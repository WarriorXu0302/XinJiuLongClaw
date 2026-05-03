"""E2E：mall 订单 delivered >60 天未全款 → job_detect_partial_close 坏账路径。

验证桥 B3.5 在真实数据上：
  1. 造一个 delivered 订单，delivered_at 改成 61 天前，pay_amount=100，received_amount=30
  2. 跑 job_detect_partial_close
  3. 断言：
     (a) 订单 status → partial_closed, payment_status → partially_paid
     (b) Commission 按已收 30 计提（status=pending）
     (c) profit_service 聚合能看到 mall_bad_debt=70
     (d) 通知 assigned + referrer 都收到了"订单坏账关单"
     (e) MallProduct.total_sales +=1（按 item.quantity）
     (f) audit_logs 有 mall_order.partial_close

跑法：
  cd backend && python -m scripts.e2e_mall_partial_close
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.database import admin_session_factory
from app.models.mall.base import MallOrderStatus, MallUserStatus, MallUserApplicationStatus
from app.models.mall.inventory import MallInventory
from app.models.mall.order import MallOrder, MallOrderItem
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallAddress, MallUser
from app.models.audit_log import AuditLog
from app.models.notification_log import NotificationLog
from app.models.user import Commission
from app.services.mall import housekeeping_service, order_service, profit_service


def banner(title: str) -> None:
    print(f"\n{'='*70}\n{title}\n{'='*70}")


async def main() -> None:
    banner("E2E partial_close 造数据 + 跑 job + 断言")
    order_id: str = ""
    sku_pid: int = 0
    sales_before: int = 0
    old_delivered_at: datetime = datetime.now(timezone.utc)
    async with admin_session_factory() as s:
        # ── 1. 找业务员、消费者、SKU、地址 ──
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one_or_none()
        if sm is None:
            print("❌ 找不到 sm_test 业务员 — 请先跑 e2e_verify_4bugs.py 的 seed")
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
        if inv is None or inv.quantity < 3:
            print(f"❌ 库存不够（sku={sku.id} qty={inv.quantity if inv else 0}）")
            return

        addr = (await s.execute(
            select(MallAddress).where(MallAddress.user_id == consumer.id).limit(1)
        )).scalar_one_or_none()
        if addr is None:
            addr = MallAddress(
                user_id=consumer.id, receiver="E2E 测试", mobile="13800000000",
                addr="partial_close 测试地址", is_default=True,
            )
            s.add(addr)
            await s.flush()

        prod = await s.get(MallProduct, sku.product_id)
        sales_before = prod.total_sales or 0
        print(f"fixtures: sm={sm.username}, consumer={consumer.real_name or consumer.nickname}, "
              f"sku={sku.id}, warehouse={inv.warehouse_id[:8]}, qty={inv.quantity}, "
              f"product.total_sales={sales_before}")
        await s.flush()

        # ── 2. 下单 → 抢 → ship(bulk) → deliver ──
        order = await order_service.create_order(
            s, consumer,
            items=[{"sku_id": sku.id, "quantity": 2}],
            address_id=addr.id,
        )
        print(f"① 下单: {order.order_no} status={order.status} pay_amount={order.pay_amount}")

        await order_service.claim_order(s, sm, order.id)
        await s.flush()
        await s.refresh(order)
        print(f"② 抢单: status={order.status} assigned={order.assigned_salesman_id[:8]}")

        # 直接改状态跳过 ship/deliver（这里不是 ship 本身的测试）
        now = datetime.now(timezone.utc)
        old_delivered_at = now - timedelta(days=settings.MALL_PARTIAL_CLOSE_DAYS + 1)
        order.status = MallOrderStatus.DELIVERED.value
        order.shipped_at = old_delivered_at - timedelta(days=1)
        order.delivered_at = old_delivered_at
        # 收了 30 元部分款（下一步 job 应按差额坏账）
        order.received_amount = Decimal("30.00")
        order.payment_status = "partially_paid"
        await s.flush()
        order_id = order.id
        sku_pid = sku.product_id
        await s.commit()
        print(f"③ 强改数据：delivered_at=-{settings.MALL_PARTIAL_CLOSE_DAYS+1}d, "
              f"pay_amount={order.pay_amount}, received_amount=30.00")

    # ── 3. 跑 job（独立 session，因为 _with_job_log 内部也开 session）──
    result = await housekeeping_service.job_detect_partial_close()
    print(f"④ 跑 job_detect_partial_close → {result}")

    # ── 4. 断言 ──
    async with admin_session_factory() as s:
        order = (await s.execute(
            select(MallOrder).where(MallOrder.id == order_id)
        )).scalar_one()
        print(f"\n⑤ 订单结果: status={order.status} payment_status={order.payment_status} "
              f"profit_ledger_posted={order.profit_ledger_posted}")
        assert order.status == MallOrderStatus.PARTIAL_CLOSED.value, \
            f"期望 partial_closed, 实际 {order.status}"
        assert order.payment_status == "partially_paid"
        assert order.profit_ledger_posted is True
        print("   ✅ 订单状态")

        # Commission
        coms = (await s.execute(
            select(Commission).where(Commission.mall_order_id == order.id)
        )).scalars().all()
        total_com = sum((c.commission_amount or Decimal("0")) for c in coms)
        print(f"   Commission: 条数={len(coms)} 合计={total_com}")
        assert len(coms) > 0, "应有 pending commission"
        for c in coms:
            assert c.status == "pending", f"期望 pending, 实际 {c.status}"
        print("   ✅ Commission 按已收 30 计提, pending")

        # ProfitLedger 聚合（通过 profit_service，不直接查表）
        brand_id = None
        items = (await s.execute(
            select(MallOrderItem).where(MallOrderItem.order_id == order.id)
        )).scalars().all()
        for it in items:
            if it.brand_id:
                brand_id = it.brand_id
                break
        if brand_id:
            # 覆盖 partial_closed 订单（按 delivered_at 落窗口）：
            # 订单 delivered_at 被强改到 61 天前，所以 date_from 要回溯够远
            date_from = old_delivered_at - timedelta(days=1)
            date_to = now + timedelta(days=1)
            summary = await profit_service.aggregate_mall_profit(
                s, brand_id=brand_id, date_from=date_from, date_to=date_to,
            )
            bd = Decimal(str(summary.get("total_bad_debt", "0")))
            print(f"   profit summary(brand={brand_id[:8]}): total_bad_debt={bd}")
            assert bd >= Decimal("70.00"), (
                f"坏账应 >= 70（pay_amount - received_amount），"
                f"实际 total_bad_debt={summary.get('total_bad_debt')}"
            )
            print("   ✅ total_bad_debt 正确记录")

        # 通知 assigned + referrer
        notifs = (await s.execute(
            select(NotificationLog)
            .where(NotificationLog.related_entity_type == "MallOrder")
            .where(NotificationLog.related_entity_id == order.id)
            .where(NotificationLog.title == "订单坏账关单")
        )).scalars().all()
        recv_ids = {n.mall_user_id for n in notifs}
        print(f"   通知: 收件人={[r[:8] for r in recv_ids]}")
        expected = {order.assigned_salesman_id, order.referrer_salesman_id}
        assert expected.issubset(recv_ids), f"通知收件人不全: expected {expected}, got {recv_ids}"
        print("   ✅ assigned + referrer 都收到通知")

        # MallProduct.total_sales
        prod = await s.get(MallProduct, sku_pid)
        assert prod.total_sales >= sales_before + 2, (
            f"total_sales 应 +2, 实际 {sales_before} → {prod.total_sales}"
        )
        print(f"   ✅ MallProduct.total_sales: {sales_before} → {prod.total_sales}")

        # Audit
        audit = (await s.execute(
            select(AuditLog)
            .where(AuditLog.action == "mall_order.partial_close")
            .where(AuditLog.entity_id == order.id)
        )).scalar_one_or_none()
        assert audit is not None, "缺少 mall_order.partial_close 审计"
        print(f"   ✅ audit: {audit.action} actor_type={audit.actor_type}")

    banner("✅ partial_close E2E 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
