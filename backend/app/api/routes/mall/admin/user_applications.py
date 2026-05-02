"""
/api/mall/admin/user-applications/*

消费者注册审批端点（admin/boss）：
  GET /          列表（默认 status=pending）
  GET /{id}      详情（含营业执照 URL / 推荐业务员 / 邀请码信息）
  POST /{id}/approve  审批通过
  POST /{id}/reject   审批驳回（必填 reason；邀请码不退回 —— 用户需重新找业务员拿码）

驳回并不真正"作废"已消费的邀请码（因为它已 used_at 标记）；
用户若要重试需找业务员重新签发新码（新账号 username/openid 必须不同）。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.base import MallUserApplicationStatus
from app.models.mall.user import MallInviteCode, MallUser
from app.services.audit_service import log_audit

router = APIRouter()


def _to_dict(u: MallUser, *, referrer: Optional[MallUser] = None) -> dict:
    return {
        "id": u.id,
        "application_status": u.application_status,
        "username": u.username,
        "nickname": u.nickname,
        "real_name": u.real_name,
        "contact_phone": u.contact_phone,
        "delivery_address": u.delivery_address,
        "business_license_url": u.business_license_url,
        "rejection_reason": u.rejection_reason,
        "approved_at": u.approved_at,
        "approved_by_employee_id": u.approved_by_employee_id,
        "referrer_salesman": {
            "id": referrer.id, "nickname": referrer.nickname, "phone": referrer.phone,
        } if referrer else None,
        "created_at": u.created_at,
    }


@router.get("")
async def list_applications(
    user: CurrentUser,
    status: Optional[str] = Query(default="pending"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    stmt = select(MallUser).where(
        MallUser.user_type == "consumer"
    )
    if status and status != "all":
        stmt = stmt.where(MallUser.application_status == status)

    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(MallUser.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    # 批量 join 推荐人
    ref_ids = list({r.referrer_salesman_id for r in rows if r.referrer_salesman_id})
    ref_map: dict[str, MallUser] = {}
    if ref_ids:
        refs = (await db.execute(
            select(MallUser).where(MallUser.id.in_(ref_ids))
        )).scalars().all()
        ref_map = {r.id: r for r in refs}

    return {
        "records": [_to_dict(u, referrer=ref_map.get(u.referrer_salesman_id)) for u in rows],
        "total": total,
    }


@router.get("/{user_id}")
async def get_application(
    user_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    u = await db.get(MallUser, user_id)
    if u is None or u.user_type != "consumer":
        raise HTTPException(status_code=404, detail="申请不存在")
    ref = await db.get(MallUser, u.referrer_salesman_id) if u.referrer_salesman_id else None
    return _to_dict(u, referrer=ref)


class _ApproveBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/{user_id}/approve")
async def approve_application(
    user_id: str,
    body: _ApproveBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    u = await db.get(MallUser, user_id)
    if u is None or u.user_type != "consumer":
        raise HTTPException(status_code=404, detail="申请不存在")
    if u.application_status != MallUserApplicationStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"申请状态 {u.application_status} 不可通过",
        )

    u.application_status = MallUserApplicationStatus.APPROVED.value
    u.approved_at = datetime.now(timezone.utc)
    u.approved_by_employee_id = user.get("employee_id")
    u.rejection_reason = None  # 清掉之前的拒绝理由（若之前拒了再通过，不保留旧理由）
    await db.flush()

    await log_audit(
        db, action="mall_user_application.approve",
        entity_type="MallUser", entity_id=u.id,
        user=user, request=request,
        changes={
            "real_name": u.real_name,
            "contact_phone": u.contact_phone,
            "note": body.note,
        },
    )

    # 通知用户审批通过
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db, mall_user_id=u.id,
        title="账号审批通过",
        content=f"恭喜您，您的注册申请已通过审核，现在可以登录使用鑫久隆批发商城了。",
        entity_type="MallUser", entity_id=u.id,
    )
    return _to_dict(u)


class _RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{user_id}/reject")
async def reject_application(
    user_id: str,
    body: _RejectBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    u = await db.get(MallUser, user_id)
    if u is None or u.user_type != "consumer":
        raise HTTPException(status_code=404, detail="申请不存在")
    if u.application_status != MallUserApplicationStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"申请状态 {u.application_status} 不可驳回",
        )

    u.application_status = MallUserApplicationStatus.REJECTED.value
    u.rejection_reason = body.reason
    # bump token_version 防并发已签过的 token（虽然 pending 阶段不签，保险）
    u.token_version = (u.token_version or 0) + 1

    # 邀请码已消费状态不变（plan：拒绝不退码，用户重申请需新码）
    # 但审计上标注该码关联的注册被驳回，便于业务员侧后续追查
    if u.referrer_salesman_id:
        invite = (await db.execute(
            select(MallInviteCode).where(MallInviteCode.used_by_user_id == u.id)
        )).scalar_one_or_none()
        if invite and not invite.invalidated_at:
            # 决策：拒绝时邀请码自动作废（标 invalidated_at），避免和"已使用"状态混淆；
            # 用户想重新注册只能找业务员要新码
            invite.invalidated_at = datetime.now(timezone.utc)
            invite.invalidated_reason = f"注册申请被驳回：{body.reason}"

    await db.flush()

    await log_audit(
        db, action="mall_user_application.reject",
        entity_type="MallUser", entity_id=u.id,
        user=user, request=request,
        changes={
            "real_name": u.real_name,
            "contact_phone": u.contact_phone,
            "reason": body.reason,
        },
    )

    # 通知用户审批驳回 —— pending 阶段的用户 nickname 已存好，notify_mall_user 走 mall_user_id 路径
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db, mall_user_id=u.id,
        title="账号审批未通过",
        content=f"您的注册申请未通过审核。原因：{body.reason}。如有疑问请联系业务员。",
        entity_type="MallUser", entity_id=u.id,
    )
    return _to_dict(u)
