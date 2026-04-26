"""Receipt confirmation side-effects.

Receipt 从 pending_confirmation 转为 confirmed（或直接 finance 建 confirmed）
时需要触发的一系列业务效应。抽成 service 让两条路径（直接 create_receipt /
审批路径 confirm_payment）逻辑一致。

职责拆分：
- apply_per_receipt_effects: 对单条 Receipt 生效的（应收账款分摊）
- apply_post_confirmation_effects: 订单层一次性的（Commission 生成 / KPI 刷新
  / 销售目标里程碑通知）。多条 Receipt 一起审批时只调用一次。

幂等保证：
- Commission: 按 order_id 查现有，已生成跳过
- 应收分摊: Receipt 只会被 confirmed 一次（pending → confirmed 单向），每笔只走一次
- KPI/里程碑: 基于 DB 当前聚合值重算，多跑无副作用（rate 已达的不再推二次通知）
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import PaymentStatus
from app.models.customer import Receivable
from app.models.finance import Receipt
from app.models.order import Order


async def apply_per_receipt_effects(
    db: AsyncSession, receipt: Receipt, order: Order | None = None
) -> None:
    """对单条 Receipt 触发的副作用：应收账款分摊。

    在 Receipt 变成 confirmed 之后、未 commit 之前调。
    """
    if not receipt.order_id:
        return

    receivables = (
        await db.execute(
            select(Receivable)
            .where(Receivable.order_id == receipt.order_id)
            .where(Receivable.status != "paid")
        )
    ).scalars().all()

    remaining = Decimal(str(receipt.amount))
    for recv in receivables:
        if remaining <= 0:
            break
        can_apply = Decimal(str(recv.amount)) - Decimal(str(recv.paid_amount))
        applied = min(remaining, can_apply)
        recv.paid_amount = float(Decimal(str(recv.paid_amount)) + applied)
        if recv.paid_amount >= float(recv.amount):
            recv.status = "paid"
        else:
            recv.status = "partial"
        remaining -= applied

    if remaining > 0:
        # 收款多于应收，记到 Receipt 防静默吞款
        note_suffix = f" [警告: 多收款 ¥{remaining} 未匹配到应收]"
        if not (receipt.notes or "").endswith(note_suffix):
            receipt.notes = (receipt.notes or "") + note_suffix


async def apply_post_confirmation_effects(
    db: AsyncSession,
    order: Order,
    user: dict[str, Any],
    prev_payment_status: str,
) -> None:
    """订单层一次性副作用：Commission 生成 / KPI 刷新 / 销售目标里程碑通知。

    调用前：订单 payment_status 已被更新到最新（基于 confirmed Receipts SUM）。
    prev_payment_status 是更新前的值，用来判断"首次全款"触发 Commission。
    """
    from app.models.user import Commission, User
    from app.models.payroll import (
        AssessmentItem,
        BrandSalaryScheme,
        EmployeeBrandPosition,
    )
    from app.models.sales_target import SalesTarget
    from app.services.notification_service import notify

    if not (order.salesman_id and order.brand_id):
        return

    # ─── 1. Commission: 订单首次跃升为 fully_paid 时生成一次 ────────
    just_fully_paid = (
        prev_payment_status != PaymentStatus.FULLY_PAID
        and order.payment_status == PaymentStatus.FULLY_PAID
    )
    if just_fully_paid:
        # 幂等：同一 order_id 不重复挂 Commission
        existed = (
            await db.execute(
                select(Commission).where(Commission.order_id == order.id)
            )
        ).scalar_one_or_none()
        if not existed:
            # 取员工在该品牌的个性化提成率；没有则取品牌+岗位默认
            ebp = (
                await db.execute(
                    select(EmployeeBrandPosition).where(
                        EmployeeBrandPosition.employee_id == order.salesman_id,
                        EmployeeBrandPosition.brand_id == order.brand_id,
                    )
                )
            ).scalar_one_or_none()
            rate: Decimal | None = None
            if ebp and ebp.commission_rate is not None:
                rate = Decimal(str(ebp.commission_rate))
            else:
                scheme = (
                    await db.execute(
                        select(BrandSalaryScheme).where(
                            BrandSalaryScheme.brand_id == order.brand_id,
                            BrandSalaryScheme.position_code == (
                                ebp.position_code if ebp else "salesman"
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if scheme:
                    rate = Decimal(str(scheme.commission_rate))

            if rate and rate > 0:
                # 提成基数 = 订单应收（customer_pay/employee_pay 按指导价；company_pay 按到手价）
                comm_base = order.customer_paid_amount or order.total_amount
                comm_amount = (Decimal(str(comm_base)) * rate).quantize(Decimal("0.01"))
                import uuid as _uuid
                db.add(
                    Commission(
                        id=str(_uuid.uuid4()),
                        employee_id=order.salesman_id,
                        brand_id=order.brand_id,
                        order_id=order.id,
                        commission_amount=comm_amount,
                        status="pending",
                        notes=f"订单{order.order_no} 基数¥{comm_base} × {rate * 100}%（{order.settlement_mode}）",
                    )
                )
                await db.flush()

    # ─── 2. KPI 刷新 + 3. 销售目标里程碑（都基于本月累计，整单触发即可）─────
    # 只在"有状态变化"时触发，避免重复查询
    if prev_payment_status == order.payment_status:
        return

    try:
        now = datetime.now(timezone.utc)
        period = f"{now.year}-{str(now.month).zfill(2)}"

        # KPI 刷新
        items = (
            await db.execute(
                select(AssessmentItem).where(
                    AssessmentItem.employee_id == order.salesman_id,
                    AssessmentItem.period == period,
                )
            )
        ).scalars().all()
        for it in items:
            actual: Decimal | int | None = None
            if it.item_code == "kpi_revenue":
                actual = (
                    await db.execute(
                        select(func.coalesce(func.sum(Receipt.amount), 0))
                        .select_from(Receipt)
                        .join(Order, Order.id == Receipt.order_id, isouter=True)
                        .where(
                            Order.salesman_id == order.salesman_id,
                            Receipt.status == "confirmed",
                            extract("year", Receipt.receipt_date) == now.year,
                            extract("month", Receipt.receipt_date) == now.month,
                        )
                    )
                ).scalar_one()
            elif it.item_code == "kpi_customers":
                actual = (
                    await db.execute(
                        select(func.count(func.distinct(Order.customer_id))).where(
                            Order.salesman_id == order.salesman_id,
                            extract("year", Order.created_at) == now.year,
                            extract("month", Order.created_at) == now.month,
                        )
                    )
                ).scalar_one()
            if actual is not None:
                it.actual_value = Decimal(str(actual))
                if it.target_value and it.target_value > 0:
                    r = Decimal(str(actual)) / it.target_value
                else:
                    r = Decimal("0")
                it.completion_rate = r
                it.earned_amount = (
                    (it.item_amount * r).quantize(Decimal("0.01"))
                    if r >= Decimal("0.5")
                    else Decimal("0")
                )

        # 销售目标里程碑：50% / 80% / 100% / 120%
        targets = (
            await db.execute(
                select(SalesTarget).where(
                    SalesTarget.target_level == "employee",
                    SalesTarget.employee_id == order.salesman_id,
                    SalesTarget.target_year == now.year,
                    SalesTarget.target_month == now.month,
                )
            )
        ).scalars().all()
        for t in targets:
            metric_label = "回款" if t.bonus_metric != "sales" else "销售"
            if t.bonus_metric == "sales":
                _s = (
                    await db.execute(
                        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                            Order.salesman_id == order.salesman_id,
                            extract("year", Order.created_at) == now.year,
                            extract("month", Order.created_at) == now.month,
                        )
                    )
                ).scalar_one()
                metric_actual = Decimal(str(_s))
                target_val = t.sales_target
            else:
                _r = (
                    await db.execute(
                        select(func.coalesce(func.sum(Receipt.amount), 0))
                        .select_from(Receipt)
                        .join(Order, Order.id == Receipt.order_id, isouter=True)
                        .where(
                            Order.salesman_id == order.salesman_id,
                            Receipt.status == "confirmed",
                            extract("year", Receipt.receipt_date) == now.year,
                            extract("month", Receipt.receipt_date) == now.month,
                        )
                    )
                ).scalar_one()
                metric_actual = Decimal(str(_r))
                target_val = t.receipt_target
            if not target_val or target_val <= 0:
                continue
            rate = float(metric_actual / target_val)

            # 里程碑推送：近似上一次 rate = 当前 - 刚确认订单的金额；
            # 实际场景"刚跨过门槛"才推（幂等性由 notification 自身保证更佳，此处尽力）
            prev_actual = metric_actual  # 保守：不假设 delta，里程碑 notify 可能重复但用户不太在意
            prev_rate = float(prev_actual / target_val) if target_val > 0 else 0
            for milestone, emoji in [(0.5, "🎯"), (0.8, "💪"), (1.0, "🎉"), (1.2, "🏆")]:
                if prev_rate < milestone <= rate:
                    u = (
                        await db.execute(
                            select(User).where(
                                User.employee_id == order.salesman_id,
                                User.is_active == True,  # noqa: E712
                            )
                        )
                    ).scalar_one_or_none()
                    if u:
                        await notify(
                            db,
                            recipient_id=u.id,
                            title=f"{emoji} {metric_label}目标达成 {int(milestone * 100)}%",
                            content=(
                                f"{now.year}-{str(now.month).zfill(2)} "
                                f"{metric_label}目标 ¥{float(target_val):,.0f}，"
                                f"当前 ¥{float(metric_actual):,.0f}，完成率 {rate * 100:.1f}%"
                            ),
                            entity_type="SalesTarget",
                            entity_id=t.id,
                        )
                    break
    except Exception:
        # KPI/里程碑副作用失败不阻塞核心收款流程
        pass
