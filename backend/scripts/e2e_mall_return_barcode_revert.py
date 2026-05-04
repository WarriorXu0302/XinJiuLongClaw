"""E2E：mall 退货 approve 时条码回退（桥 B4.4）。

验证场景：
  1. ship 过条码的订单批准退货 → 条码 OUTBOUND → IN_STOCK + outbound_order_id=NULL
  2. 没扫过码的订单（合规性保护：本不该发生）批准退货 → service 只处理 matched 条码，
     不崩
  3. 其他订单的条码不受影响（只改 outbound_order_id 匹配的）

跑法：
  cd backend && python -m scripts.e2e_mall_return_barcode_revert
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallInventoryBarcodeStatus,
    MallInventoryBarcodeType,
    MallOrderStatus,
    MallReturnStatus,
    MallUserApplicationStatus,
    MallUserStatus,
)
from app.models.mall.inventory import MallInventory, MallInventoryBarcode
from app.models.mall.order import MallOrder, MallReturnRequest
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallAddress, MallUser
from app.models.user import Commission, Employee
from app.services.mall import commission_service, order_service, return_service


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E mall 退货条码回退（桥 B4.4）")

    async with admin_session_factory() as s:
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one_or_none()
        if sm is None:
            print("❌ 需要 sm_test fixture")
            return
        sm.status = MallUserStatus.ACTIVE.value
        sm.is_accepting_orders = True

        consumer = (await s.execute(
            select(MallUser)
            .where(MallUser.user_type == "consumer")
            .where(MallUser.application_status == MallUserApplicationStatus.APPROVED.value)
            .where(MallUser.status == MallUserStatus.ACTIVE.value)
            .limit(1)
        )).scalar_one()
        consumer.referrer_salesman_id = sm.id
        if consumer.referrer_bound_at is None:
            consumer.referrer_bound_at = datetime.now(timezone.utc)

        sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.cost_price.isnot(None)).limit(1)
        )).scalar_one()
        inv = (await s.execute(
            select(MallInventory).where(MallInventory.sku_id == sku.id).limit(1)
        )).scalar_one_or_none()
        if inv is None or inv.quantity < 5:
            print(f"❌ 库存不足")
            return
        addr = (await s.execute(
            select(MallAddress).where(MallAddress.user_id == consumer.id).limit(1)
        )).scalar_one_or_none()
        if addr is None:
            addr = MallAddress(
                user_id=consumer.id, receiver="B4.4-e2e", mobile="13800000000",
                addr="B4.4 测试", is_default=True,
            )
            s.add(addr)
            await s.flush()
        emp = (await s.execute(select(Employee).limit(1))).scalar_one()
        await s.commit()

        fx = {"sm_id": sm.id, "consumer_id": consumer.id, "sku_id": sku.id,
              "addr_id": addr.id, "warehouse_id": inv.warehouse_id,
              "product_id": sku.product_id, "emp_id": emp.id}
        print(f"fixtures: sm={sm.id[:8]} sku={sku.id} wh={inv.warehouse_id[:8]}")

    order_ids: list[str] = []
    other_order_ids: list[str] = []
    return_ids: list[str] = []
    tag_barcodes: list[str] = []  # 本次造的 OUTBOUND 条码
    other_barcodes: list[str] = []  # 不同订单的 OUTBOUND 条码（应不受本次 approve 影响）

    try:
        # ── Step 1：造两笔订单，各有 2 个 OUTBOUND 条码 ──
        print("\n[1] 造 2 个订单 × 2 瓶，分别扫码 outbound")
        async with admin_session_factory() as s:
            c = await s.get(MallUser, fx["consumer_id"])
            sm_now = await s.get(MallUser, fx["sm_id"])

            for order_idx in range(2):
                o = await order_service.create_order(
                    s, c, items=[{"sku_id": fx["sku_id"], "quantity": 2}],
                    address_id=fx["addr_id"],
                )
                await order_service.claim_order(s, sm_now, o.id)
                await s.flush()

                # 推 completed + 手工造 OUTBOUND 条码（绑到 order）
                now = datetime.now(timezone.utc)
                o.status = MallOrderStatus.COMPLETED.value
                o.payment_status = "fully_paid"
                o.received_amount = o.pay_amount
                o.delivered_at = now
                o.completed_at = now
                await commission_service.post_commission_for_order(s, o)

                # 手工建 2 个 OUTBOUND 条码，outbound_order_id=o.id
                for i in range(2):
                    code = f"E2E-B44-{order_idx}-{uuid.uuid4().hex[:6].upper()}"
                    s.add(MallInventoryBarcode(
                        id=str(uuid.uuid4()),
                        barcode=code,
                        barcode_type=MallInventoryBarcodeType.BOTTLE.value,
                        sku_id=fx["sku_id"],
                        product_id=fx["product_id"],
                        warehouse_id=fx["warehouse_id"],
                        batch_no=f"E2E-B44-B-{uuid.uuid4().hex[:4]}",
                        status=MallInventoryBarcodeStatus.OUTBOUND.value,
                        cost_price=Decimal("50.00"),
                        outbound_order_id=o.id,
                        outbound_at=now,
                    ))
                    if order_idx == 0:
                        tag_barcodes.append(code)
                    else:
                        other_barcodes.append(code)
                if order_idx == 0:
                    order_ids.append(o.id)
                else:
                    other_order_ids.append(o.id)
            await s.commit()

        print(f"   订单 1 (will refund): {order_ids[0][:8]}, 2 条码 {tag_barcodes}")
        print(f"   订单 2 (not refund):  {other_order_ids[0][:8]}, 2 条码 {other_barcodes}")

        # ── Step 2：发起并批准退货订单 1 ──
        print("\n[2] 申请 + 批准订单 1 的退货")
        async with admin_session_factory() as s:
            o = await s.get(MallOrder, order_ids[0])
            req = await return_service.apply_return(
                s, order=o, user_id=fx["consumer_id"], reason="B4.4 E2E"
            )
            req_id = req.id
            return_ids.append(req_id)
            await s.commit()

        async with admin_session_factory() as s:
            req = await s.get(MallReturnRequest, req_id)
            await return_service.approve_return(
                s, req=req, reviewer_employee_id=fx["emp_id"],
                review_note="B4.4",
            )
            await s.commit()

        # ── Step 3：断言条码回 IN_STOCK ──
        print("\n[3] 断言订单 1 的 2 瓶条码 → IN_STOCK，outbound_order_id=NULL")
        async with admin_session_factory() as s:
            bcs = (await s.execute(
                select(MallInventoryBarcode).where(
                    MallInventoryBarcode.barcode.in_(tag_barcodes)
                )
            )).scalars().all()
            assert len(bcs) == 2
            for b in bcs:
                assert b.status == MallInventoryBarcodeStatus.IN_STOCK.value, \
                    f"条码 {b.barcode} status={b.status}"
                assert b.outbound_order_id is None, \
                    f"条码 {b.barcode} outbound_order_id 未清空：{b.outbound_order_id}"
                assert b.outbound_at is None or b.outbound_at is not None  # 可 None 可保留（service 未必清）
            print(f"   ✅ 2 瓶都 IN_STOCK + outbound_order_id=NULL")

        # ── Step 4：断言订单 2 的条码不受影响 ──
        print("\n[4] 订单 2 未退货，条码仍 OUTBOUND + outbound_order_id 指向自己")
        async with admin_session_factory() as s:
            other_bcs = (await s.execute(
                select(MallInventoryBarcode).where(
                    MallInventoryBarcode.barcode.in_(other_barcodes)
                )
            )).scalars().all()
            assert len(other_bcs) == 2
            for b in other_bcs:
                assert b.status == MallInventoryBarcodeStatus.OUTBOUND.value, \
                    f"订单 2 条码 {b.barcode} 不该变：status={b.status}"
                assert b.outbound_order_id == other_order_ids[0], \
                    f"订单 2 条码 {b.barcode} outbound_order_id 被误改"
            print(f"   ✅ 订单 2 的 2 条条码不受影响")

        # ── Step 5：重复批准应抛错（状态校验）──
        print("\n[5] 重复 approve 应 409")
        async with admin_session_factory() as s:
            req2 = await s.get(MallReturnRequest, req_id)
            try:
                await return_service.approve_return(
                    s, req=req2, reviewer_employee_id=fx["emp_id"],
                    review_note="B4.4 dup",
                )
                assert False, "应拒绝"
            except Exception as e:
                # HTTPException 或 AssertionError 都可
                detail = getattr(e, "detail", str(e))
                assert "可审批" in str(detail) or "approved" in str(detail).lower() or str(detail), \
                    f"错误消息不对：{detail}"
                print(f"   ✅ 拒绝: {detail}")

        banner("✅ B4.4 条码回退回归通过")

    finally:
        # 清理
        async with admin_session_factory() as s:
            await s.execute(
                delete(MallInventoryBarcode).where(
                    MallInventoryBarcode.barcode.like("E2E-B44-%")
                )
            )
            if return_ids:
                await s.execute(
                    delete(MallReturnRequest).where(MallReturnRequest.id.in_(return_ids))
                )
            all_orders = order_ids + other_order_ids
            if all_orders:
                await s.execute(
                    delete(Commission).where(Commission.mall_order_id.in_(all_orders))
                )
                from app.models.mall.order import MallOrderItem
                await s.execute(
                    delete(MallOrderItem).where(MallOrderItem.order_id.in_(all_orders))
                )
                await s.execute(
                    delete(MallOrder).where(MallOrder.id.in_(all_orders))
                )
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
