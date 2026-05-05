"""
/api/mall/admin/dashboard/*

商城运营看板。聚合端点一次返回所有卡片数据，减少前端并发请求。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
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

    # ── G9：本月利润/毛利率（聚合 profit_service）─────────
    from app.services.mall.profit_service import aggregate_mall_profit
    m_profit_data = await aggregate_mall_profit(
        db, date_from=month_start,
    )
    # 今日利润（按今日窗口单独算，口径一致）
    t_profit_data = await aggregate_mall_profit(
        db, date_from=t_start, date_to=t_end,
    )

    def _gross_margin(rev: Decimal, cost: Decimal, bad_debt: Decimal) -> Optional[str]:
        """毛利率 = (revenue - cost - bad_debt) / revenue。0 收入返 None。"""
        if rev <= 0:
            return None
        gm = (rev - cost - bad_debt) / rev * 100
        return f"{gm:.1f}"

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
            # 禁用业务员仍在榜（历史单还算 GMV），前端标灰色让老板不困惑
            "is_disabled": bool(s and s.status != "active") if s else False,
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

    t_rev = Decimal(t_profit_data["total_revenue"])
    t_cost = Decimal(t_profit_data["total_cost"])
    t_bd = Decimal(t_profit_data["total_bad_debt"])
    m_rev = Decimal(m_profit_data["total_revenue"])
    m_cost = Decimal(m_profit_data["total_cost"])
    m_bd = Decimal(m_profit_data["total_bad_debt"])

    return {
        "today": {
            "orders": today_orders,
            "received": str(today_received),
            "new_users": today_new_users,
            "cancelled": today_cancelled,
            # G9 profit cards
            "revenue": t_profit_data["total_revenue"],
            "profit": t_profit_data["total_profit"],
            "commission": t_profit_data["total_commission"],
            "gross_margin_pct": _gross_margin(t_rev, t_cost, t_bd),
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
            # G9 profit cards
            "revenue": m_profit_data["total_revenue"],
            "profit": m_profit_data["total_profit"],
            "commission": m_profit_data["total_commission"],
            "bad_debt": m_profit_data["total_bad_debt"],
            "gross_margin_pct": _gross_margin(m_rev, m_cost, m_bd),
        },
        "trend": trend,
        "salesman_rank": salesman_rank,
        "product_rank": product_rank,
        "low_stock": low_stock,
    }


# =============================================================================
# 决策 #2：月度业务员排行（快照 vs 实时双模式）
# =============================================================================


@router.get("/salesman-ranking")
async def salesman_ranking(
    user: CurrentUser,
    year_month: str,  # "YYYY-MM"
    mode: str = "realtime",  # snapshot | realtime
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """业务员月度排行榜。

    mode=realtime：实时聚合 mall_orders（completed/partial_closed 纳入，refunded 排除）。
                   下月客户退货会导致数字变动，适合"当前真实口径"。
    mode=snapshot：查 mall_monthly_kpi_snapshot 冻结数据，月初 1 号定格不受后续退货影响。
                   适合"发奖金后核对"的场景。

    排行按 gmv desc。
    """
    require_role(user, "admin", "boss", "finance")

    try:
        y_str, m_str = year_month.split("-")
        y, m = int(y_str), int(m_str)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="year_month 格式应为 YYYY-MM")

    month_start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        month_end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(y, m + 1, 1, tzinfo=timezone.utc)

    if mode == "snapshot":
        from app.models.mall.kpi_snapshot import MallMonthlyKpiSnapshot
        from app.models.user import Employee
        snap_rows = (await db.execute(
            select(MallMonthlyKpiSnapshot)
            .where(MallMonthlyKpiSnapshot.period == year_month)
            .order_by(desc(MallMonthlyKpiSnapshot.gmv))
            .limit(limit)
        )).scalars().all()
        emp_ids = [r.employee_id for r in snap_rows]
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars().all() if emp_ids else []
        emp_map = {e.id: e for e in emps}

        # 同时取 MallUser (nickname) 方便前端展示 —— linked_employee_id 回查
        sms = (await db.execute(
            select(MallUser).where(MallUser.linked_employee_id.in_(emp_ids))
        )).scalars().all() if emp_ids else []
        sm_by_emp = {s.linked_employee_id: s for s in sms}

        return {
            "mode": "snapshot",
            "period": year_month,
            "records": [
                {
                    "employee_id": r.employee_id,
                    "employee_name": emp_map[r.employee_id].name if r.employee_id in emp_map else None,
                    "nickname": sm_by_emp[r.employee_id].nickname if r.employee_id in sm_by_emp else None,
                    "gmv": str(r.gmv),
                    "order_count": r.order_count,
                    "commission_amount": str(r.commission_amount),
                    "snapshot_at": r.snapshot_at,
                }
                for r in snap_rows
            ],
            "is_frozen": True,
            "snapshot_count": len(snap_rows),
        }

    # realtime 模式
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
                MallOrder.completed_at < month_end,
            ),
            and_(
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                MallOrder.delivered_at >= month_start,
                MallOrder.delivered_at < month_end,
            ),
        ))
        .group_by(MallOrder.assigned_salesman_id)
        .order_by(desc("gmv"))
        .limit(limit)
    )).all()

    sm_ids = [r[0] for r in rank_rows]
    sms = (await db.execute(
        select(MallUser).where(MallUser.id.in_(sm_ids))
    )).scalars().all() if sm_ids else []
    sm_map = {s.id: s for s in sms}

    return {
        "mode": "realtime",
        "period": year_month,
        "records": [
            {
                "salesman_id": sm_id,
                "employee_id": sm_map[sm_id].linked_employee_id if sm_id in sm_map else None,
                "nickname": sm_map[sm_id].nickname if sm_id in sm_map else None,
                # 禁用业务员仍算进榜（本月历史单 GMV 保留），前端标灰
                "is_disabled": (
                    sm_id in sm_map and sm_map[sm_id].status != "active"
                ),
                "gmv": str(gmv or 0),
                "order_count": cnt,
            }
            for sm_id, cnt, gmv in rank_rows
        ],
        "is_frozen": False,
    }


@router.post("/salesman-ranking/build-snapshot")
async def build_snapshot_admin(
    user: CurrentUser,
    year_month: str,
    db: AsyncSession = Depends(get_db),
):
    """手工回补某月快照（admin/boss）。同月重跑会 UPSERT。"""
    require_role(user, "admin", "boss")
    try:
        y_str, m_str = year_month.split("-")
        y, m = int(y_str), int(m_str)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="year_month 格式应为 YYYY-MM")

    from app.services.mall import kpi_snapshot_service as kss
    result = await kss.build_snapshot_for_month(
        db, y, m,
        notes=f"手工回补 by {user.get('name') or user.get('id')}",
    )
    return result


@router.post("/salesman-ranking/build-snapshot-range")
async def build_snapshot_range_admin(
    user: CurrentUser,
    from_month: str,  # "YYYY-MM"
    to_month: str,  # inclusive
    db: AsyncSession = Depends(get_db),
):
    """批量回补某段月份快照（admin/boss）。仅系统上线初期补历史数据用。

    示例：from_month=2025-06, to_month=2026-04 → 逐月 UPSERT 共 11 条 period 的快照。
    """
    require_role(user, "admin", "boss")
    try:
        fy_s, fm_s = from_month.split("-")
        ty_s, tm_s = to_month.split("-")
        fy, fm = int(fy_s), int(fm_s)
        ty, tm = int(ty_s), int(tm_s)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="month 格式应为 YYYY-MM")

    if (fy, fm) > (ty, tm):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="from_month 必须早于 to_month")

    from app.services.mall import kpi_snapshot_service as kss
    results = []
    y, m = fy, fm
    while (y, m) <= (ty, tm):
        r = await kss.build_snapshot_for_month(
            db, y, m,
            notes=f"批量回补 by {user.get('name') or user.get('id')}",
        )
        results.append(r)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    await db.flush()
    return {
        "ok": True,
        "from_month": from_month,
        "to_month": to_month,
        "months_processed": len(results),
        "total_upserted": sum(r["upserted"] for r in results),
        "details": results,
    }
