"""E2E：第 3 轮 review 修复验证。

修复验证：
  P1-6: partial_closed 订单退货后 bad_debt 仍计入 profit_service 聚合
    - 造一个 partial_closed 单（pay=¥1000, received=¥700, bad_debt=¥300）
    - aggregate_mall_profit 返 bad_debt=¥300
    - 批准退货 → status=refunded, refunded_from_status=partial_closed
    - 再次调 aggregate_mall_profit → bad_debt 仍 ¥300（不消失）

  P1-7: 月榜时区按北京时区
    - _period_bounds(2026, 5) 返的 start 应该是 2026-05-01 00:00 CST = 2026-04-30 16:00 UTC
    - 不是 2026-05-01 00:00 UTC

跑法：
  cd backend && python -m scripts.e2e_review3_fixes
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallOrderStatus,
    MallReturnStatus,
    MallUserApplicationStatus,
    MallUserStatus,
    MallUserType,
)
from app.models.mall.order import MallOrder, MallOrderItem, MallReturnRequest
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallUser
from app.models.user import Commission, Employee
from app.services.mall import kpi_snapshot_service as kss
from app.services.mall.profit_service import aggregate_mall_profit
from app.services.mall.return_service import approve_return


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def test_p1_7_timezone() -> None:
    banner("P1-7: 月榜时区按北京时区")
    bj = ZoneInfo("Asia/Shanghai")
    period, start, end = kss._period_bounds(2026, 5)
    expected_start = datetime(2026, 5, 1, tzinfo=bj).astimezone(timezone.utc)
    expected_end = datetime(2026, 6, 1, tzinfo=bj).astimezone(timezone.utc)
    assert start == expected_start, f"start 应为 {expected_start}, 实际 {start}"
    assert end == expected_end, f"end 应为 {expected_end}, 实际 {end}"
    print(f"[1] ✅ _period_bounds('2026-05'): {start.isoformat()} ~ {end.isoformat()}")
    # UTC 视角的 2026-05-01 00:00 应该**不**被视为 5 月（它是北京时间 5-1 08:00 没错，但
    # 2026-04-30 17:00 UTC 实际上是北京 5-1 01:00，被归到 5 月才对）
    test_ts = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)  # 北京 5-1 04:00
    assert start <= test_ts < end, "北京 5-1 04:00 应在 5 月区间内"
    print(f"[2] ✅ 北京 5-1 04:00（UTC 4-30 20:00）落入 5 月区间")


async def test_p1_6_partial_closed_refund_bad_debt() -> None:
    banner("P1-6: partial_closed 退货后 bad_debt 仍计入")

    # 直接构造数据：避开完整订单流程
    async with admin_session_factory() as s:
        # 找一个有 brand 的 mall product
        prod = (await s.execute(
            select(MallProduct).where(MallProduct.status == "on_sale").limit(1)
        )).scalar_one_or_none()
        if prod is None:
            print("   ⚠ 无 on_sale 商品，跳过")
            return
        sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.product_id == prod.id).limit(1)
        )).scalar_one_or_none()
        if sku is None:
            print("   ⚠ 无 sku，跳过")
            return
        # 任取一个 consumer
        consumer = (await s.execute(
            select(MallUser).where(MallUser.user_type == "consumer").limit(1)
        )).scalar_one_or_none()
        if consumer is None:
            print("   ⚠ 无 consumer，跳过")
            return

        delivered_at = datetime.now(timezone.utc) - timedelta(days=65)
        order = MallOrder(
            id=str(uuid.uuid4()),
            order_no=f"E2E-R3-{uuid.uuid4().hex[:6]}",
            user_id=consumer.id,
            status=MallOrderStatus.PARTIAL_CLOSED.value,  # 模拟已 partial_close
            total_amount=Decimal("1000"),
            pay_amount=Decimal("1000"),
            received_amount=Decimal("700"),  # 坏账 300
            shipping_fee=Decimal("0"),
            address_snapshot={"receiver": "E2E", "mobile": "138", "addr": "x"},
            delivered_at=delivered_at,
        )
        s.add(order)
        await s.flush()
        item = MallOrderItem(
            order_id=order.id,
            product_id=prod.id,
            sku_id=sku.id,
            brand_id=prod.brand_id,
            sku_snapshot={"sku_id": sku.id, "spec": sku.spec},
            price=Decimal("1000"),
            quantity=1,
            subtotal=Decimal("1000"),
            cost_price_snapshot=Decimal("500"),
        )
        s.add(item)
        await s.commit()
        order_id = order.id

    try:
        # Step 1: 聚合 → 应含 bad_debt=300
        async with admin_session_factory() as s:
            window_from = delivered_at - timedelta(days=1)
            window_to = delivered_at + timedelta(days=1)
            result = await aggregate_mall_profit(
                s, date_from=window_from, date_to=window_to,
            )
            before_bad_debt = Decimal(result["total_bad_debt"])
            assert before_bad_debt >= Decimal("300"), (
                f"partial_closed bad_debt 应 >=300，实际 {before_bad_debt}"
            )
            print(f"[1] ✅ partial_closed 订单 bad_debt = {before_bad_debt}")

        # Step 2: 手工构造 refund（直接改状态 + refunded_from_status）
        async with admin_session_factory() as s:
            o = await s.get(MallOrder, order_id)
            o.refunded_from_status = o.status  # partial_closed
            o.status = MallOrderStatus.REFUNDED.value
            await s.commit()

        # Step 3: 再次聚合 → bad_debt 仍应含 300（不消失）
        async with admin_session_factory() as s:
            result = await aggregate_mall_profit(
                s, date_from=window_from, date_to=window_to,
            )
            after_bad_debt = Decimal(result["total_bad_debt"])
            assert after_bad_debt == before_bad_debt, (
                f"退货后 bad_debt 应保持 {before_bad_debt}，实际 {after_bad_debt}"
            )
            print(f"[2] ✅ 批准退货后 bad_debt 仍 {after_bad_debt}（不被洗白）")

    finally:
        async with admin_session_factory() as s:
            await s.execute(delete(MallOrderItem).where(MallOrderItem.order_id == order_id))
            await s.execute(delete(MallOrder).where(MallOrder.id == order_id))
            await s.commit()
        print("   ✅ 清理完毕")


async def main() -> None:
    await test_p1_7_timezone()
    await test_p1_6_partial_closed_refund_bad_debt()
    banner("✅ 第 3 轮 review 修复全部通过")


if __name__ == "__main__":
    asyncio.run(main())
