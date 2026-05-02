"""
/api/mall/admin/salesmen/*

管理员管理业务员账号。

端点：
  GET  /                     列表（分页 + 搜索 + 状态过滤，附带 employee/brand 信息）
  POST /                     新建业务员
  GET  /{id}                 详情
  PUT  /{id}                 更新（nickname / phone / assigned_brand_id）
  POST /{id}/disable         禁用（token_version +1 → 立即踢下线）
  POST /{id}/enable          启用
  PUT  /{id}/reset-password  重置密码

  GET  /_helpers/employees   可绑定 employee 下拉（未被其他 salesman 占用、active）
  GET  /_helpers/brands      品牌下拉
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser, get_password_hash
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
from app.models.product import Brand
from app.models.user import Employee
from app.services.audit_service import log_audit

router = APIRouter()


def _salesman_dict(u: MallUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "phone": u.phone,
        "status": u.status,
        "linked_employee_id": u.linked_employee_id,
        "assigned_brand_id": u.assigned_brand_id,
        "is_accepting_orders": u.is_accepting_orders,
        "must_change_password": u.must_change_password,
        "created_at": u.created_at,
    }


# =============================================================================
# 列表（分页 + 搜索 + 关联 employee/brand）
# =============================================================================

@router.get("")
async def list_salesmen(
    user: CurrentUser,
    keyword: Optional[str] = Query(default=None, description="昵称/手机/用户名"),
    status: Optional[str] = Query(default=None, description="active/disabled/inactive_archived"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    stmt = select(MallUser).where(MallUser.user_type == MallUserType.SALESMAN.value)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            (MallUser.username.ilike(kw))
            | (MallUser.nickname.ilike(kw))
            | (MallUser.phone.ilike(kw))
        )
    if status:
        stmt = stmt.where(MallUser.status == status)

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallUser.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    emp_ids = [r.linked_employee_id for r in rows if r.linked_employee_id]
    brand_ids = [r.assigned_brand_id for r in rows if r.assigned_brand_id]

    emps = []
    brands = []
    if emp_ids:
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars().all()
    if brand_ids:
        brands = (await db.execute(
            select(Brand).where(Brand.id.in_(brand_ids))
        )).scalars().all()
    emp_map = {e.id: e for e in emps}
    brand_map = {b.id: b for b in brands}

    records = []
    for r in rows:
        emp = emp_map.get(r.linked_employee_id)
        brand = brand_map.get(r.assigned_brand_id) if r.assigned_brand_id else None
        records.append({
            **_salesman_dict(r),
            "employee": {"id": emp.id, "name": emp.name, "status": emp.status} if emp else None,
            "brand": {"id": brand.id, "name": brand.name} if brand else None,
        })
    return {"records": records, "total": total}


# =============================================================================
# 详情
# =============================================================================

@router.get("/{salesman_id}")
async def get_salesman(
    salesman_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    emp = await db.get(Employee, sm.linked_employee_id) if sm.linked_employee_id else None
    brand = await db.get(Brand, sm.assigned_brand_id) if sm.assigned_brand_id else None
    return {
        **_salesman_dict(sm),
        "employee": ({"id": emp.id, "name": emp.name, "status": emp.status} if emp else None),
        "brand": ({"id": brand.id, "name": brand.name} if brand else None),
    }


# =============================================================================
# 新建
# =============================================================================

class _CreateSalesmanBody(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    linked_employee_id: str = Field(min_length=36, max_length=36)
    assigned_brand_id: Optional[str] = None
    nickname: Optional[str] = None
    phone: Optional[str] = None


@router.post("")
async def create_salesman(
    body: _CreateSalesmanBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    emp = await db.get(Employee, body.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="linked_employee_id 指向的员工不存在")
    if emp.status != "active":
        raise HTTPException(status_code=400, detail=f"员工状态 {emp.status}，无法绑定")

    dup_emp = (await db.execute(
        select(MallUser)
        .where(MallUser.linked_employee_id == body.linked_employee_id)
        .where(MallUser.user_type == MallUserType.SALESMAN.value)
    )).scalar_one_or_none()
    if dup_emp:
        raise HTTPException(
            status_code=409,
            detail=f"员工 {emp.name} 已绑定业务员账号 {dup_emp.username}",
        )

    dup = (await db.execute(
        select(MallUser).where(MallUser.username == body.username)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="账号已存在")

    sm = MallUser(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        phone=body.phone,
        nickname=body.nickname or emp.name or body.username,
        status=MallUserStatus.ACTIVE.value,
        user_type=MallUserType.SALESMAN.value,
        linked_employee_id=body.linked_employee_id,
        assigned_brand_id=body.assigned_brand_id,
        is_accepting_orders=True,
        must_change_password=True,
        token_version=1,
    )
    db.add(sm)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail="账号冲突，请稍后重试") from e

    await log_audit(
        db, action="mall_salesman.create", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={
            "username": body.username,
            "linked_employee_id": body.linked_employee_id,
            "employee_name": emp.name,
            "assigned_brand_id": body.assigned_brand_id,
        },
    )
    return _salesman_dict(sm)


# =============================================================================
# 更新
# =============================================================================

class _UpdateSalesmanBody(BaseModel):
    nickname: Optional[str] = None
    phone: Optional[str] = None
    assigned_brand_id: Optional[str] = None  # 传空字符串或 null 清除
    is_accepting_orders: Optional[bool] = None


@router.put("/{salesman_id}")
async def update_salesman(
    salesman_id: str,
    body: _UpdateSalesmanBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    updates = body.model_dump(exclude_unset=True)
    # assigned_brand_id 空字符串视为清除
    if updates.get("assigned_brand_id") == "":
        updates["assigned_brand_id"] = None

    if "assigned_brand_id" in updates and updates["assigned_brand_id"]:
        b = await db.get(Brand, updates["assigned_brand_id"])
        if b is None:
            raise HTTPException(status_code=400, detail="品牌不存在")

    for k, v in updates.items():
        setattr(sm, k, v)
    sm.updated_at = datetime.now(timezone.utc)

    await log_audit(
        db, action="mall_salesman.update", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request, changes=updates,
    )
    await db.flush()
    return _salesman_dict(sm)


# =============================================================================
# 禁用 / 启用
# =============================================================================

class _ReasonBody(BaseModel):
    reason: Optional[str] = None


@router.post("/{salesman_id}/disable")
async def disable_salesman(
    salesman_id: str,
    body: _ReasonBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """禁用业务员。bump token_version 让所有在途 JWT 立即失效。"""
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")
    if sm.status == MallUserStatus.DISABLED.value:
        return _salesman_dict(sm)

    sm.status = MallUserStatus.DISABLED.value
    sm.token_version = (sm.token_version or 0) + 1
    sm.is_accepting_orders = False

    await log_audit(
        db, action="mall_salesman.disable", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={"username": sm.username, "reason": body.reason},
    )
    await db.flush()
    return _salesman_dict(sm)


@router.post("/{salesman_id}/enable")
async def enable_salesman(
    salesman_id: str,
    body: _ReasonBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """启用被禁用的业务员。"""
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")
    if sm.status == MallUserStatus.ACTIVE.value:
        return _salesman_dict(sm)

    sm.status = MallUserStatus.ACTIVE.value

    await log_audit(
        db, action="mall_salesman.enable", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={"username": sm.username, "reason": body.reason},
    )
    await db.flush()
    return _salesman_dict(sm)


# =============================================================================
# 重置密码
# =============================================================================

class _ResetPwdBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


@router.put("/{salesman_id}/reset-password")
async def reset_password(
    salesman_id: str,
    body: _ResetPwdBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    sm.hashed_password = get_password_hash(body.new_password)
    sm.must_change_password = True
    sm.token_version = (sm.token_version or 0) + 1

    await log_audit(
        db, action="mall_salesman.reset_password", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request, changes={"username": sm.username},
    )
    await db.flush()
    return {"success": True, "must_change_password": True}


# =============================================================================
# 辅助下拉
# =============================================================================

@router.get("/_helpers/employees")
async def list_bindable_employees(
    user: CurrentUser,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """列出可绑定的 employee（未绑定过 salesman，且 status=active）。"""
    require_role(user, "admin", "boss", "hr")

    # 已绑定过的 employee id
    bound_ids = [
        eid for eid, in (await db.execute(
            select(MallUser.linked_employee_id)
            .where(MallUser.user_type == MallUserType.SALESMAN.value)
            .where(MallUser.linked_employee_id.isnot(None))
        )).all()
    ]

    stmt = select(Employee).where(Employee.status == "active")
    if bound_ids:
        stmt = stmt.where(Employee.id.notin_(bound_ids))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where((Employee.name.ilike(kw)) | (Employee.phone.ilike(kw)))
    stmt = stmt.order_by(Employee.name).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {"id": e.id, "name": e.name, "phone": e.phone}
            for e in rows
        ]
    }


@router.get("/_helpers/brands")
async def list_brands_helper(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    rows = (await db.execute(
        select(Brand).order_by(Brand.name)
    )).scalars().all()
    return {"records": [{"id": b.id, "name": b.name} for b in rows]}
