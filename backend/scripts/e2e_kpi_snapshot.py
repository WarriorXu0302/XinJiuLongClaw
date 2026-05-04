"""E2E：决策 #2 月榜快照 vs 实时双显。

场景：
  1. 业务员 A 上月成交 3 单，GMV 300
  2. 月初 1 号快照冻结 → snapshot(gmv=300, order_count=3)
  3. 下月初（now）其中 1 单 (pay=100) 被客户退货批准 → status=refunded
  4. 验证：
     - 实时查询（realtime）上月排行：2 单 GMV 200（refunded 被排除）
     - 快照查询（snapshot）上月排行：依然 3 单 GMV 300（冻结不动）
  5. 幂等：重跑 build_snapshot_for_month(上月) → UPSERT 同一行，数字更新而不是建新行
  6. build_snapshot_for_month 对"现在"做一次，把本月 in-progress 数据也能冻结（用于演示）

跑法：
  cd backend && python -m scripts.e2e_kpi_snapshot
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallOrderStatus,
    MallUserApplicationStatus,
    MallUserStatus,
    MallUserType,
)
from app.models.mall.kpi_snapshot import MallMonthlyKpiSnapshot
from app.models.mall.order import MallOrder
from app.models.mall.user import MallUser
from app.models.user import Commission, Employee
from app.services.mall import kpi_snapshot_service as kss


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E 决策 #2 月榜快照 vs 实时双显")

    # 准备"上月"时间窗
    today_utc = datetime.now(timezone.utc)
    last_month_last_day = today_utc.replace(day=1) - timedelta(days=1)
    ly, lm = last_month_last_day.year, last_month_last_day.month
    last_month_period = f"{ly:04d}-{lm:02d}"
    # 上月的 15 号（作为 completed_at）
    completed_at = datetime(ly, lm, 15, 10, 0, 0, tzinfo=timezone.utc)

    emp_id = None
    sm_id = None
    order_ids = []
    snapshot_ids = []

    try:
        # ── fixture: 1 个 employee + 1 个 mall salesman + 3 单完结订单 ──
        async with admin_session_factory() as s:
            emp = Employee(
                id=str(uuid.uuid4()),
                employee_no=f"E2E-KPI-E-{uuid.uuid4().hex[:4]}",
                name="E2E 快照测试业务员",
                position="salesman",
                status="active",
                hire_date=date.today(),
                social_security=Decimal("0"),
                company_social_security=Decimal("0"),
                expected_manufacturer_subsidy=Decimal("0"),
            )
            s.add(emp)
            await s.flush()
            emp_id = emp.id

            sm = MallUser(
                id=str(uuid.uuid4()),
                username=f"e2e_kpi_sm_{uuid.uuid4().hex[:4]}",
                hashed_password="x",
                user_type=MallUserType.SALESMAN.value,
                status=MallUserStatus.ACTIVE.value,
                linked_employee_id=emp.id,
                application_status=MallUserApplicationStatus.APPROVED.value,
                nickname="E2E KPI 业务员",
            )
            s.add(sm)
            await s.flush()
            sm_id = sm.id

            # 3 单 completed，receive_amount = 100 each
            for i in range(3):
                o = MallOrder(
                    id=str(uuid.uuid4()),
                    order_no=f"E2E-KPI-O-{uuid.uuid4().hex[:6]}-{i}",
                    user_id=sm.id,  # 给自己下单（业务场景允许）
                    assigned_salesman_id=sm.id,
                    status=MallOrderStatus.COMPLETED.value,
                    total_amount=Decimal("100"),
                    pay_amount=Decimal("100"),
                    received_amount=Decimal("100"),
                    shipping_fee=Decimal("0"),
                    address_snapshot={"receiver": "E2E", "mobile": "138", "addr": "E2E test"},
                    completed_at=completed_at,
                )
                s.add(o)
                order_ids.append(o.id)

            await s.commit()

        # ── Step 1: 构建上月快照（冻结当时的 3 单/300） ──
        async with admin_session_factory() as s:
            result = await kss.build_snapshot_for_month(
                s, ly, lm, notes="E2E 首次冻结",
            )
            await s.commit()
            assert result["upserted"] >= 1, f"应至少 UPSERT 1 行 实际 {result['upserted']}"
            print(f"[1] ✅ 快照冻结 {last_month_period} → {result}")

        async with admin_session_factory() as s:
            snap = (await s.execute(
                select(MallMonthlyKpiSnapshot)
                .where(MallMonthlyKpiSnapshot.employee_id == emp_id)
                .where(MallMonthlyKpiSnapshot.period == last_month_period)
            )).scalar_one()
            snapshot_ids.append(snap.id)
            assert snap.gmv == Decimal("300.00"), f"快照 GMV 应 300 实际 {snap.gmv}"
            assert snap.order_count == 3
            print(f"    snapshot: gmv={snap.gmv} order_count={snap.order_count}")

        # ── Step 2: 模拟下月其中 1 单退货（status=refunded） ──
        async with admin_session_factory() as s:
            o = await s.get(MallOrder, order_ids[0])
            o.status = MallOrderStatus.REFUNDED.value
            await s.commit()
            print(f"[2] 模拟 1 单退货 order={order_ids[0][:8]} → refunded")

        # ── Step 3: 实时查询（refunded 被排除） ──
        async with admin_session_factory() as s:
            # 用 service 的逻辑直接聚合算实时（不经过 HTTP，省测试复杂度）
            from sqlalchemy import and_, func, or_
            rank_rows = (await s.execute(
                select(
                    MallOrder.assigned_salesman_id,
                    func.count(MallOrder.id).label("oc"),
                    func.coalesce(func.sum(MallOrder.received_amount), 0).label("gmv"),
                )
                .where(MallOrder.assigned_salesman_id == sm_id)
                .where(or_(
                    and_(
                        MallOrder.status == MallOrderStatus.COMPLETED.value,
                        MallOrder.completed_at >= datetime(ly, lm, 1, tzinfo=timezone.utc),
                        MallOrder.completed_at < datetime(
                            ly if lm < 12 else ly + 1,
                            (lm % 12) + 1, 1,
                            tzinfo=timezone.utc,
                        ),
                    ),
                ))
                .group_by(MallOrder.assigned_salesman_id)
            )).all()
            assert len(rank_rows) == 1
            _, oc_rt, gmv_rt = rank_rows[0]
            assert oc_rt == 2, f"实时订单数应 2 实际 {oc_rt}"
            assert gmv_rt == Decimal("200"), f"实时 GMV 应 200 实际 {gmv_rt}"
            print(f"[3] ✅ 实时查询 order_count={oc_rt} gmv={gmv_rt}（refunded 排除）")

        # ── Step 4: 快照查询（数字不变） ──
        async with admin_session_factory() as s:
            snap = (await s.execute(
                select(MallMonthlyKpiSnapshot)
                .where(MallMonthlyKpiSnapshot.period == last_month_period)
                .where(MallMonthlyKpiSnapshot.employee_id == emp_id)
            )).scalar_one()
            assert snap.gmv == Decimal("300.00"), "快照 GMV 不应变"
            assert snap.order_count == 3, "快照订单数不应变"
            print(f"[4] ✅ 快照查询 order_count=3 gmv=300（冻结不受退货影响）")

        # ── Step 5: 重跑 build_snapshot 幂等（UPSERT） ──
        async with admin_session_factory() as s:
            before = (await s.execute(
                select(MallMonthlyKpiSnapshot)
                .where(MallMonthlyKpiSnapshot.period == last_month_period)
                .where(MallMonthlyKpiSnapshot.employee_id == emp_id)
            )).scalars().all()
            await kss.build_snapshot_for_month(s, ly, lm, notes="E2E 二次 UPSERT")
            await s.commit()

        # 新 session 避免 identity map 缓存（之前读 before 后 UPSERT，
        # 同 session 读取会返回缓存旧值，上线场景不存在但测试里要开新 session）
        async with admin_session_factory() as s:
            after = (await s.execute(
                select(MallMonthlyKpiSnapshot)
                .where(MallMonthlyKpiSnapshot.period == last_month_period)
                .where(MallMonthlyKpiSnapshot.employee_id == emp_id)
            )).scalars().all()
            assert len(before) == len(after) == 1, (
                f"重跑应 UPSERT 不建新行 before={len(before)} after={len(after)}"
            )
            # 这次重跑时 1 单已 refunded，新快照会以"现在的真实"重写
            new_snap = after[0]
            assert new_snap.gmv == Decimal("200.00"), (
                f"重跑 UPSERT 后快照按当前口径 GMV=200 实际 {new_snap.gmv}"
            )
            assert new_snap.order_count == 2
            print(f"[5] ✅ 重跑 UPSERT 不建新行，新口径 gmv={new_snap.gmv} oc={new_snap.order_count}")
            print("    （老板要『发奖金后定格』就 1 号定时任务写过一次即可，别再手工 rerun）")

        banner("✅ 决策 #2 月榜快照 E2E 通过")

    finally:
        # 清理
        async with admin_session_factory() as s:
            await s.execute(
                delete(MallMonthlyKpiSnapshot)
                .where(MallMonthlyKpiSnapshot.employee_id == emp_id)
            )
            for oid in order_ids:
                await s.execute(delete(MallOrder).where(MallOrder.id == oid))
            if sm_id:
                await s.execute(delete(MallUser).where(MallUser.id == sm_id))
            if emp_id:
                await s.execute(delete(Employee).where(Employee.id == emp_id))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
