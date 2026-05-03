"""
/api/mall/admin/dashboard/*

商城运营看板。聚合端点一次返回所有卡片数据，减少前端并发请求。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, func as sa_func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.base import MallOrderStatus, MallPaymentApprovalStatus
from app.models.mall.inventory import MallInventory
from app.models.mall.order import (
    MallOrder,
    MallOrderItem,
    MallPayment,
    MallReturnRequest,
    MallSkipAlert,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallUser

router = APIRouter()

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _today_range() -> tuple[datetime, datetime]:
    """返回今日 [00:00, 明天 00:00) 的 UTC。按 Asia/Shanghai 日界。"""
    now_sh = datetime.now(SHANGHAI)
    start_sh = now_sh.replace(hour=0, minute=0, second=0, microsecond=0)
    end_sh = start_sh + timedelta(days=1)
    return start_sh.astimezone(timezone.utc), end_sh.astimezone(timezone.utc)


def _yesterday_range() -> tuple[datetime, datetime]:
    t_start, _ = _today_range()
    return t_start - timedelta(days=1), t_start


@router.get("/summary")
async def dashboard_summary(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """看板汇总：today / yesterday / pending / month / trend / salesman_rank / product_rank / low_stock。"""
    require_role(user, "admin", "boss", "finance")

    t_start, t_end = _today_range()
    y_start, y_end = _yesterday_range()
    now_sh = datetime.now(SHANGHAI)
    month_start_sh = now_sh.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start_sh.astimezone(timezone.utc)

    # ── 今日 ──────────────────────────────────────────────
    today_orders = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.created_at >= t_start)
        .where(MallOrder.created_at < t_end)
    )).scalar() or 0)

    today_received = (await db.execute(
        select(sa_func.coalesce(sa_func.sum(MallPayment.amount), 0))
        .where(MallPayment.status == MallPaymentApprovalStatus.CONFIRMED.value)
        .where(MallPayment.confirmed_at >= t_start)
        .where(MallPayment.confirmed_at < t_end)
    )).scalar() or Decimal("0")

    today_new_users = int((await db.execute(
        select(sa_func.count(MallUser.id))
        .where(MallUser.user_type == "consumer")
        .where(MallUser.created_at >= t_start)
        .where(MallUser.created_at < t_end)
    )).scalar() or 0)

    today_cancelled = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.cancelled_at >= t_start)
        .where(MallOrder.cancelled_at < t_end)
    )).scalar() or 0)

    # ── 昨日（环比）────────────────────────────────────────
    y_orders = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.created_at >= y_start)
        .where(MallOrder.created_at < y_end)
    )).scalar() or 0)
    y_received = (await db.execute(
        select(sa_func.coalesce(sa_func.sum(MallPayment.amount), 0))
        .where(MallPayment.status == MallPaymentApprovalStatus.CONFIRMED.value)
        .where(MallPayment.confirmed_at >= y_start)
        .where(MallPayment.confirmed_at < y_end)
    )).scalar() or Decimal("0")

    # ── 待处理事项 ────────────────────────────────────────
    pending_assignment = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.status == MallOrderStatus.PENDING_ASSIGNMENT.value)
    )).scalar() or 0)

    pending_confirm = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.status == MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value)
    )).scalar() or 0)

    open_alerts = int((await db.execute(
        select(sa_func.count(MallSkipAlert.id))
        .where(MallSkipAlert.status == "open")
    )).scalar() or 0)

    # 注册待审批 / 退货待审批 / 退货已通过待退款（财务侧 KPI）
    pending_applications = int((await db.execute(
        select(sa_func.count(MallUser.id))
        .where(MallUser.user_type == "consumer")
        .where(MallUser.application_status == "pending")
    )).scalar() or 0)

    pending_returns = int((await db.execute(
        select(sa_func.count(MallReturnRequest.id))
        .where(MallReturnRequest.status == "pending")
    )).scalar() or 0)

    approved_returns_awaiting_refund = int((await db.execute(
        select(sa_func.count(MallReturnRequest.id))
        .where(MallReturnRequest.status == "approved")
    )).scalar() or 0)

    # 低库存仅统计 active SKU 且所属商品 on_sale；下架商品库存低不算告警
    low_stock_count = int((await db.execute(
        select(sa_func.count(MallInventory.id))
        .join(MallProductSku, MallProductSku.id == MallInventory.sku_id)
        .join(MallProduct, MallProduct.id == MallProductSku.product_id)
        .where(MallInventory.quantity <= 10)
        .where(MallProductSku.status == "active")
        .where(MallProduct.status == "on_sale")
    )).scalar() or 0)

    # ── 本月 ──────────────────────────────────────────────
    m_orders = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.created_at >= month_start)
    )).scalar() or 0)
    m_received = (await db.execute(
        select(sa_func.coalesce(sa_func.sum(MallPayment.amount), 0))
        .where(MallPayment.status == MallPaymentApprovalStatus.CONFIRMED.value)
        .where(MallPayment.confirmed_at >= month_start)
    )).scalar() or Decimal("0")
    m_new_users = int((await db.execute(
        select(sa_func.count(MallUser.id))
        .where(MallUser.user_type == "consumer")
        .where(MallUser.created_at >= month_start)
    )).scalar() or 0)

    # ── 30 天趋势 ─────────────────────────────────────────
    trend_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    trend_start_utc = trend_start.astimezone(timezone.utc)

    order_trend_rows = (await db.execute(
        select(
            sa_func.date_trunc("day", sa_func.timezone("Asia/Shanghai", MallOrder.created_at)).label("day"),
            sa_func.count(MallOrder.id),
        )
        .where(MallOrder.created_at >= trend_start_utc)
        .group_by("day")
        .order_by("day")
    )).all()
    order_by_day = {r[0].date().isoformat(): int(r[1]) for r in order_trend_rows}

    received_trend_rows = (await db.execute(
        select(
            sa_func.date_trunc("day", sa_func.timezone("Asia/Shanghai", MallPayment.confirmed_at)).label("day"),
            sa_func.coalesce(sa_func.sum(MallPayment.amount), 0),
        )
        .where(MallPayment.status == MallPaymentApprovalStatus.CONFIRMED.value)
        .where(MallPayment.confirmed_at >= trend_start_utc)
        .group_by("day")
        .order_by("day")
    )).all()
    received_by_day = {r[0].date().isoformat(): str(r[1]) for r in received_trend_rows}

    trend = []
    for i in range(30):
        day = (trend_start + timedelta(days=i)).date().isoformat()
        trend.append({
            "day": day,
            "orders": order_by_day.get(day, 0),
            "received": received_by_day.get(day, "0"),
        })

    # ── 业务员排行（本月 GMV top 5）────────────────────────
    rank_rows = (await db.execute(
        select(
            MallOrder.assigned_salesman_id,
            sa_func.count(MallOrder.id).label("order_count"),
            sa_func.coalesce(sa_func.sum(MallOrder.received_amount), 0).label("gmv"),
        )
        .where(MallOrder.assigned_salesman_id.isnot(None))
        .where(or_(
            and_(
                MallOrder.status == MallOrderStatus.COMPLETED.value,
                MallOrder.completed_at >= month_start,
            ),
            and_(
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                MallOrder.delivered_at >= month_start,
            ),
        ))
        .group_by(MallOrder.assigned_salesman_id)
        .order_by(desc("gmv"))
        .limit(5)
    )).all()

    sm_ids = [r[0] for r in rank_rows]
    sms = (await db.execute(
        select(MallUser).where(MallUser.id.in_(sm_ids))
    )).scalars().all() if sm_ids else []
    sm_map = {s.id: s for s in sms}
    salesman_rank = []
    for sm_id, cnt, gmv in rank_rows:
        s = sm_map.get(sm_id)
        salesman_rank.append({
            "id": sm_id,
            "nickname": s.nickname if s else None,
            "phone": s.phone if s else None,
            "order_count": int(cnt),
            "gmv": str(gmv or 0),
        })

    # ── 商品销量 Top 10（本月）──────────────────────────────
    prod_rank_rows = (await db.execute(
        select(
            MallOrderItem.product_id,
            sa_func.sum(MallOrderItem.quantity).label("qty"),
            sa_func.coalesce(sa_func.sum(MallOrderItem.subtotal), 0).label("amount"),
        )
        .join(MallOrder, MallOrderItem.order_id == MallOrder.id)
        .where(or_(
            and_(
                MallOrder.status == MallOrderStatus.COMPLETED.value,
                MallOrder.completed_at >= month_start,
            ),
            and_(
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                MallOrder.delivered_at >= month_start,
            ),
        ))
        .group_by(MallOrderItem.product_id)
        .order_by(desc("qty"))
        .limit(10)
    )).all()

    p_ids = [r[0] for r in prod_rank_rows]
    prods = (await db.execute(
        select(MallProduct).where(MallProduct.id.in_(p_ids))
    )).scalars().all() if p_ids else []
    prod_map = {p.id: p for p in prods}
    product_rank = []
    for pid, qty, amount in prod_rank_rows:
        p = prod_map.get(pid)
        product_rank.append({
            "id": pid,
            "name": p.name if p else None,
            "main_image": p.main_image if p else None,
            "quantity": int(qty or 0),
            "amount": str(amount or 0),
        })

    # ── 低库存 5 个（只显示在售商品，下架的不参与告警）─────
    low_rows = (await db.execute(
        select(MallInventory, MallProductSku, MallProduct)
        .join(MallProductSku, MallInventory.sku_id == MallProductSku.id)
        .join(MallProduct, MallProductSku.product_id == MallProduct.id)
        .where(MallInventory.quantity <= 10)
        .where(MallProductSku.status == "active")
        .where(MallProduct.status == "on_sale")
        .order_by(MallInventory.quantity.asc())
        .limit(5)
    )).all()
    low_stock = [
        {
            "inventory_id": inv.id,
            "sku_id": sku.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "spec": sku.spec,
            "quantity": inv.quantity,
        }
        for inv, sku, prod in low_rows
    ]

    return {
        "today": {
            "orders": today_orders,
            "received": str(today_received),
            "new_users": today_new_users,
            "cancelled": today_cancelled,
        },
        "yesterday": {
            "orders": y_orders,
            "received": str(y_received),
        },
        "pending": {
            "pending_assignment": pending_assignment,
            "pending_payment_confirmation": pending_confirm,
            "open_skip_alerts": open_alerts,
            "low_stock_count": low_stock_count,
            "pending_applications": pending_applications,
            "pending_returns": pending_returns,
            "approved_returns_awaiting_refund": approved_returns_awaiting_refund,
        },
        "month": {
            "orders": m_orders,
            "received": str(m_received),
            "new_users": m_new_users,
        },
        "trend": trend,
        "salesman_rank": salesman_rank,
        "product_rank": product_rank,
        "low_stock": low_stock,
    }
