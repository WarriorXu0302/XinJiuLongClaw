"""
/api/mall/workspace/sales-targets/my-dashboard

业务员看板：本月销售目标 + 实际完成率（按 mall 订单口径）。

计算口径（mall 业务员独立计算，不碰 ERP Order 表）：
  - actual_sales：assigned_salesman_id=自己 且 status NOT IN (cancelled) 的订单 pay_amount 之和
  - actual_receipt：同上订单的 received_amount 之和（财务已确认的收款累加）
  - 按 brand 聚合时走 mall_order_items.brand_id
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.base import MallOrderStatus
from app.models.mall.order import MallOrder, MallOrderItem
from app.models.sales_target import SalesTarget
from app.services.mall import auth_service

router = APIRouter()


async def _calc_mall_actual(
    db: AsyncSession, salesman_id: str, year: int, month: Optional[int],
    brand_id: Optional[str],
) -> tuple[Decimal, Decimal]:
    """按 mall_orders 聚合某业务员在指定年月 + 品牌的实际销售/回款。"""
    # 基础条件：排除 cancelled / refunded（二者都不代表有效销售）
    conds = [
        MallOrder.assigned_salesman_id == salesman_id,
        MallOrder.status.notin_([
            MallOrderStatus.CANCELLED.value,
            MallOrderStatus.REFUNDED.value,
        ]),
        extract("year", MallOrder.created_at) == year,
    ]
    if month:
        conds.append(extract("month", MallOrder.created_at) == month)

    if brand_id:
        # 按品牌聚合 → 需 join order_items（订单多品牌合单的场景，按 item.subtotal 占比累加）
        # 简化：只要订单包含该品牌 item 就把该 item 的 subtotal 计入销售、按比例分配回款
        item_sum_stmt = (
            select(
                func.coalesce(func.sum(MallOrderItem.subtotal), 0).label("brand_subtotal"),
                func.coalesce(func.sum(MallOrder.pay_amount), 0).label("order_total_pay"),
                func.coalesce(func.sum(MallOrder.received_amount), 0).label("order_total_recv"),
            )
            .select_from(MallOrder)
            .join(MallOrderItem, MallOrderItem.order_id == MallOrder.id)
            .where(and_(*conds, MallOrderItem.brand_id == brand_id))
        )
        # 简化：销售=brand 的 item.subtotal；回款=brand_subtotal / order.pay_amount * order.received
        # 实际上同一订单多品牌场景罕见（mall C 端加购多为同品牌）；先用 subtotal 近似销售
        # 回款按比例分配需要 per-order 聚合，这里仅做 brand_subtotal 作销售；回款退化到整单（若订单只含该 brand）
        # —— 以下实现取简单路径：同一业务员 + brand + 月份的订单 item subtotal 合计作 sales
        row = (await db.execute(item_sum_stmt)).one()
        sales = Decimal(str(row.brand_subtotal or 0))
        # 回款：该品牌占订单额比例 × 订单实收（防虚算）
        if row.order_total_pay and Decimal(str(row.order_total_pay)) > 0:
            ratio = sales / Decimal(str(row.order_total_pay))
            receipt = Decimal(str(row.order_total_recv or 0)) * ratio
        else:
            receipt = Decimal("0")
        return sales, receipt.quantize(Decimal("0.01"))

    # 不指定 brand：直接聚合订单
    row = (await db.execute(
        select(
            func.coalesce(func.sum(MallOrder.pay_amount), 0),
            func.coalesce(func.sum(MallOrder.received_amount), 0),
        ).where(and_(*conds))
    )).one()
    return Decimal(str(row[0] or 0)), Decimal(str(row[1] or 0))


@router.get("/my-dashboard")
async def my_dashboard(
    current: CurrentMallUser,
    target_year: Optional[int] = Query(default=None),
    target_month: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        return []

    if not target_year:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        target_year = now.year
        target_month = target_month or now.month

    stmt = select(SalesTarget).where(
        SalesTarget.target_level == "employee",
        SalesTarget.employee_id == user.linked_employee_id,
        SalesTarget.target_year == target_year,
        SalesTarget.status == "approved",
    )
    if target_month is not None:
        stmt = stmt.where(SalesTarget.target_month == target_month)
    rows = (await db.execute(stmt)).scalars().all()

    results = []
    for r in rows:
        actual_sales, actual_receipt = await _calc_mall_actual(
            db, user.id, r.target_year, r.target_month, r.brand_id,
        )
        sales_tgt = Decimal(str(r.sales_target or 0))
        recv_tgt = Decimal(str(r.receipt_target or 0))
        sales_comp = float(actual_sales / sales_tgt) if sales_tgt > 0 else 0.0
        recv_comp = float(actual_receipt / recv_tgt) if recv_tgt > 0 else 0.0
        results.append({
            "id": r.id,
            "target_year": r.target_year,
            "target_month": r.target_month,
            "brand_id": r.brand_id,
            "sales_target": float(sales_tgt),
            "receipt_target": float(recv_tgt),
            "actual_sales": float(actual_sales),
            "actual_receipt": float(actual_receipt),
            "sales_completion": sales_comp,
            "receipt_completion": recv_comp,
            "status": r.status,
        })
    return results
