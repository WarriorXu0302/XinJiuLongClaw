"""E2E：reversed commission 应该被下月工资单排除。

业务场景：业务员 X 上月某订单 → pending commission C_X
  → 当月退货 → C_X.status → reversed
  → 下月生成工资单 → C_X 不应被计入（只结 status=pending 的）

这个脚本用 SQL 直接造：
  1. 新建一个 salesman（linked_employee=E）
  2. 插 2 条 Commission(employee_id=E, mall_order_id=O1)：一条 pending 一条 reversed
  3. 模拟"工资单扫描"查询：按 generate_salary_records 的 filter 条件
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
from app.models.mall.user import MallUser
from app.models.user import Commission, Employee


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E：reversed commission 被下月工资单排除")

    async with admin_session_factory() as s:
        emp = (await s.execute(select(Employee).limit(1))).scalar_one()
        print(f"fixture employee={emp.id[:8]} name={emp.name}")

        fake_mall_order_id = str(uuid.uuid4())
        # 提前清理（幂等）
        await s.execute(
            delete(Commission)
            .where(Commission.employee_id == emp.id)
            .where(Commission.mall_order_id == fake_mall_order_id)
        )
        await s.commit()

        # 插 2 条 commission
        pending_c = Commission(
            id=str(uuid.uuid4()),
            employee_id=emp.id,
            mall_order_id=fake_mall_order_id,
            commission_amount=Decimal("50.00"),
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        reversed_c = Commission(
            id=str(uuid.uuid4()),
            employee_id=emp.id,
            mall_order_id=fake_mall_order_id,
            commission_amount=Decimal("30.00"),
            status="reversed",
            notes="[测试] 已退货冲销",
            created_at=datetime.now(timezone.utc),
        )
        s.add_all([pending_c, reversed_c])
        await s.commit()
        print(f"插入: pending={pending_c.id[:8]} ¥50, reversed={reversed_c.id[:8]} ¥30")

    # ── 模拟工资单扫描的 filter ──
    async with admin_session_factory() as s:
        rows = (await s.execute(
            select(Commission)
            .where(Commission.employee_id == emp.id)
            .where(Commission.mall_order_id.is_not(None))
            .where(Commission.status == "pending")  # 这条就是 payroll 路由的 filter
        )).scalars().all()

        print(f"\n查询结果（与 payroll 工资单扫描一致的 filter）：{len(rows)} 条")
        for r in rows:
            print(f"  - id={r.id[:8]} amount={r.commission_amount} status={r.status}")

        # 期望：只能看到 pending 的，amount=50
        assert len(rows) == 1, f"应有 1 条 pending，实际 {len(rows)}"
        assert rows[0].status == "pending"
        assert rows[0].commission_amount == Decimal("50.00")
        print("\n✅ reversed commission 被正确排除，仅 pending 计入")

    # ── 清理 ──
    async with admin_session_factory() as s:
        await s.execute(
            delete(Commission).where(Commission.mall_order_id == fake_mall_order_id)
        )
        await s.commit()
        print("✅ 测试数据已清理")


if __name__ == "__main__":
    asyncio.run(main())
