"""
/api/mall/admin/users/*

管理员管理 mall_users（C 端用户 + 业务员）。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
from app.services.audit_service import log_audit

router = APIRouter()


def _user_dict(u: MallUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "phone": u.phone,
        "user_type": u.user_type,
        "status": u.status,
        "linked_employee_id": u.linked_employee_id,
        "referrer_salesman_id": u.referrer_salesman_id,
        "last_order_at": u.last_order_at,
        "archived_at": u.archived_at,
        "created_at": u.created_at,
    }


@router.get("")
async def list_users(
    user: CurrentUser,
    status: Optional[str] = Query(default=None),
    user_type: Optional[str] = Query(default=None),
    referrer_id: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="昵称/手机号/用户名关键词"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    stmt = select(MallUser)
    if status:
        stmt = stmt.where(MallUser.status == status)
    if user_type:
        stmt = stmt.where(MallUser.user_type == user_type)
    if referrer_id:
        stmt = stmt.where(MallUser.referrer_salesman_id == referrer_id)
    if keyword:
        like = f"%{keyword}%"
        from sqlalchemy import or_
        stmt = stmt.where(or_(
            MallUser.nickname.ilike(like),
            MallUser.phone.ilike(like),
            MallUser.username.ilike(like),
        ))
    stmt = stmt.order_by(desc(MallUser.created_at))
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return {
        "records": [_user_dict(u) for u in rows],
        "total": total,
    }


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_dict(u)


# =============================================================================
# 启用 / 禁用
# =============================================================================

class _StatusBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{user_id}/reactivate")
async def reactivate(
    user_id: str,
    body: _StatusBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """启用归档/禁用的用户。last_order_at 重置为 now，给 3 个月新的观察期。"""
    require_role(user, "admin", "boss")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.status == MallUserStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="用户已是 active 状态")

    now = datetime.now(timezone.utc)
    old_status = u.status
    u.status = MallUserStatus.ACTIVE.value
    # archived_at 不清空（保留历史归档痕迹给审计）；last_order_at 重置给新的观察期
    u.last_order_at = now
    # bump token_version（虽然之前归档已经 bump 过，此处再 bump 不影响用户，留档一致性）
    u.token_version = (u.token_version or 0) + 1

    await log_audit(
        db,
        action="mall_user.reactivate",
        entity_type="MallUser",
        entity_id=u.id,
        user=user,
        changes={"from_status": old_status, "to_status": "active", "reason": body.reason},
    )
    await db.flush()
    return _user_dict(u)


@router.post("/{user_id}/disable")
async def disable(
    user_id: str,
    body: _StatusBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.status == MallUserStatus.DISABLED.value:
        raise HTTPException(status_code=409, detail="用户已禁用")

    old_status = u.status
    u.status = MallUserStatus.DISABLED.value
    u.token_version = (u.token_version or 0) + 1
    await log_audit(
        db,
        action="mall_user.disable",
        entity_type="MallUser",
        entity_id=u.id,
        user=user,
        changes={"from_status": old_status, "to_status": "disabled", "reason": body.reason},
    )
    await db.flush()
    return _user_dict(u)


# =============================================================================
# 换绑推荐人
# =============================================================================

class _RebindBody(BaseModel):
    new_referrer_id: Optional[str] = None  # None = 解绑
    reason: str = Field(min_length=1, max_length=500)


@router.put("/{user_id}/referrer")
async def change_referrer(
    user_id: str,
    body: _RebindBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.user_type != MallUserType.CONSUMER.value:
        raise HTTPException(status_code=400, detail="仅 consumer 可换绑推荐人")

    if body.new_referrer_id:
        target = await db.get(MallUser, body.new_referrer_id)
        if target is None or target.user_type != MallUserType.SALESMAN.value:
            raise HTTPException(status_code=400, detail="目标不是业务员")
        if target.status != MallUserStatus.ACTIVE.value:
            raise HTTPException(status_code=400, detail="目标业务员状态非 active")

    old = u.referrer_salesman_id
    now = datetime.now(timezone.utc)
    u.referrer_salesman_id = body.new_referrer_id
    if body.new_referrer_id and old != body.new_referrer_id:
        u.referrer_bound_at = now
    u.referrer_last_changed_at = now
    u.referrer_change_reason = body.reason

    await log_audit(
        db,
        action="mall_user.change_referrer",
        entity_type="MallUser",
        entity_id=u.id,
        user=user,
        changes={"from": old, "to": body.new_referrer_id, "reason": body.reason},
    )
    await db.flush()
    return _user_dict(u)
