"""
/api/mall/salesman/stats
/api/mall/salesman/order-count-badges

看板统计 + tabBar 角标数。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.base import MallOrderStatus
from app.models.mall.order import MallOrder
from app.models.user import Commission
from app.services.mall import auth_service
from app.services.mall.order_service import unclaim_timeout_cutoff

router = APIRouter()
TZ_BJ = ZoneInfo("Asia/Shanghai")


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


def _range_window(range_key: str) -> tuple[datetime, datetime]:
    """按业务时区（北京）返 (start, end) aware datetime（UTC）。"""
    now = datetime.now(TZ_BJ)
    end = now
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "week":
        # ISO 周一起
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif range_key == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise HTTPException(status_code=400, detail="range 只能是 today/week/month")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("")
async def stats(
    current: CurrentMallUser,
    range: str = Query(default="month", alias="range"),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    start, end = _range_window(range)

    # 已成交订单数 / GMV：
    # - completed 订单按 completed_at 落窗口
    # - partial_closed 订单 completed_at 故意留空（见 job_detect_partial_close 注释），
    #   改用 delivered_at 落窗口（实际交付完成时刻最贴近"成交月份"）
    # 两类合并统计，避免 partial_closed 在 stats 里消失
    from sqlalchemy import or_
    done_stats = (await db.execute(
        select(
            func.count(MallOrder.id).label("cnt"),
            func.coalesce(func.sum(MallOrder.received_amount), 0).label("gmv"),
        )
        .where(MallOrder.assigned_salesman_id == user.id)
        .where(or_(
            and_(
                MallOrder.status == MallOrderStatus.COMPLETED.value,
                MallOrder.completed_at.is_not(None),
                MallOrder.completed_at >= start,
                MallOrder.completed_at <= end,
            ),
            and_(
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                MallOrder.delivered_at.is_not(None),
                MallOrder.delivered_at >= start,
                MallOrder.delivered_at <= end,
            ),
        ))
    )).one()

    month_orders = int(done_stats.cnt or 0)
    month_gmv = Decimal(str(done_stats.gmv or 0))

    # 提成（绑定的 employee_id）
    pending_sum = Decimal("0")
    settled_sum = Decimal("0")
    if user.linked_employee_id:
        com_rows = (await db.execute(
            select(Commission.status, func.coalesce(func.sum(Commission.commission_amount), 0))
            .where(Commission.employee_id == user.linked_employee_id)
            .where(Commission.mall_order_id.is_not(None))
            .where(Commission.created_at >= start)
            .where(Commission.created_at <= end)
            .group_by(Commission.status)
        )).all()
        for st, amount in com_rows:
            if st == "settled":
                settled_sum = Decimal(str(amount or 0))
            else:
                pending_sum = Decimal(str(amount or 0))

    return {
        "range": range,
        "month_orders": month_orders,
        "month_gmv": str(month_gmv),
        "month_commission_pending": str(pending_sum),
        "month_commission_settled": str(settled_sum),
    }


@router.get("/order-count-badges")
async def badges(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    cutoff = unclaim_timeout_cutoff()

    async def _cnt(*clauses):
        stmt = select(func.count(MallOrder.id)).where(and_(*clauses))
        return int((await db.execute(stmt)).scalar() or 0)

    my_pool = await _cnt(
        MallOrder.status == MallOrderStatus.PENDING_ASSIGNMENT.value,
        MallOrder.referrer_salesman_id == user.id,
        MallOrder.created_at > cutoff,
    )
    public_pool = await _cnt(
        MallOrder.status == MallOrderStatus.PENDING_ASSIGNMENT.value,
        MallOrder.created_at <= cutoff,
    )
    in_transit = await _cnt(
        MallOrder.assigned_salesman_id == user.id,
        MallOrder.status.in_([
            MallOrderStatus.ASSIGNED.value,
            MallOrderStatus.SHIPPED.value,
        ]),
    )
    awaiting_payment = await _cnt(
        MallOrder.assigned_salesman_id == user.id,
        MallOrder.status == MallOrderStatus.DELIVERED.value,
    )
    awaiting_finance = await _cnt(
        MallOrder.assigned_salesman_id == user.id,
        MallOrder.status == MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
    )

    return {
        "my_pool": my_pool,
        "public_pool": public_pool,
        "in_transit": in_transit,
        "awaiting_payment": awaiting_payment,
        "awaiting_finance": awaiting_finance,
    }
