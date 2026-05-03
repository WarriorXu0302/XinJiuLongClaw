"""E2E：验证 dismissed=True 的 skip_log 不计入告警阈值。

场景：
  1. 造 3 条 skip_log（customer C + salesman S）
  2. 手动将其中 1 条改成 dismissed=True
  3. 手动触发第 4 次跳单（_record_skip_log）→ 不应建 alert（2 + 1 新 = 3 > 阈值 3 False；需严格 ≥）
     实际阈值 = MALL_SKIP_ALERT_THRESHOLD（默认 3）
  4. 第 5 次跳单（_record_skip_log）→ 应建 alert（3 + 1 新 = 4 ≥ 3）

断言 MallSkipAlert 数量符合预期。

跑法：
  cd backend && python -m scripts.e2e_skip_alert_threshold
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select, update as sa_update

from app.core.config import settings
from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallOrderStatus,
    MallSkipAlertStatus,
    MallSkipType,
    MallUserStatus,
)
from app.models.mall.order import (
    MallCustomerSkipLog,
    MallOrder,
    MallSkipAlert,
)
from app.models.mall.user import MallUser
from app.services.mall.order_service import _record_skip_log


def banner(msg: str) -> None:
    print(f"\n{'='*70}\n{msg}\n{'='*70}")


async def main() -> None:
    banner("E2E skip_alert threshold with dismissed exclusion")
    THRESHOLD = settings.MALL_SKIP_ALERT_THRESHOLD
    WINDOW = settings.MALL_SKIP_ALERT_WINDOW_DAYS
    print(f"阈值={THRESHOLD}，窗口={WINDOW}d")

    async with admin_session_factory() as s:
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one_or_none()
        if sm is None:
            print("❌ 需要 sm_test")
            return
        consumer = (await s.execute(
            select(MallUser).where(MallUser.user_type == "consumer").limit(1)
        )).scalar_one()
        print(f"fixtures: salesman={sm.username}, consumer={consumer.id[:8]}")

        # 清理历史遗留
        await s.execute(
            delete(MallSkipAlert)
            .where(MallSkipAlert.customer_user_id == consumer.id)
            .where(MallSkipAlert.salesman_user_id == sm.id)
        )
        await s.execute(
            delete(MallCustomerSkipLog)
            .where(MallCustomerSkipLog.customer_user_id == consumer.id)
            .where(MallCustomerSkipLog.salesman_user_id == sm.id)
        )
        await s.commit()

    # ── 用 1 个真实 MallOrder 作 ref_order（reuse 同一单即可） ──
    async with admin_session_factory() as s:
        ref_order = (await s.execute(
            select(MallOrder).where(MallOrder.user_id == consumer.id).limit(1)
        )).scalar_one_or_none()
        if ref_order is None:
            # 造一个 stub order（状态 pending_assignment 不干扰其他流程）
            print("❌ 没有现成 order，跳过（请先让这个 consumer 下一单再跑）")
            return
        ref_order_id = ref_order.id
        print(f"ref_order={ref_order_id[:8]}")

    # ── Step 1: 写 2 条有效 skip_log（customer+salesman 匹配）──
    for i in range(THRESHOLD - 1):
        async with admin_session_factory() as s:
            o = await s.get(MallOrder, ref_order_id)
            await _record_skip_log(
                s, o, salesman_user_id=sm.id,
                skip_type=MallSkipType.NOT_CLAIMED_IN_TIME.value,
            )
            await s.commit()
    print(f"① 写了 {THRESHOLD - 1} 条有效 skip_log")

    # ── Step 2: 先造 1 条 dismissed=True 的"老历史"skip_log ──
    async with admin_session_factory() as s:
        dismissed_log = MallCustomerSkipLog(
            customer_user_id=consumer.id,
            salesman_user_id=sm.id,
            order_id=ref_order_id,
            skip_type=MallSkipType.ADMIN_REASSIGNED.value,
            dismissed=True,  # 被 admin 驳回过的
        )
        s.add(dismissed_log)
        await s.commit()
    print("② 注入 1 条 dismissed=True skip_log（应被阈值计算排除）")

    # ── 检查：当前 alert 数 = 0（threshold-1 条非 dismissed < 阈值）──
    async with admin_session_factory() as s:
        alerts = (await s.execute(
            select(MallSkipAlert)
            .where(MallSkipAlert.customer_user_id == consumer.id)
            .where(MallSkipAlert.salesman_user_id == sm.id)
        )).scalars().all()
        assert len(alerts) == 0, f"threshold 未到，不该有 alert；实际 {len(alerts)}"
        total_logs = int((await s.execute(
            select(
                # count all vs count non-dismissed for debugging
                __import__("sqlalchemy").func.count(MallCustomerSkipLog.id)
            )
            .where(MallCustomerSkipLog.customer_user_id == consumer.id)
            .where(MallCustomerSkipLog.salesman_user_id == sm.id)
        )).scalar() or 0)
        non_dismissed = int((await s.execute(
            select(__import__("sqlalchemy").func.count(MallCustomerSkipLog.id))
            .where(MallCustomerSkipLog.customer_user_id == consumer.id)
            .where(MallCustomerSkipLog.salesman_user_id == sm.id)
            .where(MallCustomerSkipLog.dismissed.is_(False))
        )).scalar() or 0)
        print(f"   累计 skip_log={total_logs}（非 dismissed={non_dismissed}）")
        assert non_dismissed == THRESHOLD - 1

    # ── Step 3: 再跳一次 → 非 dismissed 数 = THRESHOLD 正好触发 ──
    async with admin_session_factory() as s:
        o = await s.get(MallOrder, ref_order_id)
        await _record_skip_log(
            s, o, salesman_user_id=sm.id,
            skip_type=MallSkipType.NOT_CLAIMED_IN_TIME.value,
        )
        await s.commit()

    async with admin_session_factory() as s:
        alerts = (await s.execute(
            select(MallSkipAlert)
            .where(MallSkipAlert.customer_user_id == consumer.id)
            .where(MallSkipAlert.salesman_user_id == sm.id)
        )).scalars().all()
        assert len(alerts) == 1, (
            f"第 {THRESHOLD} 次非 dismissed 跳单应触发 alert，"
            f"实际 alert 数={len(alerts)}"
        )
        alert = alerts[0]
        assert alert.status == MallSkipAlertStatus.OPEN.value
        # alert.skip_count 取的是阈值查询时的 cnt
        print(f"③ ✅ 第 {THRESHOLD} 次跳单触发 alert: skip_count={alert.skip_count}, status={alert.status}")
        # 关键断言：skip_count 应等于 THRESHOLD（不含 dismissed 的那条）
        assert alert.skip_count == THRESHOLD, (
            f"skip_count 应 == {THRESHOLD}（排除 dismissed），实际 {alert.skip_count}"
        )
        print(f"   ✅ skip_count={alert.skip_count}，正确排除了 dismissed 的那条")

    # ── 清理：保持测试幂等 ──
    async with admin_session_factory() as s:
        await s.execute(
            delete(MallSkipAlert)
            .where(MallSkipAlert.customer_user_id == consumer.id)
            .where(MallSkipAlert.salesman_user_id == sm.id)
        )
        await s.execute(
            delete(MallCustomerSkipLog)
            .where(MallCustomerSkipLog.customer_user_id == consumer.id)
            .where(MallCustomerSkipLog.salesman_user_id == sm.id)
        )
        await s.commit()
    print("\n✅ dismissed skip_log 阈值排除验证通过，测试数据已清理")


if __name__ == "__main__":
    asyncio.run(main())
