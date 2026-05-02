"""
Mall 提成服务。

规则（plan 决策 #5）：
  - 提成归属 order.assigned_salesman_id（配送业务员），不是推荐人
  - 提成率查询顺序：EmployeeBrandPosition → BrandSalaryScheme → settings.MALL_DEFAULT_COMMISSION_RATE
  - 按 order_items.brand_id 分组：一张订单可能产出多条 commission（跨品牌）
  - 基数 = 订单的 received_amount（已收金额），按 items 分品牌时按销售额占比切分
  - 幂等：commission_posted 标记防重复
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mall.order import MallOrder, MallOrderItem
from app.models.mall.user import MallUser
from app.models.payroll import BrandSalaryScheme, EmployeeBrandPosition
from app.models.user import Commission


async def _resolve_commission_rate(
    db: AsyncSession, employee_id: str, brand_id: Optional[str]
) -> Decimal:
    """EmployeeBrandPosition → BrandSalaryScheme(salesman) → 默认。"""
    if brand_id:
        # 1. EmployeeBrandPosition 个性化
        ebp = (await db.execute(
            select(EmployeeBrandPosition)
            .where(EmployeeBrandPosition.employee_id == employee_id)
            .where(EmployeeBrandPosition.brand_id == brand_id)
        )).scalar_one_or_none()
        if ebp and ebp.commission_rate is not None:
            return ebp.commission_rate

        # 2. 品牌默认 salesman 岗位
        scheme = (await db.execute(
            select(BrandSalaryScheme)
            .where(BrandSalaryScheme.brand_id == brand_id)
            .where(BrandSalaryScheme.position_code == "salesman")
        )).scalar_one_or_none()
        if scheme:
            return scheme.commission_rate

    # 3. 兜底默认
    return Decimal(str(settings.MALL_DEFAULT_COMMISSION_RATE))


async def post_commission_for_order(
    db: AsyncSession, order: MallOrder
) -> list[Commission]:
    """订单首次结算 / 补录恢复时写 commission。

    幂等 + 增量补发：
      - 按 received_amount 切分到各 brand 得到目标提成
      - 查本订单已写入的各 brand commission 合计
      - 仅差额 > 0 时追加一条新 commission（首次调用就是全额）

    覆盖以下场景：
      1. 首次全款 confirm_payment → 全额首次入账
      2. partial_closed 时 received>0 → 仅对已收部分计提成
      3. partial_closed 恢复 completed → 对新增部分补提成（旧逻辑会跳过）
    """
    if not order.assigned_salesman_id:
        return []

    salesman = (await db.execute(
        select(MallUser).where(MallUser.id == order.assigned_salesman_id)
    )).scalar_one_or_none()
    if salesman is None or not salesman.linked_employee_id:
        return []

    items = (await db.execute(
        select(MallOrderItem).where(MallOrderItem.order_id == order.id)
    )).scalars().all()
    if not items:
        return []

    total_amount = order.total_amount or Decimal("0")
    received = order.received_amount or Decimal("0")
    if total_amount <= 0 or received <= 0:
        return []

    brand_subtotal: dict[Optional[str], Decimal] = {}
    for it in items:
        brand_subtotal[it.brand_id] = (
            brand_subtotal.get(it.brand_id, Decimal("0")) + (it.subtotal or Decimal("0"))
        )

    # 本订单已写入的各 brand commission 合计（只数 pending+settled；rejected/void 不算）
    existing_rows = (await db.execute(
        select(Commission.brand_id, func.coalesce(func.sum(Commission.commission_amount), 0))
        .where(Commission.mall_order_id == order.id)
        .where(Commission.status.in_(["pending", "settled"]))
        .group_by(Commission.brand_id)
    )).all()
    existing_by_brand: dict[Optional[str], Decimal] = {
        bid: Decimal(str(amt or 0)) for bid, amt in existing_rows
    }

    commissions: list[Commission] = []
    for brand_id, subtotal in brand_subtotal.items():
        if subtotal <= 0:
            continue
        brand_income = (received * subtotal / total_amount).quantize(Decimal("0.01"))
        rate = await _resolve_commission_rate(
            db, salesman.linked_employee_id, brand_id
        )
        target_amount = (brand_income * rate).quantize(Decimal("0.01"))
        already = existing_by_brand.get(brand_id, Decimal("0"))
        delta = (target_amount - already).quantize(Decimal("0.01"))
        if delta <= 0:
            continue
        c = Commission(
            employee_id=salesman.linked_employee_id,
            brand_id=brand_id,
            mall_order_id=order.id,
            commission_amount=delta,
            status="pending",
            notes=(
                f"Mall 订单 {order.order_no} · 品牌提成率 {rate} · "
                f"{'补发差额' if already > 0 else '首次入账'}"
            ),
        )
        db.add(c)
        commissions.append(c)

    # commission_posted 标记保留语义：True 表示本订单至少发过一笔提成
    if commissions:
        order.commission_posted = True
    await db.flush()
    return commissions
