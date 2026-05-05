"""
Mall 退货申请服务。

核心流程：
  C 端发起（pending）
    → admin approve（退库存 + 订单→refunded + reverse 已入账 commission）
      → admin mark_refunded（记 refunded_at，资金流线下走完毕）
  或
    → admin reject（申请作废，订单/库存不动）

关键设计：
  - approved 时已做库存回退 + 订单 status=refunded。refunded 态是"资金结算完成"标记，
    并不需要再回改任何状态数据；只是让财务流程有据可查（什么时候真的把钱退给客户了）
  - 提成回写：已入账 commission 批量改为 REVERSED 状态（MallCommission 表），
    月结前会把它扣除（已实现：工资生成查 pending + settled 排除 reversed）
  - 利润台账：订单 status=refunded 后自动从 profit_service 聚合中排除（profit 查 completed/partial_closed）
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import (
    MallInventoryFlowType,
    MallOrderStatus,
    MallReturnStatus,
)
from app.models.mall.inventory import MallInventory, MallInventoryFlow
from app.models.mall.order import (
    MallOrder,
    MallOrderItem,
    MallReturnRequest,
)
from app.services.audit_service import log_audit


async def apply_return(
    db: AsyncSession,
    *,
    order: MallOrder,
    user_id: str,
    reason: str,
) -> MallReturnRequest:
    """C 端申请退货。只允许 completed / partial_closed 订单；同时只能有一条活跃申请。"""
    if order.user_id != user_id:
        raise HTTPException(status_code=403, detail="订单不属于当前用户")
    if order.status not in (
        MallOrderStatus.COMPLETED.value,
        MallOrderStatus.PARTIAL_CLOSED.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可申请退货（仅已完成/部分付款可退）",
        )

    # 活跃申请检查（DB 有 unique partial index 兜底，但先给友好提示）
    active = (await db.execute(
        select(MallReturnRequest)
        .where(MallReturnRequest.order_id == order.id)
        .where(MallReturnRequest.status.in_([
            MallReturnStatus.PENDING.value,
            MallReturnStatus.APPROVED.value,
        ]))
    )).scalar_one_or_none()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"该订单已有退货申请（status={active.status}），请等待处理结果",
        )

    req = MallReturnRequest(
        order_id=order.id,
        user_id=user_id,
        reason=reason,
        status=MallReturnStatus.PENDING.value,
    )
    db.add(req)
    await db.flush()

    await log_audit(
        db,
        action="mall_return.apply",
        entity_type="MallReturnRequest",
        entity_id=req.id,
        mall_user_id=user_id,
        actor_type="mall_user",
        changes={
            "order_no": order.order_no,
            "order_status": order.status,
            "received_amount": str(order.received_amount or 0),
            "reason": (reason or "")[:200],
        },
    )
    return req


async def approve_return(
    db: AsyncSession,
    *,
    req: MallReturnRequest,
    reviewer_employee_id: str,
    refund_amount: Optional[Decimal] = None,
    review_note: Optional[str] = None,
) -> MallReturnRequest:
    """财务批准退货：
      1. 按原订单 item.quantity 反向入库（按原出库 flow 定位仓）
      2. 订单 status → refunded
      3. 提成回写（pending commission 标 reversed，已 settled 的只记审计不追溯）
    """
    # 并发保护（G12）：同一 req 并发 approve 会分别建 adjustment Commission，造成双扣。
    # 先 FOR UPDATE 锁住申请行再做状态检查，确保只有一个事务能进入 approved 分支。
    locked_req = (await db.execute(
        select(MallReturnRequest)
        .where(MallReturnRequest.id == req.id)
        .with_for_update()
    )).scalar_one_or_none()
    if locked_req is None:
        raise HTTPException(status_code=404, detail="申请已不存在")
    if locked_req.status != MallReturnStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"申请状态 {locked_req.status} 不可审批",
        )
    req = locked_req  # 用锁定后的对象，避免用缓存的脏副本

    # 订单也一起锁，防止与 admin_cancel / partial_close 等并发路径打架
    order = (await db.execute(
        select(MallOrder)
        .where(MallOrder.id == req.order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 反向入库（按原出库流水的 inventory 定位目标仓）
    items = (await db.execute(
        select(MallOrderItem).where(MallOrderItem.order_id == order.id)
    )).scalars().all()
    flows = (await db.execute(
        select(MallInventoryFlow, MallInventory)
        .join(MallInventory, MallInventoryFlow.inventory_id == MallInventory.id)
        .where(MallInventoryFlow.ref_type == "order")
        .where(MallInventoryFlow.ref_id == order.id)
        .where(MallInventoryFlow.flow_type == MallInventoryFlowType.OUT.value)
    )).all()
    sku_to_inv = {inv.sku_id: inv for _, inv in flows}

    for it in items:
        inv = sku_to_inv.get(it.sku_id)
        if inv is None:
            raise HTTPException(
                status_code=500,
                detail=f"找不到 SKU {it.sku_id} 的原出库流水，无法退货",
            )
        # 直接回加库存（不改 avg_cost_price，退货按原单成本记录流水）
        inv.quantity = (inv.quantity or 0) + it.quantity
        db.add(MallInventoryFlow(
            inventory_id=inv.id,
            flow_type=MallInventoryFlowType.IN.value,
            quantity=it.quantity,
            cost_price=it.cost_price_snapshot,
            ref_type="return",
            ref_id=req.id,
            notes=f"退货入库 {order.order_no}（退货申请 {req.id[:8]}）",
        ))

    # 条码回 IN_STOCK（与 admin_cancel 一致的处理，否则出库条码永远挂着）
    from app.models.mall.base import MallInventoryBarcodeStatus
    from app.models.mall.inventory import MallInventoryBarcode
    bcs = (await db.execute(
        select(MallInventoryBarcode)
        .where(MallInventoryBarcode.outbound_order_id == order.id)
        .where(MallInventoryBarcode.status == MallInventoryBarcodeStatus.OUTBOUND.value)
    )).scalars().all()
    for b in bcs:
        b.status = MallInventoryBarcodeStatus.IN_STOCK.value
        b.outbound_order_id = None
        b.outbound_by_user_id = None
        b.outbound_at = None

    # 订单 → refunded
    # 记录退货前状态供 profit_service 使用：partial_closed 的单退货后
    # bad_debt 仍计入利润聚合（避免上月坏账报表"凭空减少"）
    order.refunded_from_status = order.status
    order.status = MallOrderStatus.REFUNDED.value

    # 决策 #4 商品销量双数据：退货时扣 net_sales（total_sales 保留历史）
    from app.models.mall.product import MallProduct
    qty_by_product: dict[int, int] = {}
    for it in items:
        qty_by_product[it.product_id] = qty_by_product.get(it.product_id, 0) + it.quantity
    for pid, qty in qty_by_product.items():
        prod = await db.get(MallProduct, pid)
        if prod is not None:
            prod.net_sales = max(0, (prod.net_sales or 0) - qty)

    # 提成回写（决策 #1）：
    # - pending → reversed（本月还没发工资，直接抹掉）
    # - settled → 建负数 Commission(is_adjustment=True, status=pending)
    #   下月工资单扫入扣回；工资不够扣时走 salary_adjustments_pending 挂账
    import uuid as _uuid
    from app.models.user import Commission
    commissions = (await db.execute(
        select(Commission)
        .where(Commission.mall_order_id == order.id)
        .where(Commission.is_adjustment.is_(False))  # 不处理已经是 adjustment 的
    )).scalars().all()
    reversed_count = 0
    adjustment_count = 0
    reason_tag = (req.reason or "")[:80]
    for c in commissions:
        if c.status == "pending":
            c.status = "reversed"
            c.notes = ((c.notes or "") + f"\n[退货回写] reason={reason_tag}").strip()
            reversed_count += 1
        elif c.status == "settled":
            # 已 settled：工资已发出，建负数追回 commission 挂到下月工资单
            # 幂等：查是否已有针对此 Commission 的 adjustment（防重复退货 approve）
            existing_adj = (await db.execute(
                select(Commission)
                .where(Commission.adjustment_source_commission_id == c.id)
            )).scalar_one_or_none()
            if existing_adj is None:
                adj = Commission(
                    id=str(_uuid.uuid4()),
                    employee_id=c.employee_id,
                    brand_id=c.brand_id,
                    mall_order_id=c.mall_order_id,
                    order_id=None,
                    store_sale_id=None,
                    commission_amount=-c.commission_amount,
                    is_adjustment=True,
                    adjustment_source_commission_id=c.id,
                    status="pending",
                    notes=f"[跨月退货追回] 原 commission {c.id[:8]} ¥{c.commission_amount} · reason={reason_tag}",
                )
                db.add(adj)
                adjustment_count += 1
                # 原 Commission 不动 status；仅加 notes 审计
                c.notes = ((c.notes or "") + f"\n[跨月退货已建追回 adj] {reason_tag}").strip()
    # 退货后 order.commission_posted 不改（保持历史痕迹），profit_service 查 refunded 不纳入聚合

    req.status = MallReturnStatus.APPROVED.value
    req.reviewer_employee_id = reviewer_employee_id
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_note = review_note
    # refund_amount 默认取订单已收金额（financial 可在 mark_refunded 时调整）
    req.refund_amount = refund_amount if refund_amount is not None else (order.received_amount or Decimal("0"))

    await db.flush()

    await log_audit(
        db,
        action="mall_return.approve",
        entity_type="MallReturnRequest",
        entity_id=req.id,
        actor_id=reviewer_employee_id,
        changes={
            "order_no": order.order_no,
            "refund_amount": str(req.refund_amount),
            "commissions_reversed": reversed_count,
            "commissions_adjustment_built": adjustment_count,
            "review_note": (review_note or "")[:200],
        },
    )
    return req


async def reject_return(
    db: AsyncSession,
    *,
    req: MallReturnRequest,
    reviewer_employee_id: str,
    review_note: str,
) -> MallReturnRequest:
    """财务驳回退货：不动订单/库存，只改申请状态。"""
    if req.status != MallReturnStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"申请状态 {req.status} 不可驳回",
        )
    req.status = MallReturnStatus.REJECTED.value
    req.reviewer_employee_id = reviewer_employee_id
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_note = review_note
    await db.flush()

    await log_audit(
        db,
        action="mall_return.reject",
        entity_type="MallReturnRequest",
        entity_id=req.id,
        actor_id=reviewer_employee_id,
        changes={
            "order_id": req.order_id,
            "review_note": (review_note or "")[:200],
        },
    )
    return req


async def mark_refunded(
    db: AsyncSession,
    *,
    req: MallReturnRequest,
    refund_method: str,
    refund_note: Optional[str] = None,
    refund_amount: Optional[Decimal] = None,
) -> MallReturnRequest:
    """财务在线下完成退款后确认。"""
    if req.status != MallReturnStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"申请状态 {req.status} 不可标记已退款（仅 approved 可进入 refunded）",
        )
    old_refund_amount = req.refund_amount
    req.status = MallReturnStatus.REFUNDED.value
    req.refunded_at = datetime.now(timezone.utc)
    req.refund_method = refund_method
    if refund_note:
        req.refund_note = refund_note
    if refund_amount is not None:
        req.refund_amount = refund_amount
    await db.flush()

    # 需要 reviewer_employee_id 做 actor，但这里没传进来；mark_refunded 通常由 finance 触发，
    # 路由层会在端点里附加 log_audit；service 层这条作"数据变化"兜底留痕
    changes = {
        "order_id": req.order_id,
        "refund_method": refund_method,
        "refund_amount": str(req.refund_amount),
    }
    if refund_amount is not None and refund_amount != old_refund_amount:
        # G10：金额变更单独留痕
        changes["refund_amount_adjusted"] = {
            "from": str(old_refund_amount),
            "to": str(refund_amount),
        }
    await log_audit(
        db,
        action="mall_return.mark_refunded",
        entity_type="MallReturnRequest",
        entity_id=req.id,
        changes=changes,
    )
    return req
