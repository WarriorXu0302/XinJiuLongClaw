"""
Authentication API routes — login, token refresh, user info.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import admin_session_factory, get_db, get_db_anon
from app.core.security import (
    CurrentUser,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.user import Role, User, UserRole
from app.models.payroll import EmployeeBrandPosition
from app.services.audit_service import log_audit

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    employee_id: str | None
    roles: list[str]
    brand_ids: list[str] = []


async def build_jwt_payload(db: AsyncSession, user: User) -> dict:
    """构造 JWT payload。login 和 /api/feishu/exchange-token 共用同一份逻辑。

    Why：两处产出的 token 必须字段一致，否则 MCP RBAC / RLS 会因漏字段误判。
    如新增字段，只改这里一处。
    """
    roles = [ur.role.code for ur in user.roles if ur.role]
    is_admin = any(r in ('admin', 'boss') for r in roles)
    # 跨品牌可见角色：财务/HR/管理员看所有品牌数据
    see_all_brands = is_admin or any(r in ('finance', 'hr') for r in roles)

    brand_ids: list[str] = []
    if see_all_brands:
        from app.models.product import Brand
        all_bids = (await db.execute(select(Brand.id))).scalars().all()
        brand_ids = list(all_bids)
    elif user.employee_id:
        ebs = (await db.execute(
            select(EmployeeBrandPosition.brand_id)
            .where(EmployeeBrandPosition.employee_id == user.employee_id)
            .distinct()
        )).scalars().all()
        brand_ids = list(ebs)

    return {
        "sub": user.id,
        "username": user.username,
        "employee_id": user.employee_id,
        "roles": roles,
        "brand_ids": brand_ids,
        "is_admin": is_admin,
        "can_see_master": is_admin,
    }


async def _audit_login_failure(
    request: Request, username: str, user_obj: User | None,
    status_code: int, reason: str,
):
    """登录失败审计 —— 独立 session，和主事务解耦。

    注意：audit_logs.actor_id FK → employees.id；
    用户不一定绑定 employee（如纯管理员），所以 actor_id 只在 user.employee_id 存在时写。
    entity_id 写 user.id（User 表的主键），便于按账户反查。
    """
    async with admin_session_factory() as s:
        await log_audit(
            s, action="user.login_failed",
            entity_type="User",
            entity_id=user_obj.id if user_obj else None,
            actor_id=user_obj.employee_id if user_obj else None,
            actor_type="employee" if user_obj else "anonymous",
            request=request,
            changes={
                "username_tried": username,
                "user_id": user_obj.id if user_obj else None,
                "user_exists": bool(user_obj),
                "status_code": status_code,
                "reason": reason,
            },
        )
        await s.commit()


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db_anon)):
    user = (
        await db.execute(
            select(User)
            .where(User.username == body.username)
            .options(selectinload(User.roles).selectinload(UserRole.role))
        )
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        await _audit_login_failure(
            request, body.username, user, 401, "Incorrect username or password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        await _audit_login_failure(
            request, body.username, user, 403, "Account is disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token_data = await build_jwt_payload(db, user)
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    token_data = {
        "sub": payload["sub"],
        "username": payload.get("username"),
        "employee_id": payload.get("employee_id"),
        "roles": payload.get("roles", []),
        "brand_ids": payload.get("brand_ids", []),
        "is_admin": payload.get("is_admin", False),
        "can_see_master": payload.get("can_see_master", False),
    }
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get("/me", response_model=UserInfoResponse)
async def get_me(user: CurrentUser):
    return UserInfoResponse(
        user_id=user["sub"],
        username=user.get("username", ""),
        employee_id=user.get("employee_id"),
        roles=user.get("roles", []),
        brand_ids=user.get("brand_ids", []),
    )


# ═══════════════════════════════════════════════════════════════════
# User Management (admin only)
# ═══════════════════════════════════════════════════════════════════

import uuid


class CreateUserRequest(BaseModel):
    username: str
    password: str
    employee_id: str | None = None
    role_codes: list[str] = []


class UpdateUserRequest(BaseModel):
    username: str | None = None
    employee_id: str | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class SetRolesRequest(BaseModel):
    role_codes: list[str]


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id, "username": u.username,
        "employee_id": u.employee_id,
        "is_active": u.is_active, "is_superuser": u.is_superuser,
        "roles": [ur.role.code for ur in u.roles if ur.role] if u.roles else [],
        "employee_name": u.employee.name if u.employee else None,
        "created_at": str(u.created_at) if u.created_at else None,
    }


@router.get("/users")
async def list_users(
    user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List all user accounts."""
    from app.core.permissions import require_role
    require_role(user, "boss", "hr")
    from sqlalchemy import func
    base = select(User)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.options(
            selectinload(User.roles).selectinload(UserRole.role),
            selectinload(User.employee),
        ).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return {"items": [_user_to_dict(u) for u in rows], "total": total}


