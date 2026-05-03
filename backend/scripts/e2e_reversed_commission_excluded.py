"""E2E：reversed commission 应该被下月工资单排除。

业务场景：业务员 X 上月某订单 → pending commission C_X
  → 当月退货 → C_X.status → reversed
  → 下月生成工资单 → C_X 不应被计入（只结 status=pending 的）

脚本做法：
  1. 找已有的 mall_user(consumer) + employee，造一个最小 MallOrder 作为 FK 目标
  2. 插 2 条 Commission(employee_id=E, mall_order_id=O1)：pending ¥50 + reversed ¥30
  3. 模拟 payroll.generate_salary_records 的 filter 条件查询
  4. 断言只能查到 pending 的那条

不真实跑 generate_salary_records（跨多张表，依赖很多），
只验证提成筛选条件（Commission.status=='pending'）本身是有效的。

跑法：
  cd backend && python -m scripts.e2e_reversed_commission_excluded
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import MallOrderStatus
from app.models.mall.order import MallOrder
from app.models.mall.user import MallUser
from app.models.user import Commission, Employee


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E：reversed commission 被下月工资单排除")

    async with admin_session_factory() as s:
        emp = (await s.execute(select(Employee).limit(1))).scalar_one()
        consumer = (await s.execute(
            select(MallUser).where(MallUser.user_type == "consumer").limit(1)
        )).scalar_one()
        print(f"fixture employee={emp.id[:8]} name={emp.name}, consumer={consumer.id[:8]}")

        # 造一个最小可用的 MallOrder（只为 commission.mall_order_id FK）
        mall_order_no = f"E2E-RC-{uuid.uuid4().hex[:8].upper()}"
        mall_order = MallOrder(
            id=str(uuid.uuid4()),
            order_no=mall_order_no,
            user_id=consumer.id,
            address_snapshot={"receiver": "e2e-test", "mobile": "00000000000", "addr": "test"},
            status=MallOrderStatus.COMPLETED.value,
            payment_status="fully_paid",
            total_amount=Decimal("80.00"),
            shipping_fee=Decimal("0"),
            discount_amount=Decimal("0"),
            pay_amount=Decimal("80.00"),
            received_amount=Decimal("80.00"),
            created_at=datetime.now(timezone.utc),
        )
        s.add(mall_order)
        await s.commit()
        real_mall_order_id = mall_order.id
        print(f"造单: order_no={mall_order_no}")

    try:
        # 插 2 条 commission
        async with admin_session_factory() as s:
            # 幂等清理（理论上此 order_id 是全新的，但以防万一）
            await s.execute(
                delete(Commission).where(Commission.mall_order_id == real_mall_order_id)
            )
            pending_c = Commission(
                id=str(uuid.uuid4()),
                employee_id=emp.id,
                mall_order_id=real_mall_order_id,
                commission_amount=Decimal("50.00"),
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            reversed_c = Commission(
                id=str(uuid.uuid4()),
                employee_id=emp.id,
                mall_order_id=real_mall_order_id,
                commission_amount=Decimal("30.00"),
                status="reversed",
                notes="[测试] 已退货冲销",
                created_at=datetime.now(timezone.utc),
            )
            s.add_all([pending_c, reversed_c])
            await s.commit()
            print(f"插入: pending={pending_c.id[:8]} ¥50, reversed={reversed_c.id[:8]} ¥30")

        # ── 模拟 payroll 工资单扫描的 filter ──
        async with admin_session_factory() as s:
            rows = (await s.execute(
                select(Commission)
                .where(Commission.employee_id == emp.id)
                .where(Commission.mall_order_id == real_mall_order_id)  # 限定本次插的，不被其他数据干扰
                .where(Commission.status == "pending")  # payroll 路由的关键 filter
            )).scalars().all()

            print(f"\n查询结果（与 payroll 工资单扫描一致的 filter）：{len(rows)} 条")
            for r in rows:
                print(f"  - id={r.id[:8]} amount={r.commission_amount} status={r.status}")

            assert len(rows) == 1, f"应有 1 条 pending，实际 {len(rows)}"
            assert rows[0].status == "pending"
            assert rows[0].commission_amount == Decimal("50.00")
            print("\n✅ reversed commission 被正确排除，仅 pending 计入")

    finally:
        # 清理
        async with admin_session_factory() as s:
            await s.execute(
                delete(Commission).where(Commission.mall_order_id == real_mall_order_id)
            )
            await s.execute(
                delete(MallOrder).where(MallOrder.id == real_mall_order_id)
            )
            await s.commit()
            print("✅ 测试数据已清理")


if __name__ == "__main__":
    asyncio.run(main())
