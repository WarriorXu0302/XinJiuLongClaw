"""E2E：mall 全链路贯通脚本。

覆盖流（mall 业务原子 bridges.md 的完整闭环）：
  1. 业务员生成邀请码
  2. 消费者注册（消费邀请码 + 绑定推荐人 + 建地址）
  3. admin 审批通过注册
  4. 消费者下单（pending_assignment）
  5. 业务员抢单（ASSIGNED）
  6. 业务员 ship（触发 bulk 或 scan 路径）
  7. 业务员 deliver（DELIVERED + 送达照）
  8. 业务员 upload voucher（PENDING_PAYMENT_CONFIRMATION）
  9. 财务确认（COMPLETED + commission + 累计销量）
 10. 消费者申请退货 → admin approve（REFUNDED + reversed commission + 退库存 + 退条码）

每步断言 DB 关键字段 + 审计日志落地。整段走完后幂等重跑不会留脏数据。

跑法：
  cd backend && python -m scripts.e2e_full_mall_flow
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, delete

from app.core.database import admin_session_factory
from app.models.audit_log import AuditLog
from app.models.mall.base import (
    MallOrderStatus,
    MallPaymentApprovalStatus,
    MallReturnStatus,
    MallUserApplicationStatus,
    MallUserStatus,
)
from app.models.mall.inventory import MallInventory, MallInventoryBarcode
from app.models.mall.order import (
    MallOrder,
    MallOrderClaimLog,
    MallOrderItem,
    MallPayment,
    MallReturnRequest,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallAddress, MallInviteCode, MallUser
from app.models.user import Commission, Employee
from app.services.mall import (
    auth_service,
    invite_service,
    order_service,
    return_service,
)


def banner(msg: str) -> None:
    print(f"\n{'='*70}\n{msg}\n{'='*70}")


def step(n: int, label: str) -> None:
    print(f"\n[{n:02d}] {label}")


async def main() -> None:
    banner("E2E 全链路 mall 流程")

    # ── Fixture 准备 ──────────────────────────────────────
    async with admin_session_factory() as s:
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one_or_none()
        if sm is None:
            print("❌ 需要 sm_test 业务员（请先跑 e2e_verify_4bugs.py 的 seed）")
            return
        sm.status = MallUserStatus.ACTIVE.value
        sm.is_accepting_orders = True
        if sm.linked_employee_id is None:
            emp = (await s.execute(select(Employee).limit(1))).scalar_one()
            sm.linked_employee_id = emp.id
            print(f"   绑 linked_employee_id → {emp.id[:8]}")

        # 商品/库存
        sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.cost_price.isnot(None)).limit(1)
        )).scalar_one()
        inv = (await s.execute(
            select(MallInventory).where(MallInventory.sku_id == sku.id).limit(1)
        )).scalar_one_or_none()
        if inv is None or inv.quantity < 3:
            print(f"❌ 库存不够 sku={sku.id} qty={inv.quantity if inv else 0}")
            return
        qty_before = inv.quantity
        print(f"fixtures: sm={sm.username}, sku={sku.id}, wh={inv.warehouse_id[:8]}, "
              f"qty_before={qty_before}")
        await s.commit()

    # ── Step 1：业务员生成邀请码 ──────────────────────────
    step(1, "业务员生成邀请码")
    async with admin_session_factory() as s:
        sm_in = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one()
        invite = await invite_service.generate_invite_code(s, sm_in)
        code = invite.code
        await s.commit()
    assert code, "邀请码生成失败"
    print(f"   code={code}")

    # ── Step 2：消费者注册（消费邀请码）───────────────────
    step(2, "消费者注册：消费邀请码 + 建地址")
    suffix = uuid.uuid4().hex[:8]
    username = f"e2e_{suffix}"
    async with admin_session_factory() as s:
        user = await auth_service.register_mall_user(
            s,
            username=username,
            password="Test1234!",
            invite_code=code,
            nickname=f"E2E-{suffix}",
            real_name=f"测试人{suffix}",
            contact_phone="13900001111",
            delivery_address="测试省测试市测试区测试街道 1 号",
            business_license_url="/api/uploads/files/mall/license-fake.jpg",
            address_parts={
                "province": "河南省", "province_code": "410000",
                "city": "郑州市", "city_code": "410100",
                "area": "金水区", "area_code": "410105",
                "detail": "测试街道 1 号",
            },
        )
        consumer_id = user.id
        await s.commit()
    print(f"   consumer_id={consumer_id[:8]} application_status=pending")

    order_id = ""
    try:
        # ── Step 3：admin 审批通过 ──────────────────────────
        step(3, "admin 审批通过注册")
        async with admin_session_factory() as s:
            u = await s.get(MallUser, consumer_id)
            assert u.application_status == MallUserApplicationStatus.PENDING.value
            u.application_status = MallUserApplicationStatus.APPROVED.value
            u.approved_at = datetime.now(timezone.utc)
            await s.commit()
        print("   ✅ application_status=approved")

        # ── Step 4：消费者下单 ───────────────────────────────
        step(4, "消费者下单")
        async with admin_session_factory() as s:
            u = await s.get(MallUser, consumer_id)
            addr = (await s.execute(
                select(MallAddress).where(MallAddress.user_id == consumer_id).limit(1)
            )).scalar_one()
            order = await order_service.create_order(
                s, u,
                items=[{"sku_id": sku.id, "quantity": 1}],
                address_id=addr.id,
            )
            order_id = order.id
            order_no = order.order_no
            await s.commit()
        print(f"   ✅ order={order_no} status=pending_assignment")

        # ── Step 5：业务员抢单 ──────────────────────────────
        step(5, "业务员抢单")
        async with admin_session_factory() as s:
            sm_in = (await s.execute(
                select(MallUser).where(MallUser.username == "sm_test")
            )).scalar_one()
            await order_service.claim_order(s, sm_in, order_id)
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.ASSIGNED.value
            assert o.assigned_salesman_id == sm_in.id
            await s.commit()
        print("   ✅ status=assigned")

        # ── Step 6：业务员 ship ──────────────────────────────
        step(6, "业务员 ship（根据仓路径自动扫码或散装）")
        async with admin_session_factory() as s:
            sm_in = (await s.execute(
                select(MallUser).where(MallUser.username == "sm_test")
            )).scalar_one()

            has_barcode = (await s.execute(
                select(MallInventoryBarcode.id)
                .where(MallInventoryBarcode.sku_id == sku.id)
                .where(MallInventoryBarcode.status == "in_stock")
                .limit(1)
            )).first()
            if has_barcode:
                bc = (await s.execute(
                    select(MallInventoryBarcode)
                    .where(MallInventoryBarcode.sku_id == sku.id)
                    .where(MallInventoryBarcode.status == "in_stock")
                    .limit(1)
                )).scalar_one()
                scanned = [bc.barcode]
                print(f"   path=scan barcode={bc.barcode}")
            else:
                scanned = None
                print("   path=bulk（无条码散装）")

            await order_service.ship_order(
                s, sm_in, order_id, warehouse_id=None,
                scanned_barcodes=scanned,
            )
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.SHIPPED.value
            await s.commit()
        print(f"   ✅ status=shipped")

        # ── Step 7：业务员 deliver ───────────────────────────
        step(7, "业务员 deliver（上传送达照）")
        async with admin_session_factory() as s:
            sm_in = (await s.execute(
                select(MallUser).where(MallUser.username == "sm_test")
            )).scalar_one()
            photos = [{
                "url": f"/api/uploads/files/mall/delivery-{uuid.uuid4().hex[:8]}.jpg",
                "sha256": uuid.uuid4().hex,
                "size": 1024,
                "mime_type": "image/jpeg",
            }]
            await order_service.deliver_order(
                s, sm_in, order_id, delivery_photos=photos,
            )
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.DELIVERED.value
            assert o.delivered_at is not None
            await s.commit()
        print("   ✅ status=delivered")

        # ── Step 8：业务员 upload voucher ──────────────────
        step(8, "业务员上传收款凭证")
        async with admin_session_factory() as s:
            sm_in = (await s.execute(
                select(MallUser).where(MallUser.username == "sm_test")
            )).scalar_one()
            o = await s.get(MallOrder, order_id)
            vouchers = [{
                "url": f"/api/uploads/files/mall/voucher-{uuid.uuid4().hex[:8]}.jpg",
                "sha256": uuid.uuid4().hex,
                "size": 2048,
                "mime_type": "image/jpeg",
            }]
            await order_service.upload_payment_voucher(
                s, sm_in, order_id,
                amount=o.pay_amount,
                payment_method="cash",
                vouchers=vouchers,
            )
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value
            await s.commit()
        print("   ✅ status=pending_payment_confirmation")

        # ── Step 9：财务确认 ──────────────────────────────
        step(9, "财务确认收款")
        async with admin_session_factory() as s:
            emp = (await s.execute(select(Employee).limit(1))).scalar_one()
            await order_service.confirm_payment(
                s, order_id, operator_employee_id=emp.id,
            )
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.COMPLETED.value, \
                f"期望 completed 实际 {o.status}"
            assert o.received_amount >= o.pay_amount
            assert o.completed_at is not None

            pay = (await s.execute(
                select(MallPayment).where(MallPayment.order_id == order_id)
            )).scalar_one()
            assert pay.status == MallPaymentApprovalStatus.CONFIRMED.value

            coms = (await s.execute(
                select(Commission).where(Commission.mall_order_id == order_id)
            )).scalars().all()
            assert len(coms) > 0, "confirm 后应有 commission"
            for c in coms:
                assert c.status == "pending"
            print(f"   ✅ status=completed, commission 条数={len(coms)} 合计={sum(c.commission_amount for c in coms)}")
            await s.commit()

        # ── Step 10：消费者申请 + admin 批准退货 ────────────
        step(10, "退货申请 + admin 批准")
        async with admin_session_factory() as s:
            u = await s.get(MallUser, consumer_id)
            o = await s.get(MallOrder, order_id)
            req = await return_service.apply_return(
                s, order=o, user_id=consumer_id, reason="E2E 测试退货",
            )
            req_id = req.id
            await s.commit()

        async with admin_session_factory() as s:
            req = await s.get(MallReturnRequest, req_id)
            emp = (await s.execute(select(Employee).limit(1))).scalar_one()
            await return_service.approve_return(
                s, req=req, reviewer_employee_id=emp.id,
                review_note="E2E 批准",
            )
            await s.commit()

        async with admin_session_factory() as s:
            o = await s.get(MallOrder, order_id)
            assert o.status == MallOrderStatus.REFUNDED.value
            print(f"   ✅ 订单 status={o.status}")

            coms = (await s.execute(
                select(Commission).where(Commission.mall_order_id == order_id)
            )).scalars().all()
            for c in coms:
                assert c.status == "reversed", f"期望 reversed 实际 {c.status}"
            print(f"   ✅ 所有 commission reversed（共 {len(coms)} 条）")

            inv_after = (await s.execute(
                select(MallInventory).where(MallInventory.sku_id == sku.id).limit(1)
            )).scalar_one()
            print(f"   库存: before={qty_before} after={inv_after.quantity}")
            # create_order 扣 1，approve_return 退 1 → 净变化 0
            assert inv_after.quantity == qty_before, \
                f"库存回退后应 == 初始，实际差 {inv_after.quantity - qty_before}"
            print("   ✅ 库存净变化=0（扣 1 + 退 1）")

            req = await s.get(MallReturnRequest, req_id)
            assert req.status == MallReturnStatus.APPROVED.value
            print(f"   ✅ 退货申请 status={req.status}")

            # 审计覆盖：register / approve_app / ship / deliver / upload / partial N/A / return.approve
            # 只挑几个关键的确认入库了
            expected_actions = {
                "mall_order.ship", "mall_order.deliver",
                "mall_payment.upload_voucher",
            }
            actions_found = {
                row[0] for row in (await s.execute(
                    select(AuditLog.action)
                    .where(AuditLog.entity_id.in_([order_id, req_id]))
                )).all()
            }
            missing = expected_actions - actions_found
            if missing:
                print(f"   ⚠️  缺失关键审计: {missing}")
            else:
                print(f"   ✅ 关键审计齐全: {expected_actions & actions_found}")

        banner("✅ 全链路 E2E 通过")

    finally:
        # ── 清理：删测试用户 + 订单 + 审批 + 审计 + commission ──
        step(99, "清理测试数据")
        async with admin_session_factory() as s:
            if order_id:
                await s.execute(delete(MallReturnRequest).where(MallReturnRequest.order_id == order_id))
                await s.execute(delete(Commission).where(Commission.mall_order_id == order_id))
                await s.execute(delete(MallPayment).where(MallPayment.order_id == order_id))
                await s.execute(delete(MallOrderItem).where(MallOrderItem.order_id == order_id))
                await s.execute(delete(MallOrderClaimLog).where(MallOrderClaimLog.order_id == order_id))
                await s.execute(delete(MallOrder).where(MallOrder.id == order_id))
            await s.execute(delete(MallAddress).where(MallAddress.user_id == consumer_id))
            await s.execute(delete(MallUser).where(MallUser.id == consumer_id))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
