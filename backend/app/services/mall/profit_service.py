"""
Mall 利润聚合服务。

设计决策：
  - **不建 profit_ledger 表**（ERP 本身也不存，是实时查聚合）
  - 订单 completed / partial_closed 时 order_service 会标 profit_ledger_posted=True 作为"进入报表"标志
  - 真正给老板看利润时调本服务的 aggregate_mall_profit()
  - 按 brand_id 分账（order_item 下单时固化的 brand_id）

利润公式：
  毛利 = 收入(按 item 切分 received_amount) − 成本(cost_price_snapshot × qty) − 提成
  - 收入切分：一笔订单可能跨品牌，按 item.subtotal / sum(item.subtotal) 的比例切分 received_amount 到各 brand
  - 成本：下单瞬间固化的 cost_price_snapshot（避免后期成本变更影响历史利润）
  - 提成：Commission 表已按 brand_id 写入，直接 sum

bad_debt 科目：
  - partial_closed 订单的 pay_amount - received_amount = 坏账金额
  - 按 item.subtotal 比例切分到 brand
  - 利润公式里作为额外扣项：profit = revenue - cost - commission - bad_debt

不计：
  - 运费（M3 商城无运费）
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import MallOrderStatus
from app.models.mall.order import MallOrder, MallOrderItem
from app.models.user import Commission


async def aggregate_mall_profit(
    db: AsyncSession,
    *,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    brand_id: Optional[str] = None,
) -> dict:
    """聚合 mall 销售利润。

    按时间窗口（基于 order.completed_at）+ 可选 brand_id 过滤。
    返回：
      {
        total_revenue: str,         # 按 item 切分后的收入合计
        total_cost: str,            # cost_price_snapshot × qty 合计
        total_commission: str,      # mall 订单关联的 commission
        total_profit: str,          # revenue - cost - commission
        by_brand: [                 # 分品牌细分（若无 brand_id 筛选则展示所有）
          {brand_id, revenue, cost, commission, profit, order_count}
        ],
      }

    幂等性：纯聚合查询，调多次结果一致。
    """
    # 纳入利润聚合的订单三类：
    #   1. completed
    #   2. partial_closed（坏账也计入，扣在净利润里）
    #   3. **refunded 且退货前是 partial_closed**（P1-6 修复）
    #      partial_closed 订单的坏账已在当月利润报表扣过，下月退货不应让
    #      上月的坏账"凭空消失"，保持财务报表月度稳定
    # 时间窗口口径：
    #   - completed：按 completed_at（全款到账时刻）
    #   - partial_closed：按 delivered_at（completed_at 故意留空）
    #   - refunded(from partial_closed)：按 delivered_at（和 partial_closed 对齐）
    from sqlalchemy import and_, or_
    order_stmt = (
        select(
            MallOrder.id.label("oid"),
            MallOrder.received_amount.label("recv"),
            MallOrder.pay_amount.label("pay"),
            MallOrder.status.label("st"),
            MallOrder.refunded_from_status.label("rfs"),
            MallOrder.completed_at,
        )
        .where(
            or_(
                MallOrder.status == MallOrderStatus.COMPLETED.value,
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                and_(
                    MallOrder.status == MallOrderStatus.REFUNDED.value,
                    MallOrder.refunded_from_status == MallOrderStatus.PARTIAL_CLOSED.value,
                ),
            )
        )
    )
    if date_from or date_to:
        completed_conds = [MallOrder.status == MallOrderStatus.COMPLETED.value]
        partial_conds = [MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value]
        refunded_partial_conds = [
            MallOrder.status == MallOrderStatus.REFUNDED.value,
            MallOrder.refunded_from_status == MallOrderStatus.PARTIAL_CLOSED.value,
        ]
        if date_from:
            completed_conds.append(MallOrder.completed_at >= date_from)
            partial_conds.append(MallOrder.delivered_at >= date_from)
            refunded_partial_conds.append(MallOrder.delivered_at >= date_from)
        if date_to:
            completed_conds.append(MallOrder.completed_at < date_to)
            partial_conds.append(MallOrder.delivered_at < date_to)
            refunded_partial_conds.append(MallOrder.delivered_at < date_to)
        order_stmt = order_stmt.where(or_(
            and_(*completed_conds),
            and_(*partial_conds),
            and_(*refunded_partial_conds),
        ))
    order_rows = (await db.execute(order_stmt)).all()
    if not order_rows:
        return {
            "total_revenue": "0",
            "total_cost": "0",
            "total_commission": "0",
            "total_bad_debt": "0",
            "total_profit": "0",
            "by_brand": [],
        }

    order_ids = [r[0] for r in order_rows]
    recv_map = {r[0]: Decimal(str(r[1] or 0)) for r in order_rows}
    # 坏账 = pay_amount - received_amount
    # 计入 bad_debt 的两种：
    #   - status=partial_closed（原路径）
    #   - status=refunded 且 refunded_from_status=partial_closed（P1-6 修）
    # completed 订单全款到账，bad_debt=0
    bad_debt_map: dict[str, Decimal] = {}
    for oid, recv, pay, st, rfs, _ct in order_rows:
        has_bad_debt = (
            st == MallOrderStatus.PARTIAL_CLOSED.value
            or (st == MallOrderStatus.REFUNDED.value and rfs == MallOrderStatus.PARTIAL_CLOSED.value)
        )
        if has_bad_debt:
            bd = Decimal(str(pay or 0)) - Decimal(str(recv or 0))
            bad_debt_map[oid] = bd if bd > 0 else Decimal("0")
        else:
            bad_debt_map[oid] = Decimal("0")

    # ── 取所有 items（按 order + brand 分组）──────────────────
    item_stmt = select(
        MallOrderItem.order_id,
        MallOrderItem.brand_id,
        sa_func.sum(MallOrderItem.subtotal).label("item_subtotal"),
        sa_func.sum(
            MallOrderItem.cost_price_snapshot * MallOrderItem.quantity
        ).label("item_cost"),
        sa_func.sum(MallOrderItem.quantity).label("qty"),
    ).where(MallOrderItem.order_id.in_(order_ids))
    if brand_id:
        item_stmt = item_stmt.where(MallOrderItem.brand_id == brand_id)
    item_stmt = item_stmt.group_by(MallOrderItem.order_id, MallOrderItem.brand_id)
    item_rows = (await db.execute(item_stmt)).all()

    # ── 订单内 brand 收入切分 ──────────────────────────────────
    # order_subtotal_by_order: 订单总 subtotal（用于算比例）
    order_total_stmt = select(
        MallOrderItem.order_id,
        sa_func.sum(MallOrderItem.subtotal).label("order_total"),
    ).where(MallOrderItem.order_id.in_(order_ids)).group_by(MallOrderItem.order_id)
    order_total_rows = (await db.execute(order_total_stmt)).all()
    order_total_map = {r[0]: Decimal(str(r[1] or 0)) for r in order_total_rows}

    # 聚合到 brand
    brand_agg: dict[Optional[str], dict] = {}
    for oid, bid, item_sub, item_cost, qty in item_rows:
        item_sub_d = Decimal(str(item_sub or 0))
        item_cost_d = Decimal(str(item_cost or 0))
        order_total = order_total_map.get(oid, Decimal("0"))
        recv = recv_map.get(oid, Decimal("0"))
        bad_debt_total = bad_debt_map.get(oid, Decimal("0"))

        # 该 brand 在该订单里的占比 = item_sub / order_total
        if order_total > 0:
            ratio = item_sub_d / order_total
            brand_revenue = (recv * ratio).quantize(Decimal("0.01"))
            brand_bad_debt = (bad_debt_total * ratio).quantize(Decimal("0.01"))
        else:
            brand_revenue = Decimal("0")
            brand_bad_debt = Decimal("0")

        agg = brand_agg.setdefault(bid, {
            "brand_id": bid,
            "revenue": Decimal("0"),
            "cost": Decimal("0"),
            "commission": Decimal("0"),
            "bad_debt": Decimal("0"),
            "qty": 0,
            "order_ids": set(),
        })
        agg["revenue"] += brand_revenue
        agg["cost"] += item_cost_d
        agg["bad_debt"] += brand_bad_debt
        agg["qty"] += int(qty or 0)
        agg["order_ids"].add(oid)

    # ── 提成（按 brand_id 累加）─────────────────────────────
    com_stmt = select(
        Commission.brand_id,
        sa_func.coalesce(sa_func.sum(Commission.commission_amount), 0),
    ).where(Commission.mall_order_id.in_(order_ids))
    if brand_id:
        com_stmt = com_stmt.where(Commission.brand_id == brand_id)
    com_stmt = com_stmt.group_by(Commission.brand_id)
    com_rows = (await db.execute(com_stmt)).all()
    for bid, total in com_rows:
        agg = brand_agg.setdefault(bid, {
            "brand_id": bid,
            "revenue": Decimal("0"),
            "cost": Decimal("0"),
            "commission": Decimal("0"),
            "bad_debt": Decimal("0"),
            "qty": 0,
            "order_ids": set(),
        })
        agg["commission"] += Decimal(str(total or 0))

    # ── 汇总 ───────────────────────────────────────────────
    by_brand = []
    total_rev = total_cost = total_com = total_bd = Decimal("0")
    for bid, agg in brand_agg.items():
        profit = agg["revenue"] - agg["cost"] - agg["commission"] - agg["bad_debt"]
        by_brand.append({
            "brand_id": bid,
            "revenue": str(agg["revenue"]),
            "cost": str(agg["cost"]),
            "commission": str(agg["commission"]),
            "bad_debt": str(agg["bad_debt"]),
            "profit": str(profit),
            "qty": agg["qty"],
            "order_count": len(agg["order_ids"]),
        })
        total_rev += agg["revenue"]
        total_cost += agg["cost"]
        total_com += agg["commission"]
        total_bd += agg["bad_debt"]

    # 按利润降序
    by_brand.sort(key=lambda x: Decimal(x["profit"]), reverse=True)

    return {
        "total_revenue": str(total_rev),
        "total_cost": str(total_cost),
        "total_commission": str(total_com),
        "total_bad_debt": str(total_bd),
        "total_profit": str(total_rev - total_cost - total_com - total_bd),
        "by_brand": by_brand,
    }
