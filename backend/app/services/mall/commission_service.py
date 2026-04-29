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

from sqlalchemy import select
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
    """订单首次结算时写 commission。

    幂等：order.commission_posted=True 时跳过。
    """
    if order.commission_posted:
        return []
    if not order.assigned_salesman_id:
        # 没有配送业务员（理论不会到 confirm_payment；留兜底日志）
        return []

    salesman = (await db.execute(
        select(MallUser).where(MallUser.id == order.assigned_salesman_id)
    )).scalar_one_or_none()
    if salesman is None or not salesman.linked_employee_id:
        # 业务员没有绑 employee，无法入 ERP commission 表
        return []

    # 取订单 items，按 brand_id 分组
    items = (await db.execute(
        select(MallOrderItem).where(MallOrderItem.order_id == order.id)
    )).scalars().all()
    if not items:
        return []

    # 实收 = received_amount；按 item.subtotal / total_amount 切分收入到各 brand
    total_amount = order.total_amount or Decimal("0")
    received = order.received_amount or Decimal("0")
    if total_amount <= 0 or received <= 0:
        return []

    # 按 brand 聚合 items 的 subtotal
    brand_subtotal: dict[Optional[str], Decimal] = {}
    for it in items:
        brand_subtotal[it.brand_id] = (
            brand_subtotal.get(it.brand_id, Decimal("0")) + (it.subtotal or Decimal("0"))
        )

    commissions: list[Commission] = []
    for brand_id, subtotal in brand_subtotal.items():
        if subtotal <= 0:
            continue
        # 按 subtotal 占比切收入
        brand_income = (received * subtotal / total_amount).quantize(Decimal("0.01"))
        rate = await _resolve_commission_rate(
            db, salesman.linked_employee_id, brand_id
        )
        amount = (brand_income * rate).quantize(Decimal("0.01"))
        if amount <= 0:
            continue
        c = Commission(
            employee_id=salesman.linked_employee_id,
            brand_id=brand_id,
            mall_order_id=order.id,
            commission_amount=amount,
            status="pending",
            notes=f"Mall 订单 {order.order_no} · 品牌提成率 {rate}",
        )
        db.add(c)
        commissions.append(c)

    order.commission_posted = True
    await db.flush()
    return commissions
