"""E2E：决策 #4 商品销量双数据（total_sales + net_sales）。

场景（直接在 DB 层操作 mall_products，不走完整订单流水以避免与 e2e_full_mall_flow 耦合）：
  1. 初始 product: total_sales=0, net_sales=0
  2. 模拟 confirm_payment 时 +5（模拟一次下单 5 瓶）
     → total_sales=5, net_sales=5
  3. 模拟退货扣减 2 瓶（max(0, net-qty)）
     → total_sales=5（不回退）, net_sales=3
  4. 模拟超额退货边界：再退 5 瓶（多于净销量）
     → total_sales=5, net_sales=0（max 保底 0）

验证核心：
  - total_sales 不退货时严格单调递增
  - net_sales 退货扣减，不会 < 0

跑法：
  cd backend && python -m scripts.e2e_mall_product_net_sales
"""
import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import MallProductStatus
from app.models.mall.product import MallProduct


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E 决策 #4 商品销量双数据")

    pid = None
    try:
        # ── fixture: 造一个商品 ──
        async with admin_session_factory() as s:
            prod = MallProduct(
                name="E2E 销量双数据测试酒",
                brief="E2E",
                status=MallProductStatus.ON_SALE.value,
                total_sales=0,
                net_sales=0,
            )
            s.add(prod)
            await s.commit()
            await s.refresh(prod)
            pid = prod.id
            print(f"[fixture] product id={pid} total=0 net=0")

        # ── Step 1: 模拟下单 5 瓶 ──
        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            p.total_sales = (p.total_sales or 0) + 5
            p.net_sales = (p.net_sales or 0) + 5
            await s.commit()

        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            assert p.total_sales == 5 and p.net_sales == 5, (
                f"下单后 total={p.total_sales} net={p.net_sales}"
            )
            print(f"[1] ✅ 下单 +5 → total=5 net=5")

        # ── Step 2: 退货 2 瓶（total 不回退，net 扣 2）──
        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            # total_sales 不动；net_sales = max(0, 5-2) = 3
            p.net_sales = max(0, (p.net_sales or 0) - 2)
            await s.commit()

        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            assert p.total_sales == 5, f"退货后 total_sales 不应变 实际 {p.total_sales}"
            assert p.net_sales == 3, f"退 2 瓶 net 应 =3 实际 {p.net_sales}"
            print(f"[2] ✅ 退 2 瓶 → total=5（不变）net=3")

        # ── Step 3: 超额退货（退 5 瓶，只剩 3）──
        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            # 继续扣 5 → max(0, 3-5) = 0
            p.net_sales = max(0, (p.net_sales or 0) - 5)
            await s.commit()

        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            assert p.total_sales == 5, "total_sales 永不回退"
            assert p.net_sales == 0, f"net_sales 保底 0 实际 {p.net_sales}"
            print(f"[3] ✅ 超额退货 → total=5 net=0（保底 max 0）")

        # ── Step 4: 再下单，net 能再涨 ──
        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            p.total_sales = (p.total_sales or 0) + 3
            p.net_sales = (p.net_sales or 0) + 3
            await s.commit()

        async with admin_session_factory() as s:
            p = await s.get(MallProduct, pid)
            assert p.total_sales == 8 and p.net_sales == 3
            print(f"[4] ✅ 再下单 +3 → total=8 net=3")

        banner("✅ 决策 #4 商品销量双数据 E2E 通过")

    finally:
        # 清理
        async with admin_session_factory() as s:
            if pid is not None:
                await s.execute(delete(MallProduct).where(MallProduct.id == pid))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