@router.post("/users", status_code=201)
async def create_user(body: CreateUserRequest, user: CurrentUser, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new user account with optional role assignment."""
    from app.core.permissions import require_role
    require_role(user, "boss")
    existing = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"用户名 '{body.username}' 已存在")

    new_user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        hashed_password=get_password_hash(body.password),
        employee_id=body.employee_id,
    )
    db.add(new_user)
    await db.flush()

    # Assign roles
    if body.role_codes:
        roles = (await db.execute(select(Role).where(Role.code.in_(body.role_codes)))).scalars().all()
        for r in roles:
            db.add(UserRole(id=str(uuid.uuid4()), user_id=new_user.id, role_id=r.id))
        await db.flush()

    # 审计：创建账户
    await log_audit(
        db, action="user.create", entity_type="User",
        entity_id=new_user.id, user=user, request=request,
        changes={
            "username": new_user.username,
            "employee_id": new_user.employee_id,
            "role_codes": body.role_codes or [],
        },
    )

    # Re-fetch with relationships
    refreshed = (await db.execute(
        select(User).where(User.id == new_user.id)
        .options(selectinload(User.roles).selectinload(UserRole.role), selectinload(User.employee))
    )).scalar_one()
    return _user_to_dict(refreshed)


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserRequest, user: CurrentUser, request: Request, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")
    changes: dict = {}
    if body.username is not None and body.username != u.username:
        changes["username"] = {"from": u.username, "to": body.username}
        u.username = body.username
    if body.employee_id is not None:
        new_emp = body.employee_id or None
        if new_emp != u.employee_id:
            changes["employee_id"] = {"from": u.employee_id, "to": new_emp}
            u.employee_id = new_emp
    if body.is_active is not None and body.is_active != u.is_active:
        changes["is_active"] = {"from": u.is_active, "to": body.is_active}
        u.is_active = body.is_active
    await db.flush()

    if changes:
        await log_audit(
            db, action="user.update", entity_type="User",
            entity_id=u.id, user=user, request=request,
            changes={"username": u.username, **changes},
        )

    refreshed = (await db.execute(
        select(User).where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role), selectinload(User.employee))
    )).scalar_one()
    return _user_to_dict(refreshed)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, body: ResetPasswordRequest, user: CurrentUser, request: Request, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")
    u.hashed_password = get_password_hash(body.new_password)

    # 审计：重置密码（敏感账户操作）
    await log_audit(
        db, action="user.reset_password", entity_type="User",
        entity_id=u.id, user=user, request=request,
        changes={"username": u.username},
    )

    await db.flush()
    return {"detail": "密码已重置"}


@router.put("/users/{user_id}/roles")
async def set_user_roles(user_id: str, body: SetRolesRequest, user: CurrentUser, request: Request, db: AsyncSession = Depends(get_db)):
    """Replace all roles for a user."""
    from app.core.permissions import require_role
    require_role(user, "boss")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")

    # 查旧角色用于审计
    old_roles = (await db.execute(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )).scalars().all()

    # Delete existing roles
    existing = (await db.execute(select(UserRole).where(UserRole.user_id == user_id))).scalars().all()
    for ur in existing:
        await db.delete(ur)
    await db.flush()

    # Add new roles
    if body.role_codes:
        roles = (await db.execute(select(Role).where(Role.code.in_(body.role_codes)))).scalars().all()
        for r in roles:
            db.add(UserRole(id=str(uuid.uuid4()), user_id=user_id, role_id=r.id))

    await db.flush()

    # 审计：角色变更是最高级别权限变动，必记
    await log_audit(
        db, action="user.set_roles", entity_type="User",
        entity_id=u.id, user=user, request=request,
        changes={
            "username": u.username,
            "from": sorted(old_roles),
            "to": sorted(body.role_codes or []),
        },
    )

    refreshed = (await db.execute(
        select(User).where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role), selectinload(User.employee))
    )).scalar_one()
    return _user_to_dict(refreshed)


@router.get("/roles")
async def list_roles(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """List all available roles."""
    rows = (await db.execute(select(Role).order_by(Role.code))).scalars().all()
    return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]
