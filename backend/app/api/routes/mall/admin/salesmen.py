"""
/api/mall/admin/salesmen/*

管理员管理业务员账号。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser, get_password_hash
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
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


@router.get("")
async def list_salesmen(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    rows = (await db.execute(
        select(MallUser)
        .where(MallUser.user_type == MallUserType.SALESMAN.value)
        .order_by(desc(MallUser.created_at))
    )).scalars().all()
    return {"records": [_salesman_dict(r) for r in rows]}


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
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    # 校验 employee 存在
    emp = await db.get(Employee, body.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="linked_employee_id 指向的员工不存在")

    # 校验 employee 没被其他 salesman 占用（1 employee → 1 mall salesman）
    dup_emp = (await db.execute(
        select(MallUser)
        .where(MallUser.linked_employee_id == body.linked_employee_id)
        .where(MallUser.user_type == MallUserType.SALESMAN.value)
    )).scalar_one_or_none()
    if dup_emp:
        raise HTTPException(
            status_code=409,
            detail=f"员工 {body.linked_employee_id} 已绑定业务员账号 {dup_emp.username}",
        )

    # 校验 username 唯一（软查 + DB 唯一兜底）
    dup = (await db.execute(
        select(MallUser).where(MallUser.username == body.username)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="账号已存在")

    sm = MallUser(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        phone=body.phone,
        nickname=body.nickname or body.username,
        status=MallUserStatus.ACTIVE.value,
        user_type=MallUserType.SALESMAN.value,
        linked_employee_id=body.linked_employee_id,
        assigned_brand_id=body.assigned_brand_id,
        is_accepting_orders=True,
        must_change_password=True,  # 强制首次登录改密
        token_version=1,
    )
    db.add(sm)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail="账号冲突，请稍后重试") from e

    await log_audit(
        db,
        action="mall_salesman.create",
        entity_type="MallUser",
        entity_id=sm.id,
        user=user,
        changes={
            "username": body.username,
            "linked_employee_id": body.linked_employee_id,
            "assigned_brand_id": body.assigned_brand_id,
        },
    )
    return _salesman_dict(sm)


class _ResetPwdBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


@router.put("/{salesman_id}/reset-password")
async def reset_password(
    salesman_id: str,
    body: _ResetPwdBody,
    user: CurrentUser,
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
        db,
        action="mall_salesman.reset_password",
        entity_type="MallUser",
        entity_id=sm.id,
        user=user,
        changes={"username": sm.username},
    )
    await db.flush()
    return {"success": True, "must_change_password": True}
