"""月度 KPI 快照服务（决策 #2 月榜快照 vs 实时双显）。

核心逻辑：
  - `build_snapshot_for_month(year, month)` → 计算该月每个业务员的 GMV / 订单数 / 提成
    并写入 mall_monthly_kpi_snapshot（UniqueConstraint(employee_id, period) 防重复）
  - 定时任务 `job_build_last_month_snapshot` 每月 1 号凌晨跑一次上月
  - 手工回补：调用 build_snapshot_for_month(YYYY, MM) 即可；既有行会走 ON CONFLICT DO UPDATE 覆盖

口径（和 dashboard_summary 的 salesman_rank 对齐）：
  - 订单纳入：status IN ('completed', 'partial_closed')
    * completed → 按 completed_at 时间归档
    * partial_closed → 按 delivered_at 时间归档（折损日在下月不影响"交付月"归属）
  - refunded 订单不纳入快照（和实时查询一致）
  - GMV = received_amount（三种结算模式下的公司应收已写入此字段）
  - Commission = 当月内 Commission.created_at 落在 [month_start, month_end) 的所有 commission_amount 求和
    （含 is_adjustment 负数调整，以便 snapshot 反映"月底结清后的真实净提成"）

幂等：UniqueConstraint 保证同 (employee, period) 只有一行；重跑会 UPSERT。
"""
import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import admin_session_factory
from app.models.mall.base import MallOrderStatus
from app.models.mall.kpi_snapshot import MallMonthlyKpiSnapshot
from app.models.mall.order import MallOrder
from app.models.mall.user import MallUser
from app.models.user import Commission, Employee

logger = logging.getLogger(__name__)


def _period_bounds(year: int, month: int) -> tuple[str, datetime, datetime]:
    period = f"{year:04d}-{month:02d}"
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return period, start, end


async def build_snapshot_for_month(
    db: AsyncSession,
    year: int,
    month: int,
    notes: Optional[str] = None,
) -> dict:
    """计算某月全部业务员的 KPI 并 UPSERT 到 mall_monthly_kpi_snapshot。

    返回 {period, salesmen_count, upserted}。
    """
    period, month_start, month_end = _period_bounds(year, month)

    # 1. GMV + 订单数（按 assigned_salesman_id 聚合）
    #    completed 看 completed_at，partial_closed 看 delivered_at
    rank_rows = (await db.execute(
        select(
            MallOrder.assigned_salesman_id,
            func.count(MallOrder.id).label("order_count"),
            func.coalesce(func.sum(MallOrder.received_amount), 0).label("gmv"),
        )
        .where(MallOrder.assigned_salesman_id.isnot(None))
        .where(or_(
            and_(
                MallOrder.status == MallOrderStatus.COMPLETED.value,
                MallOrder.completed_at >= month_start,
                MallOrder.completed_at < month_end,
            ),
            and_(
                MallOrder.status == MallOrderStatus.PARTIAL_CLOSED.value,
                MallOrder.delivered_at >= month_start,
                MallOrder.delivered_at < month_end,
            ),
        ))
        .group_by(MallOrder.assigned_salesman_id)
    )).all()

    if not rank_rows:
        logger.info("[kpi_snapshot] %s 无业务员 KPI 数据，跳过", period)
        return {"period": period, "salesmen_count": 0, "upserted": 0}

    # 2. salesman_id → linked_employee_id 映射（只保留有 linked_employee_id 的业务员）
    sm_ids = [r[0] for r in rank_rows]
    sms = (await db.execute(
        select(MallUser).where(MallUser.id.in_(sm_ids))
    )).scalars().all()
    sm_to_employee = {
        s.id: s.linked_employee_id
        for s in sms
        if s.linked_employee_id
    }

    # 3. 当月 commission（按 employee_id 聚合），含 is_adjustment 负数追回
    #    使用 Commission.created_at 作为归属时间（adjustment 的 created_at = 退货 approve 时间）
    comm_rows = (await db.execute(
        select(
            Commission.employee_id,
            func.coalesce(func.sum(Commission.commission_amount), 0).label("comm"),
        )
        .where(Commission.employee_id.in_(list(sm_to_employee.values())))
        .where(Commission.created_at >= month_start)
        .where(Commission.created_at < month_end)
        .group_by(Commission.employee_id)
    )).all()
    comm_by_emp = {eid: amt for eid, amt in comm_rows}

    # 4. UPSERT 每行
    upserted = 0
    for sm_id, order_count, gmv in rank_rows:
        emp_id = sm_to_employee.get(sm_id)
        if not emp_id:
            # 未绑 employee 的业务员（理论上不该存在）跳过
            continue
        commission = comm_by_emp.get(emp_id, Decimal("0"))
        stmt = pg_insert(MallMonthlyKpiSnapshot).values(
            id=str(_uuid.uuid4()),
            employee_id=emp_id,
            period=period,
            gmv=gmv,
            order_count=order_count,
            commission_amount=commission,
            notes=notes,
        ).on_conflict_do_update(
            constraint="uq_mall_kpi_snap_emp_period",
            set_={
                "gmv": gmv,
                "order_count": order_count,
                "commission_amount": commission,
                "snapshot_at": func.now(),
                "notes": notes,
            },
        )
        await db.execute(stmt)
        upserted += 1

    await db.flush()
    logger.info(
        "[kpi_snapshot] %s 冻结完毕：%d 业务员 UPSERT",
        period, upserted,
    )
    return {"period": period, "salesmen_count": len(rank_rows), "upserted": upserted}


async def job_build_last_month_snapshot() -> dict:
    """定时任务入口：每月 1 号凌晨跑上月快照。"""
    now = datetime.now(timezone.utc)
    # 上月 = 今天减 1 天，找到的月份
    last_day_of_prev_month = now.replace(day=1) - timedelta(days=1)
    y, m = last_day_of_prev_month.year, last_day_of_prev_month.month
    async with admin_session_factory() as s:
        result = await build_snapshot_for_month(
            s, y, m,
            notes=f"定时任务 {now.strftime('%Y-%m-%d %H:%M')}",
        )
        await s.commit()
    return result
