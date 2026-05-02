"""
/api/mall/admin/invite-codes/*

运营查邀请码 + 作废异常码。

业务场景：
  - 监控业务员发码情况（谁每天发最多？发后转化率）
  - 发现业务员乱发码/刷推荐人时作废
  - 审计：每条码都能追溯到签发业务员 / 使用消费者
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.user import MallInviteCode, MallUser
from app.services.audit_service import log_audit

router = APIRouter()


def _code_status(c: MallInviteCode, now: datetime) -> str:
    if c.invalidated_at:
        return "invalidated"
    if c.used_at:
        return "used"
    if c.expires_at and c.expires_at < now:
        return "expired"
    return "active"


@router.get("")
async def list_invite_codes(
    user: CurrentUser,
    status: Optional[str] = Query(default=None, description="active/used/expired/invalidated"),
    issuer_id: Optional[str] = Query(default=None, description="按签发业务员过滤"),
    code: Optional[str] = Query(default=None, description="精确查码"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD 按签发时间"),
    date_to: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    now = datetime.now(timezone.utc)

    stmt = select(MallInviteCode)
    if code:
        stmt = stmt.where(MallInviteCode.code == code.upper())
    if issuer_id:
        stmt = stmt.where(MallInviteCode.issuer_salesman_id == issuer_id)
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            stmt = stmt.where(MallInviteCode.created_at >= df)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from 格式 YYYY-MM-DD")
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to) + timedelta(days=1)
            stmt = stmt.where(MallInviteCode.created_at < dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to 格式 YYYY-MM-DD")

    # 状态派生过滤
    if status == "active":
        stmt = stmt.where(
            MallInviteCode.used_at.is_(None),
            MallInviteCode.invalidated_at.is_(None),
            MallInviteCode.expires_at > now,
        )
    elif status == "used":
        stmt = stmt.where(MallInviteCode.used_at.isnot(None))
    elif status == "expired":
        stmt = stmt.where(
            MallInviteCode.used_at.is_(None),
            MallInviteCode.invalidated_at.is_(None),
            MallInviteCode.expires_at <= now,
        )
    elif status == "invalidated":
        stmt = stmt.where(MallInviteCode.invalidated_at.isnot(None))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallInviteCode.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    # 批量取 issuer + used_by
    user_ids = {r.issuer_salesman_id for r in rows}
    user_ids.update({r.used_by_user_id for r in rows if r.used_by_user_id})
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    records = []
    for r in rows:
        issuer = user_map.get(r.issuer_salesman_id)
        used_by = user_map.get(r.used_by_user_id) if r.used_by_user_id else None
        records.append({
            "id": r.id,
            "code": r.code,
            "status": _code_status(r, now),
            "issuer": ({
                "id": issuer.id, "nickname": issuer.nickname, "phone": issuer.phone,
            } if issuer else None),
            "used_by": ({
                "id": used_by.id, "nickname": used_by.nickname, "phone": used_by.phone,
            } if used_by else None),
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "used_at": r.used_at,
            "invalidated_at": r.invalidated_at,
            "invalidated_reason": r.invalidated_reason,
        })
    return {"records": records, "total": total}


@router.get("/stats")
async def invite_code_stats(
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """按业务员统计近 N 天：签发 / 使用 / 作废 / 使用率。

    识别"刷码"或"低转化"业务员。
    """
    require_role(user, "admin", "boss")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    stmt = (
        select(
            MallInviteCode.issuer_salesman_id,
            sa_func.count(MallInviteCode.id).label("issued"),
            sa_func.sum(case((MallInviteCode.used_at.isnot(None), 1), else_=0)).label("used"),
            sa_func.sum(case((MallInviteCode.invalidated_at.isnot(None), 1), else_=0)).label("invalidated"),
        )
        .where(MallInviteCode.created_at >= since)
        .group_by(MallInviteCode.issuer_salesman_id)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"records": [], "days": days}

    issuer_ids = [r[0] for r in rows]
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(issuer_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    records = []
    for issuer_id, issued, used, invalidated in rows:
        u = user_map.get(issuer_id)
        issued_n = int(issued or 0)
        used_n = int(used or 0)
        invalidated_n = int(invalidated or 0)
        # 有效签发 = 总签发 - 作废（否则业务员改错重签会导致分母虚高、使用率虚低）
        valid_issued = max(issued_n - invalidated_n, 0)
        usage_rate = (used_n / valid_issued * 100) if valid_issued > 0 else 0
        records.append({
            "issuer_id": issuer_id,
            "issuer_nickname": u.nickname if u else None,
            "issuer_phone": u.phone if u else None,
            "issued": issued_n,
            "used": used_n,
            "invalidated": invalidated_n,
            "valid_issued": valid_issued,
            "usage_rate": round(usage_rate, 1),
        })
    records.sort(key=lambda r: r["valid_issued"], reverse=True)
    return {"records": records, "days": days}


# =============================================================================
# 作废
# =============================================================================

class _InvalidateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


@router.post("/{code_id}/invalidate")
async def invalidate_code(
    code_id: str,
    body: _InvalidateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """作废邀请码。仅 active 状态可作废。"""
    require_role(user, "admin", "boss")
    c = await db.get(MallInviteCode, code_id)
    if c is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")

    now = datetime.now(timezone.utc)
    cur_status = _code_status(c, now)
    if cur_status != "active":
        raise HTTPException(status_code=400, detail=f"该码状态 {cur_status}，不可作废")

    c.invalidated_at = now
    c.invalidated_reason = body.reason

    await log_audit(
        db, action="mall_invite_code.invalidate",
        entity_type="MallInviteCode", entity_id=c.id, user=user, request=request,
        changes={
            "code": c.code, "issuer_id": c.issuer_salesman_id,
            "reason": body.reason,
        },
    )
    await db.flush()

    # 通知业务员：你发的邀请码被管理员作废了
    if c.issuer_salesman_id:
        from app.services.notification_service import notify_mall_user
        await notify_mall_user(
            db, mall_user_id=c.issuer_salesman_id,
            title="邀请码已被作废",
            content=f"您签发的邀请码 {c.code} 已被管理员作废。原因：{body.reason or '未注明'}",
            entity_type="MallInviteCode", entity_id=c.id,
        )

    return {
        "id": c.id, "code": c.code, "status": "invalidated",
        "invalidated_at": c.invalidated_at,
    }
