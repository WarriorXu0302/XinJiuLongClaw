"""
/api/mall/admin/users/*

管理员管理 mall_users（C 端用户 + 业务员）。
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
        "referrer_bound_at": u.referrer_bound_at,
        "referrer_last_changed_at": u.referrer_last_changed_at,
        "referrer_change_reason": u.referrer_change_reason,
        "last_order_at": u.last_order_at,
        "archived_at": u.archived_at,
        "created_at": u.created_at,
    }


@router.get("")
async def list_users(
    user: CurrentUser,
    status: Optional[str] = Query(default=None),
    user_type: Optional[str] = Query(default=None, description="consumer / salesman"),
    referrer_id: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="昵称/手机号/用户名关键词"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """C 端用户 / 业务员列表。

    额外返回：
      - order_count：已成交订单数（completed + partial_closed）
      - total_gmv：累计实收金额
      - referrer_nickname：推荐人昵称（C 端用户有）
    """
    from app.models.mall.order import MallOrder

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

    if not rows:
        return {"records": [], "total": 0}

    # 批量聚合订单数 + GMV
    user_ids = [u.id for u in rows]
    order_stats = dict((await db.execute(
        select(
            MallOrder.user_id,
            func.count(MallOrder.id).label("cnt"),
            func.coalesce(func.sum(MallOrder.received_amount), 0).label("gmv"),
        )
        .where(MallOrder.user_id.in_(user_ids))
        .where(MallOrder.status.in_(["completed", "partial_closed"]))
        .group_by(MallOrder.user_id)
    )).all()).items() if False else {}  # 下面再写
    # 重写：row 元组不能用 dict() 这种技巧
    stats_rows = (await db.execute(
        select(
            MallOrder.user_id,
            func.count(MallOrder.id),
            func.coalesce(func.sum(MallOrder.received_amount), 0),
        )
        .where(MallOrder.user_id.in_(user_ids))
        .where(MallOrder.status.in_(["completed", "partial_closed"]))
        .group_by(MallOrder.user_id)
    )).all()
    stats_map = {uid: (cnt, gmv) for uid, cnt, gmv in stats_rows}

    # 批量取推荐人昵称
    referrer_ids = list({u.referrer_salesman_id for u in rows if u.referrer_salesman_id})
    ref_map = {}
    if referrer_ids:
        ref_rows = (await db.execute(
            select(MallUser).where(MallUser.id.in_(referrer_ids))
        )).scalars().all()
        ref_map = {r.id: r for r in ref_rows}

    records = []
    for u in rows:
        cnt, gmv = stats_map.get(u.id, (0, 0))
        ref = ref_map.get(u.referrer_salesman_id) if u.referrer_salesman_id else None
        records.append({
            **_user_dict(u),
            "order_count": int(cnt),
            "total_gmv": str(gmv or 0),
            "referrer_nickname": ref.nickname if ref else None,
            "referrer_phone": ref.phone if ref else None,
        })
    return {"records": records, "total": total}


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """详情 = 用户信息 + 订单历史（最多 20 条）+ 登录日志（最多 10 条）+ 地址"""
    from app.models.mall.order import MallOrder
    from app.models.mall.user import MallAddress, MallLoginLog

    require_role(user, "admin", "boss", "finance")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 推荐人
    ref = None
    if u.referrer_salesman_id:
        ref = await db.get(MallUser, u.referrer_salesman_id)

    # 订单历史
    orders = (await db.execute(
        select(MallOrder)
        .where(MallOrder.user_id == user_id)
        .order_by(desc(MallOrder.created_at))
        .limit(20)
    )).scalars().all()

    # 登录日志
    logs = (await db.execute(
        select(MallLoginLog)
        .where(MallLoginLog.user_id == user_id)
        .order_by(desc(MallLoginLog.login_at))
        .limit(10)
    )).scalars().all()

    # 地址
    addrs = (await db.execute(
        select(MallAddress)
        .where(MallAddress.user_id == user_id)
        .order_by(desc(MallAddress.is_default), MallAddress.id)
    )).scalars().all()

    # 聚合订单统计
    stats = (await db.execute(
        select(
            func.count(MallOrder.id),
            func.coalesce(func.sum(MallOrder.received_amount), 0),
        )
        .where(MallOrder.user_id == user_id)
        .where(MallOrder.status.in_(["completed", "partial_closed"]))
    )).one()
    order_count, total_gmv = int(stats[0] or 0), str(stats[1] or 0)

    return {
        **_user_dict(u),
        "referrer": ({
            "id": ref.id, "nickname": ref.nickname, "phone": ref.phone,
        } if ref else None),
        "order_count": order_count,
        "total_gmv": total_gmv,
        "orders": [
            {
                "id": o.id,
                "order_no": o.order_no,
                "status": o.status,
                "payment_status": o.payment_status,
                "total_amount": str(o.total_amount),
                "received_amount": str(o.received_amount or 0),
                "created_at": o.created_at,
                "completed_at": o.completed_at,
                "cancelled_at": o.cancelled_at,
            }
            for o in orders
        ],
        "login_logs": [
            {
                "id": l.id,
                "login_at": l.login_at,
                "login_method": l.login_method,
                "ip_address": l.ip_address,
                "user_agent": l.user_agent,
                "client_app": l.client_app,
            }
            for l in logs
        ],
        "addresses": [
            {
                "id": a.id,
                "receiver": a.receiver,
                "mobile": a.mobile,
                "province": a.province, "city": a.city, "area": a.area,
                "addr": a.addr,
                "is_default": a.is_default,
            }
            for a in addrs
        ],
    }


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
    request: Request,
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
        user=user, request=request,
        changes={"from_status": old_status, "to_status": "active", "reason": body.reason},
    )
    await db.flush()
    return _user_dict(u)


@router.post("/{user_id}/disable")
async def disable(
    user_id: str,
    body: _StatusBody,
    user: CurrentUser,
    request: Request,
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
        user=user, request=request,
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
    request: Request,
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
        user=user, request=request,
        changes={"from": old, "to": body.new_referrer_id, "reason": body.reason},
    )
    await db.flush()

    # 通知涉及的两个业务员 + 消费者本人（推荐关系变更会影响服务对接，三方都要知道）
    from app.services.notification_service import notify_mall_user
    customer_nick = u.nickname or u.username or "客户"
    new_nick = None
    if body.new_referrer_id:
        new_ref = await db.get(MallUser, body.new_referrer_id)
        new_nick = new_ref.nickname or new_ref.username or "新业务员" if new_ref else "新业务员"
    if old and old != body.new_referrer_id:
        await notify_mall_user(
            db, mall_user_id=old,
            title="客户推荐关系变更",
            content=f"客户「{customer_nick}」已由管理员调整推荐关系，原因：{body.reason}",
            entity_type="MallUser", entity_id=u.id,
        )
    if body.new_referrer_id and body.new_referrer_id != old:
        await notify_mall_user(
            db, mall_user_id=body.new_referrer_id,
            title="新增推荐客户",
            content=f"管理员将客户「{customer_nick}」的推荐关系绑定到您。",
            entity_type="MallUser", entity_id=u.id,
        )
    # 消费者本人：换绑了要告诉他"您的业务员已调整"
    if old != body.new_referrer_id:
        if body.new_referrer_id:
            await notify_mall_user(
                db, mall_user_id=u.id,
                title="您的业务员已调整",
                content=f"管理员已为您调整对接业务员「{new_nick}」，后续订单将由该业务员服务。",
                entity_type="MallUser", entity_id=u.id,
            )
        else:
            await notify_mall_user(
                db, mall_user_id=u.id,
                title="推荐业务员已解绑",
                content="管理员已解除您的推荐业务员绑定，下单前需重新联系业务员获取邀请码。",
                entity_type="MallUser", entity_id=u.id,
            )

    return _user_dict(u)


# =============================================================================
# 辅助：active 业务员下拉（换绑用）
# =============================================================================

@router.get("/_helpers/salesmen")
async def list_salesmen_helper(
    user: CurrentUser,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    stmt = select(MallUser).where(
        MallUser.user_type == MallUserType.SALESMAN.value
    ).where(MallUser.status == MallUserStatus.ACTIVE.value)
    if keyword:
        kw = f"%{keyword}%"
        from sqlalchemy import or_
        stmt = stmt.where(or_(
            MallUser.nickname.ilike(kw),
            MallUser.phone.ilike(kw),
            MallUser.username.ilike(kw),
        ))
    stmt = stmt.order_by(MallUser.created_at).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {"id": u.id, "nickname": u.nickname, "phone": u.phone, "username": u.username}
            for u in rows
        ]
    }
