"""
Mall 订单服务（M3 范围：预览 / 建单 / 列表 / 详情 / 取消 / 确认收货）。

M4 再补：抢单池 / claim/release/ship/deliver / upload_voucher / confirm_payment /
profit/commission 回写 / partial_close。
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mall.base import (
    MallClaimAction,
    MallOrderStatus,
    MallSkipAlertStatus,
    MallSkipType,
    MallUserType,
)
from app.models.mall.inventory import MallInventory
from app.models.mall.order import (
    MallCartItem,
    MallCustomerSkipLog,
    MallOrder,
    MallOrderClaimLog,
    MallOrderItem,
    MallSkipAlert,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallAddress, MallUser
from app.services.mall.inventory_service import (
    deduct_for_order,
    get_default_warehouse,
    restock_for_cancel,
)


# =============================================================================
# 订单号生成
# =============================================================================

def _generate_order_no() -> str:
    """MO + yyyymmdd + uuid4 前 8 位 = 总 22 位，冲突概率可忽略。"""
    now = datetime.now(timezone.utc)
    return f"MO{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"


# =============================================================================
# 预览：根据 skuId + quantity 列表算金额
# =============================================================================

async def preview_order(
    db: AsyncSession,
    user: MallUser,
    items: list[dict],
    address_id: Optional[str] = None,
) -> dict:
    """预览订单金额。

    items: [{sku_id, quantity}, ...]
    返回：{items: [...], total_amount, shipping_fee, discount_amount, pay_amount, address}
    """
    # 价格可见规则：consumer 必须已绑定推荐人；salesman 永远可见
    if user.user_type != "salesman" and not user.referrer_salesman_id:
        raise HTTPException(
            status_code=403,
            detail="请先联系业务员获取邀请码绑定推荐人后再下单",
        )
    if not items:
        raise HTTPException(status_code=400, detail="购物清单为空")

    detailed_items: list[dict] = []
    total_amount = Decimal("0")

    for it in items:
        sku_id = int(it["sku_id"])
        qty = int(it["quantity"])
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"SKU {sku_id} 数量必须大于 0")

        sku = (
            await db.execute(select(MallProductSku).where(MallProductSku.id == sku_id))
        ).scalar_one_or_none()
        if sku is None or sku.status != "active":
            raise HTTPException(status_code=404, detail=f"SKU {sku_id} 不存在或已下架")

        prod = (
            await db.execute(select(MallProduct).where(MallProduct.id == sku.product_id))
        ).scalar_one_or_none()
        if prod is None:
            raise HTTPException(status_code=404, detail=f"商品 {sku.product_id} 不存在")

        subtotal = (sku.price * qty).quantize(Decimal("0.01"))
        total_amount += subtotal
        detailed_items.append({
            "sku_id": sku_id,
            "product_id": prod.id,
            "product_name": prod.name,
            "sku_name": sku.spec,
            "price": sku.price,
            "quantity": qty,
            "subtotal": subtotal,
            "pic": sku.image or prod.main_image,
            "brand_id": prod.brand_id,
        })

    shipping_fee = Decimal("0")  # M3 不做运费，M5 管理后台可配
    discount_amount = Decimal("0")
    pay_amount = total_amount + shipping_fee - discount_amount

    address_data = None
    if address_id:
        addr = (
            await db.execute(
                select(MallAddress)
                .where(MallAddress.id == address_id)
                .where(MallAddress.user_id == user.id)
            )
        ).scalar_one_or_none()
        if addr is None:
            raise HTTPException(status_code=404, detail="地址不存在或不属于当前用户")
        address_data = _address_snapshot(addr)

    return {
        "items": detailed_items,
        "total_amount": total_amount,
        "shipping_fee": shipping_fee,
        "discount_amount": discount_amount,
        "pay_amount": pay_amount,
        "address": address_data,
    }


# =============================================================================
# 地址快照
# =============================================================================

def _address_snapshot(addr: MallAddress) -> dict[str, Any]:
    return {
        "id": addr.id,
        "receiver": addr.receiver,
        "mobile": addr.mobile,
        "province_code": addr.province_code,
        "city_code": addr.city_code,
        "area_code": addr.area_code,
        "province": addr.province,
        "city": addr.city,
        "area": addr.area,
        "addr": addr.addr,
    }


# =============================================================================
# 创建订单
# =============================================================================

async def create_order(
    db: AsyncSession,
    user: MallUser,
    *,
    items: list[dict],
    address_id: str,
    remarks: Optional[str] = None,
) -> MallOrder:
    """事务内：校验地址 → 扣库存 → 固化 referrer/cost_price → 写订单 + 订单项 → 清购物车。"""
    # 价格可见 = 下单资格：consumer 必须已绑推荐人；salesman 无限制（允许业务员给自己下单）
    if user.user_type != "salesman" and not user.referrer_salesman_id:
        raise HTTPException(
            status_code=403,
            detail="请先联系业务员获取邀请码绑定推荐人后再下单",
        )
    if not items:
        raise HTTPException(status_code=400, detail="购物清单为空")

    # 1. 校验地址
    addr = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.id == address_id)
            .where(MallAddress.user_id == user.id)
        )
    ).scalar_one_or_none()
    if addr is None:
        raise HTTPException(status_code=404, detail="地址不存在或不属于当前用户")

    # 2. 找默认仓（M3 简化：一个订单从同一个仓扣）
    warehouse = await get_default_warehouse(db)
    if warehouse is None:
        raise HTTPException(status_code=503, detail="未配置可用仓库，无法下单")

    # 3. 建 Order 主记录（先拿到 order.id，用于 flow ref）
    order = MallOrder(
        order_no=_generate_order_no(),
        user_id=user.id,
        address_snapshot=_address_snapshot(addr),
        # 下单瞬间固化 referrer（之后换绑推荐人不影响历史订单归属）
        referrer_salesman_id=user.referrer_salesman_id,
        assigned_salesman_id=None,
        status=MallOrderStatus.PENDING_ASSIGNMENT.value,
        payment_status="unpaid",
        total_amount=Decimal("0"),  # 循环累加后再回填
        shipping_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        pay_amount=Decimal("0"),
        remarks=remarks,
    )
    db.add(order)
    await db.flush()  # 拿 id

    # 4. 循环扣库存 + 建 item
    total_amount = Decimal("0")
    sku_ids_to_clear: list[int] = []

    for it in items:
        sku_id = int(it["sku_id"])
        qty = int(it["quantity"])
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"SKU {sku_id} 数量必须大于 0")

        sku = (
            await db.execute(select(MallProductSku).where(MallProductSku.id == sku_id))
        ).scalar_one_or_none()
        if sku is None or sku.status != "active":
            raise HTTPException(status_code=404, detail=f"SKU {sku_id} 不存在或已下架")

        prod = (
            await db.execute(select(MallProduct).where(MallProduct.id == sku.product_id))
        ).scalar_one_or_none()

        # 扣库存（FOR UPDATE，带 CHECK 兜底）
        cost_snapshot = await deduct_for_order(
            db,
            warehouse_id=warehouse.id,
            sku_id=sku_id,
            quantity=qty,
            order_id=order.id,
        )

        subtotal = (sku.price * qty).quantize(Decimal("0.01"))
        total_amount += subtotal

        item = MallOrderItem(
            order_id=order.id,
            product_id=prod.id,
            sku_id=sku_id,
            brand_id=prod.brand_id,
            sku_snapshot={
                "product_id": prod.id,
                "product_name": prod.name,
                "sku_name": sku.spec,
                "pic": sku.image or prod.main_image,
                "barcode": sku.barcode,
            },
            price=sku.price,
            quantity=qty,
            subtotal=subtotal,
            # 纯商城 SKU 可能 cost_price = None，用 inventory.avg 作为快照；
            # avg 也 None 时（第一次入库前）保持 None，M4 确认收款前必须回填
            cost_price_snapshot=cost_snapshot if cost_snapshot is not None else sku.cost_price,
        )
        db.add(item)
        sku_ids_to_clear.append(sku_id)

    # 5. 回填订单金额
    order.total_amount = total_amount
    order.pay_amount = total_amount  # M3 无运费/折扣

    # 6. 清购物车对应 SKU
    if sku_ids_to_clear:
        from sqlalchemy import delete
        await db.execute(
            delete(MallCartItem)
            .where(MallCartItem.user_id == user.id)
            .where(MallCartItem.sku_id.in_(sku_ids_to_clear))
        )

    # 注意：user.last_order_at 不在下单时更新，移到 confirm_payment 里（订单真正完成才算活跃）
    await db.flush()
    return order


# =============================================================================
# 列表 / 详情
# =============================================================================

async def list_my_orders(
    db: AsyncSession,
    user: MallUser,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[MallOrder], int]:
    from sqlalchemy import desc, func

    stmt = select(MallOrder).where(MallOrder.user_id == user.id)
    if status_filter:
        stmt = stmt.where(MallOrder.status == status_filter)
    stmt = stmt.order_by(desc(MallOrder.created_at))

    total = int((
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return list(rows), total


async def get_my_order(
    db: AsyncSession, user: MallUser, order_no: str
) -> MallOrder:
    order = (
        await db.execute(
            select(MallOrder)
            .where(MallOrder.order_no == order_no)
            .where(MallOrder.user_id == user.id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


async def get_order_items(
    db: AsyncSession, order_id: str
) -> list[MallOrderItem]:
    return list((
        await db.execute(
            select(MallOrderItem)
            .where(MallOrderItem.order_id == order_id)
            .order_by(MallOrderItem.created_at)
        )
    ).scalars())


# =============================================================================
# 取消 / 确认收货
# =============================================================================

async def cancel_order(
    db: AsyncSession,
    user: MallUser,
    order_no: str,
    reason: Optional[str] = None,
) -> MallOrder:
    """C 端取消订单。只有 pending_assignment 状态（还没业务员接单）可自取消。

    退回库存；FOR UPDATE 锁 order 防并发抢单时 cancel 撞车。
    """
    # 先用 FOR UPDATE 锁定本单（加 user_id 过滤，防越权）
    order = (
        await db.execute(
            select(MallOrder)
            .where(MallOrder.order_no == order_no)
            .where(MallOrder.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status != MallOrderStatus.PENDING_ASSIGNMENT.value:
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可取消（仅待接单可取消）",
        )

    # 退回库存
    warehouse = await get_default_warehouse(db)
    if warehouse is None:
        raise HTTPException(status_code=500, detail="未找到仓库，无法退回库存")

    items = await get_order_items(db, order.id)
    for it in items:
        await restock_for_cancel(
            db,
            warehouse_id=warehouse.id,
            sku_id=it.sku_id,
            quantity=it.quantity,
            order_id=order.id,
            cost_price=it.cost_price_snapshot,
        )

    order.status = MallOrderStatus.CANCELLED.value
    order.cancellation_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)
    await db.flush()
    # 通知 referrer：您推荐的客户取消了订单
    if order.referrer_salesman_id:
        from app.services.notification_service import notify_mall_user
        await notify_mall_user(
            db, mall_user_id=order.referrer_salesman_id,
            title="客户取消订单",
            content=f"订单 {order.order_no} 已被客户取消。",
            entity_type="MallOrder", entity_id=order.id,
        )
        await db.flush()
    return order


async def confirm_receipt(
    db: AsyncSession, user: MallUser, order_no: str
) -> MallOrder:
    """C 端"确认收货"。

    注意：订单状态流转真正由 业务员送达 → 业务员传凭证 → 财务确认收款 驱动，
    用户端确认收货本身**不改变订单状态**（避免和业务员流程冲突），仅作为用户行为
    记录。M4 可加 customer_confirmed_at 字段。M3 版只要求处于 delivered 状态。
    """
    order = await get_my_order(db, user, order_no)
    if order.status != MallOrderStatus.DELIVERED.value:
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可确认收货",
        )
    # M3：不改状态，仅允许调用通过；后续增加 customer_confirmed_at 字段时再写入
    return order


# =============================================================================
# 订单统计（orderCount）
# =============================================================================

async def order_stats(db: AsyncSession, user: MallUser) -> dict[str, int]:
    """对齐 mall4j /p/myOrder/orderCount：
    { unPay, payed, consignment, unComment } 四个计数。

    C 端视角（小程序第一版线下收款，付款发生在业务员送达时）：
      unPay       = 尚未送达收款的所有订单（下单/接单/出库/送达/财务确认中）
      payed       = 已全款确认 → completed
      consignment = 配送中（已出库未送达）
      unComment   = 已评价功能 M5 再做
    """
    from sqlalchemy import func

    async def _count(*statuses: str) -> int:
        return int((
            await db.execute(
                select(func.count(MallOrder.id))
                .where(MallOrder.user_id == user.id)
                .where(MallOrder.status.in_(statuses))
            )
        ).scalar() or 0)

    return {
        "unPay": await _count(
            MallOrderStatus.PENDING_ASSIGNMENT.value,
            MallOrderStatus.ASSIGNED.value,
            MallOrderStatus.SHIPPED.value,
            MallOrderStatus.DELIVERED.value,
            MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        ),
        "payed": await _count(MallOrderStatus.COMPLETED.value),
        "consignment": await _count(MallOrderStatus.SHIPPED.value),
        "unComment": 0,
    }


# =============================================================================
# 抢单池 / claim / release / admin reassign
# =============================================================================

def unclaim_timeout_cutoff() -> datetime:
    """独占期 cutoff = now - MALL_UNCLAIMED_TIMEOUT_MINUTES."""
    return datetime.now(timezone.utc) - timedelta(
        minutes=settings.MALL_UNCLAIMED_TIMEOUT_MINUTES
    )


# 兼容老调用（内部代码仍可能用旧名）
_unclaim_timeout_cutoff = unclaim_timeout_cutoff


async def list_order_pool(
    db: AsyncSession,
    salesman: MallUser,
    scope: str = "my",
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[MallOrder], int]:
    """抢单池查询。

    scope='my'     → referrer==salesman 且在独占期内（created_at > cutoff）
    scope='public' → 已过独占期的所有 pending_assignment（任何业务员可抢）
    """
    if salesman.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=403, detail="仅业务员可查询接单池")

    base = select(MallOrder).where(
        MallOrder.status == MallOrderStatus.PENDING_ASSIGNMENT.value
    )
    cutoff = _unclaim_timeout_cutoff()

    if scope == "my":
        stmt = base.where(MallOrder.referrer_salesman_id == salesman.id).where(
            MallOrder.created_at > cutoff
        )
    elif scope == "public":
        stmt = base.where(MallOrder.created_at <= cutoff)
    else:
        raise HTTPException(status_code=400, detail="scope 只能是 my / public")

    stmt = stmt.order_by(desc(MallOrder.created_at))
    total = int((
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return list(rows), total


async def _require_order_for_claim(
    db: AsyncSession, order_id: str
) -> MallOrder:
    """用 FOR UPDATE 锁订单，防并发抢。"""
    order = (
        await db.execute(
            select(MallOrder).where(MallOrder.id == order_id).with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


async def claim_order(
    db: AsyncSession, salesman: MallUser, order_id: str
) -> MallOrder:
    """业务员抢单。"""
    if salesman.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=403, detail="仅业务员可抢单")

    order = await _require_order_for_claim(db, order_id)
    if order.status != MallOrderStatus.PENDING_ASSIGNMENT.value:
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status}，不可抢",
        )

    # 独占期内，非推荐人不可抢
    cutoff = _unclaim_timeout_cutoff()
    in_exclusive = order.created_at > cutoff
    if in_exclusive and order.referrer_salesman_id and order.referrer_salesman_id != salesman.id:
        raise HTTPException(
            status_code=403,
            detail="订单仍在推荐人独占期，请稍后再抢",
        )

    now = datetime.now(timezone.utc)
    order.assigned_salesman_id = salesman.id
    order.status = MallOrderStatus.ASSIGNED.value
    order.claimed_at = now

    db.add(MallOrderClaimLog(
        order_id=order.id,
        action=MallClaimAction.CLAIM.value,
        from_salesman_id=None,
        to_salesman_id=salesman.id,
        operator_id=salesman.id,
        operator_type="mall_user",
    ))

    # 通知 consumer：已有业务员接单
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db,
        mall_user_id=order.user_id,
        title="已有业务员接单",
        content=f"您的订单 {order.order_no} 已由业务员接单，稍后会联系您安排送货。",
        entity_type="MallOrder",
        entity_id=order.id,
    )
    await db.flush()
    return order


async def release_order(
    db: AsyncSession, salesman: MallUser, order_id: str, reason: Optional[str] = None
) -> MallOrder:
    """业务员主动释放。订单回到 pending_assignment，若原业务员是推荐人则记 skip_log。"""
    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能释放自己接的订单")
    if order.status not in (MallOrderStatus.ASSIGNED.value, MallOrderStatus.SHIPPED.value):
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不可释放",
        )

    prev_salesman = order.assigned_salesman_id
    order.assigned_salesman_id = None
    order.status = MallOrderStatus.PENDING_ASSIGNMENT.value
    order.claimed_at = None

    db.add(MallOrderClaimLog(
        order_id=order.id,
        action=MallClaimAction.RELEASE.value,
        from_salesman_id=prev_salesman,
        to_salesman_id=None,
        operator_id=salesman.id,
        operator_type="mall_user",
        reason=reason,
    ))

    # 如果释放人是推荐人，对该客户记一条 skip_log
    if order.referrer_salesman_id == prev_salesman:
        await _record_skip_log(
            db, order, prev_salesman, MallSkipType.RELEASED.value
        )

    await db.flush()
    return order


async def admin_reassign(
    db: AsyncSession,
    order_id: str,
    target_salesman_id: str,
    operator_erp_user_id: str,
    reason: Optional[str] = None,
) -> MallOrder:
    """管理员强制改派。"""
    target = (
        await db.execute(select(MallUser).where(MallUser.id == target_salesman_id))
    ).scalar_one_or_none()
    if target is None or target.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=400, detail="目标不是业务员")
    if target.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"目标业务员状态 {target.status}，无法改派",
        )
    if not target.is_accepting_orders:
        raise HTTPException(
            status_code=400,
            detail="目标业务员已关闭接单开关",
        )
    if not target.linked_employee_id:
        raise HTTPException(
            status_code=400,
            detail="目标业务员未绑定 ERP 员工，改派后无法生成提成",
        )

    order = await _require_order_for_claim(db, order_id)
    if order.status in (
        MallOrderStatus.COMPLETED.value,
        MallOrderStatus.CANCELLED.value,
        MallOrderStatus.REFUNDED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不可改派",
        )

    prev_salesman = order.assigned_salesman_id
    order.assigned_salesman_id = target.id
    now = datetime.now(timezone.utc)
    if order.status == MallOrderStatus.PENDING_ASSIGNMENT.value:
        order.status = MallOrderStatus.ASSIGNED.value
    # 不管从 pending 还是 assigned 改派，都以当前时刻作为新业务员的接单时间
    order.claimed_at = now

    db.add(MallOrderClaimLog(
        order_id=order.id,
        action=MallClaimAction.ADMIN_ASSIGN.value if prev_salesman is None else MallClaimAction.REASSIGN.value,
        from_salesman_id=prev_salesman,
        to_salesman_id=target.id,
        operator_id=operator_erp_user_id,
        operator_type="erp_user",
        reason=reason,
    ))

    # 管理员改派 → 原业务员记 skip_log（如果是推荐人）
    if prev_salesman and order.referrer_salesman_id == prev_salesman:
        await _record_skip_log(
            db, order, prev_salesman, MallSkipType.ADMIN_REASSIGNED.value
        )

    # 通知新业务员接单 + 旧业务员订单被改派
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db, mall_user_id=target.id,
        title="管理员派单",
        content=f"订单 {order.order_no} 已派给您，请尽快履约。",
        entity_type="MallOrder", entity_id=order.id,
    )
    if prev_salesman and prev_salesman != target.id:
        await notify_mall_user(
            db, mall_user_id=prev_salesman,
            title="订单已被改派",
            content=f"订单 {order.order_no} 已由管理员改派给其他业务员。",
            entity_type="MallOrder", entity_id=order.id,
        )

    await db.flush()
    return order


# =============================================================================
# 跳单日志 + 聚合告警
# =============================================================================

async def _record_skip_log(
    db: AsyncSession, order: MallOrder, salesman_user_id: str, skip_type: str
) -> MallCustomerSkipLog:
    """写一条 skip_log；然后检查 30 天内累计次数，达阈值触发 skip_alert。"""
    log = MallCustomerSkipLog(
        customer_user_id=order.user_id,
        salesman_user_id=salesman_user_id,
        order_id=order.id,
        skip_type=skip_type,
    )
    db.add(log)
    await db.flush()

    # 聚合判定：30 天窗口内 (customer, salesman) 非 dismissed 的条数
    window_start = datetime.now(timezone.utc) - timedelta(
        days=settings.MALL_SKIP_ALERT_WINDOW_DAYS
    )
    cnt = int((
        await db.execute(
            select(func.count(MallCustomerSkipLog.id))
            .where(MallCustomerSkipLog.customer_user_id == order.user_id)
            .where(MallCustomerSkipLog.salesman_user_id == salesman_user_id)
            .where(MallCustomerSkipLog.dismissed.is_(False))
            .where(MallCustomerSkipLog.created_at >= window_start)
        )
    ).scalar() or 0)

    if cnt >= settings.MALL_SKIP_ALERT_THRESHOLD:
        existing_open = (await db.execute(
            select(MallSkipAlert)
            .where(MallSkipAlert.customer_user_id == order.user_id)
            .where(MallSkipAlert.salesman_user_id == salesman_user_id)
            .where(MallSkipAlert.status == MallSkipAlertStatus.OPEN.value)
        )).scalar_one_or_none()
        if existing_open is None:
            log_ids = (await db.execute(
                select(MallCustomerSkipLog.id)
                .where(MallCustomerSkipLog.customer_user_id == order.user_id)
                .where(MallCustomerSkipLog.salesman_user_id == salesman_user_id)
                .where(MallCustomerSkipLog.dismissed.is_(False))
                .where(MallCustomerSkipLog.created_at >= window_start)
            )).scalars().all()
            # 用 SAVEPOINT 包 alert 写入，partial unique index 冲突时只回滚这一段，
            # 不影响外层的 release_order / reassign 主流程
            try:
                async with db.begin_nested():
                    db.add(MallSkipAlert(
                        customer_user_id=order.user_id,
                        salesman_user_id=salesman_user_id,
                        skip_count=cnt,
                        trigger_log_ids=list(log_ids),
                        status=MallSkipAlertStatus.OPEN.value,
                    ))
                # alert 创建成功 → 通知业务员
                from app.services.notification_service import notify_mall_user
                await notify_mall_user(
                    db, mall_user_id=salesman_user_id,
                    title="跳单告警",
                    content=(
                        f"针对您的同一客户近 {settings.MALL_SKIP_ALERT_WINDOW_DAYS} 天"
                        f"累计 {cnt} 次跳单，已生成告警。如有异议可在 App 内申诉。"
                    ),
                    entity_type="MallSkipAlert",
                )
            except Exception as e:
                from sqlalchemy.exc import IntegrityError
                if not isinstance(e, IntegrityError):
                    raise
                # 并发下已有 open alert，忽略

    return log


# =============================================================================
# 定时任务：扫描超时未接单 → 记 skip_log（但不改订单状态）
# =============================================================================

async def detect_unclaimed_timeout(db: AsyncSession) -> int:
    """定时任务调用。找出 pending_assignment 且超过独占期、且推荐人还没被记
    not_claimed_in_time 的订单，给推荐人记一条 skip_log。

    返回处理的订单数。
    """
    cutoff = _unclaim_timeout_cutoff()
    candidates = (await db.execute(
        select(MallOrder)
        .where(MallOrder.status == MallOrderStatus.PENDING_ASSIGNMENT.value)
        .where(MallOrder.created_at <= cutoff)
        .where(MallOrder.referrer_salesman_id.is_not(None))
    )).scalars().all()

    handled = 0
    for order in candidates:
        # 幂等：该订单对 referrer 已有任何类型 skip_log 就跳过，避免同一订单一边被
        # release 一边又被 timeout 算两次
        already = (await db.execute(
            select(MallCustomerSkipLog.id)
            .where(MallCustomerSkipLog.order_id == order.id)
            .where(MallCustomerSkipLog.salesman_user_id == order.referrer_salesman_id)
        )).first()
        if already:
            continue
        await _record_skip_log(
            db, order, order.referrer_salesman_id, MallSkipType.NOT_CLAIMED_IN_TIME.value
        )
        handled += 1
    return handled


async def list_skip_alerts_for_salesman(
    db: AsyncSession,
    salesman_id: str,
    status_filter: Optional[str] = None,
) -> list[MallSkipAlert]:
    stmt = select(MallSkipAlert).where(MallSkipAlert.salesman_user_id == salesman_id)
    if status_filter:
        stmt = stmt.where(MallSkipAlert.status == status_filter)
    stmt = stmt.order_by(desc(MallSkipAlert.created_at))
    return list((await db.execute(stmt)).scalars())


async def appeal_skip_alert(
    db: AsyncSession, salesman: MallUser, alert_id: str, reason: str
) -> MallSkipAlert:
    alert = (await db.execute(
        select(MallSkipAlert).where(MallSkipAlert.id == alert_id).with_for_update()
    )).scalar_one_or_none()
    if alert is None or alert.salesman_user_id != salesman.id:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.status != MallSkipAlertStatus.OPEN.value:
        raise HTTPException(status_code=409, detail="告警已处理")
    alert.appeal_reason = reason
    alert.appeal_at = datetime.now(timezone.utc)
    await db.flush()
    return alert


async def resolve_skip_alert(
    db: AsyncSession,
    alert_id: str,
    operator_id: str,
    operator_type: str,
    resolution_status: str,  # resolved / dismissed
    note: Optional[str] = None,
) -> MallSkipAlert:
    """管理员处理告警。dismissed=True 时把关联 skip_logs 标 dismissed 不计入后续阈值。"""
    if resolution_status not in (
        MallSkipAlertStatus.RESOLVED.value, MallSkipAlertStatus.DISMISSED.value
    ):
        raise HTTPException(status_code=400, detail="处理状态非法")

    alert = (await db.execute(
        select(MallSkipAlert).where(MallSkipAlert.id == alert_id).with_for_update()
    )).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.status != MallSkipAlertStatus.OPEN.value:
        raise HTTPException(status_code=409, detail="告警已处理")

    alert.status = resolution_status
    alert.resolved_by_user_id = operator_id
    alert.resolved_by_type = operator_type
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolution_note = note

    # 驳回告警 → 对应 skip_logs 标 dismissed
    if resolution_status == MallSkipAlertStatus.DISMISSED.value and alert.trigger_log_ids:
        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(MallCustomerSkipLog)
            .where(MallCustomerSkipLog.id.in_(alert.trigger_log_ids))
            .values(dismissed=True)
        )

    await db.flush()
    return alert


# =============================================================================
# ship / deliver / upload_payment_voucher（业务员履约）
# =============================================================================

async def ship_order(
    db: AsyncSession,
    salesman: MallUser,
    order_id: str,
    warehouse_id: Optional[str] = None,
) -> MallOrder:
    """业务员标记出库。assigned → shipped。"""
    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能操作自己接的订单")
    if order.status != MallOrderStatus.ASSIGNED.value:
        raise HTTPException(status_code=409, detail=f"订单状态 {order.status} 不可出库")

    from app.models.mall.order import MallShipment
    ship = (await db.execute(
        select(MallShipment).where(MallShipment.order_id == order.id)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if ship is None:
        ship = MallShipment(
            order_id=order.id,
            warehouse_id=warehouse_id,
            status="shipped",
            shipped_at=now,
        )
        db.add(ship)
    else:
        ship.warehouse_id = warehouse_id
        ship.status = "shipped"
        ship.shipped_at = now

    order.status = MallOrderStatus.SHIPPED.value
    order.shipped_at = now
    await db.flush()
    return order


async def deliver_order(
    db: AsyncSession,
    salesman: MallUser,
    order_id: str,
    delivery_photos: list[dict],  # [{url, sha256, size}]
    request_ip: Optional[str] = None,
    request_ua: Optional[str] = None,
) -> MallOrder:
    """业务员标记已送达，必须上传至少一张送达照片（sha256 入库防篡改）。"""
    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能操作自己接的订单")
    if order.status != MallOrderStatus.SHIPPED.value:
        raise HTTPException(status_code=409, detail=f"订单状态 {order.status} 不可标记送达")
    if not delivery_photos:
        raise HTTPException(status_code=400, detail="请至少上传一张送达照片")

    from app.models.mall.base import MallAttachmentType
    from app.models.mall.order import MallAttachment, MallShipment

    for ph in delivery_photos:
        if not ph.get("url") or not ph.get("sha256"):
            raise HTTPException(status_code=400, detail="送达照片缺少 url/sha256")
        # 拒绝非本服务器上传的 URL（必须先走 /api/mall/salesman/attachments/upload）
        if not ph["url"].startswith("/api/uploads/files/mall/"):
            raise HTTPException(
                status_code=400, detail="送达照片 URL 非法，请通过附件上传端点获取",
            )
        db.add(MallAttachment(
            kind=MallAttachmentType.DELIVERY_PHOTO.value,
            ref_type="order",
            ref_id=order.id,
            file_url=ph["url"],
            sha256=ph["sha256"],
            file_size=int(ph.get("size") or 0),
            mime_type=ph.get("mime_type"),
            uploaded_by_user_id=salesman.id,
            client_ip=request_ip,
            uploaded_user_agent=(request_ua or "")[:500] or None,
        ))

    ship = (await db.execute(
        select(MallShipment).where(MallShipment.order_id == order.id)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if ship is None:
        ship = MallShipment(order_id=order.id, status="delivered", delivered_at=now)
        db.add(ship)
    else:
        ship.status = "delivered"
        ship.delivered_at = now

    order.status = MallOrderStatus.DELIVERED.value
    order.delivered_at = now

    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db,
        mall_user_id=order.user_id,
        title="订单已送达",
        content=f"订单 {order.order_no} 已送达，请确认收货并支付款项。",
        entity_type="MallOrder",
        entity_id=order.id,
    )
    await db.flush()
    return order


async def upload_payment_voucher(
    db: AsyncSession,
    salesman: MallUser,
    order_id: str,
    *,
    amount: Decimal,
    payment_method: str,
    vouchers: list[dict],  # [{url, sha256, size, mime_type?}]
    remarks: Optional[str] = None,
    request_ip: Optional[str] = None,
    request_ua: Optional[str] = None,
):
    """业务员上传收款凭证。delivered → pending_payment_confirmation。

    建 MallPayment（status=pending_confirmation）+ MallAttachment。金额允许分次收款，
    不要求 amount==pay_amount；全款判定在 confirm_payment 里做。
    """
    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能操作自己接的订单")
    if order.status != MallOrderStatus.DELIVERED.value:
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不可上传凭证（需先送达）",
        )
    if amount is None or amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    if not vouchers:
        raise HTTPException(status_code=400, detail="请至少上传一张收款凭证")
    if payment_method not in ("cash", "bank", "wechat", "alipay"):
        raise HTTPException(status_code=400, detail="支付方式非法")

    # 金额上限：本次 amount + 已 pending 未确认的凭证合计 + 已确认 received
    # 不得超过 pay_amount × 1.05（容忍 5% 溢出，覆盖零头/手续费）
    from app.models.mall.base import MallPaymentApprovalStatus
    from app.models.mall.order import MallPayment as _MP
    pending_sum = int((
        await db.execute(
            select(func.coalesce(func.sum(_MP.amount), 0))
            .where(_MP.order_id == order.id)
            .where(_MP.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
        )
    ).scalar() or 0)
    pending_sum_dec = Decimal(str(pending_sum))
    total_projected = (order.received_amount or Decimal("0")) + pending_sum_dec + amount
    max_allowed = order.pay_amount * Decimal("1.05")
    if total_projected > max_allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"金额超出应收（应收 {order.pay_amount}，"
                f"已收 {order.received_amount or 0}，待审 {pending_sum_dec}，"
                f"本次 {amount}，合计超过 5% 容忍上限）"
            ),
        )

    from app.models.mall.base import MallAttachmentType, MallPaymentChannel
    from app.models.mall.order import MallAttachment, MallPayment

    payment = MallPayment(
        order_id=order.id,
        uploaded_by_user_id=salesman.id,
        amount=amount,
        payment_method=payment_method,
        channel=MallPaymentChannel.OFFLINE.value,
        remarks=remarks,
    )
    db.add(payment)
    await db.flush()

    for v in vouchers:
        if not v.get("url") or not v.get("sha256"):
            raise HTTPException(status_code=400, detail="凭证缺少 url/sha256")
        if not v["url"].startswith("/api/uploads/files/mall/"):
            raise HTTPException(
                status_code=400, detail="凭证 URL 非法，请通过附件上传端点获取",
            )
        db.add(MallAttachment(
            kind=MallAttachmentType.PAYMENT_VOUCHER.value,
            ref_type="payment",
            ref_id=payment.id,
            file_url=v["url"],
            sha256=v["sha256"],
            file_size=int(v.get("size") or 0),
            mime_type=v.get("mime_type"),
            uploaded_by_user_id=salesman.id,
            client_ip=request_ip,
            uploaded_user_agent=(request_ua or "")[:500] or None,
        ))

    order.status = MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value
    order.payment_status = "pending_confirmation"
    await db.flush()
    return payment


# =============================================================================
# 财务确认收款（admin/boss/finance 调用）
# =============================================================================

async def confirm_payment(
    db: AsyncSession,
    order_id: str,
    operator_employee_id: str,
) -> MallOrder:
    """财务批量确认该订单的所有 pending payments。

    动作：
      - 所有 pending_confirmation 的 MallPayment → confirmed（累计 amount 写入 order.received_amount）
      - 判全款：received_amount >= pay_amount → completed，paid_at/completed_at，并触发 commission
      - 幂等：重复调用不会双扣；commission_posted 标记防重复

    注意不引 profit_service（ERP 当前无 profit_ledger 表；按 received_amount 事实记录，由 ERP 报表自行汇总）
    """
    from app.models.mall.base import MallPaymentApprovalStatus
    from app.models.mall.order import MallPayment
    from app.services.mall.commission_service import post_commission_for_order

    order = await _require_order_for_claim(db, order_id)
    if order.status == MallOrderStatus.COMPLETED.value:
        # 幂等：已完结订单直接返回
        return order
    if order.status not in (
        MallOrderStatus.DELIVERED.value,
        MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不可确认收款",
        )

    payments = (await db.execute(
        select(MallPayment)
        .where(MallPayment.order_id == order.id)
        .where(MallPayment.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
        .with_for_update()
    )).scalars().all()

    if not payments:
        raise HTTPException(status_code=400, detail="没有待确认的凭证")

    now = datetime.now(timezone.utc)
    new_received = order.received_amount or Decimal("0")
    for p in payments:
        p.status = MallPaymentApprovalStatus.CONFIRMED.value
        p.confirmed_at = now
        p.confirmed_by_employee_id = operator_employee_id
        new_received += p.amount

    order.received_amount = new_received
    from app.services.notification_service import notify_mall_user
    if new_received >= order.pay_amount:
        order.status = MallOrderStatus.COMPLETED.value
        order.payment_status = "fully_paid"
        order.paid_at = now
        order.completed_at = now
        user = (await db.execute(
            select(MallUser).where(MallUser.id == order.user_id)
        )).scalar_one_or_none()
        if user:
            user.last_order_at = now
        await db.flush()
        await post_commission_for_order(db, order)

        # 通知 consumer + 业务员
        await notify_mall_user(
            db, mall_user_id=order.user_id,
            title="订单已完成",
            content=f"订单 {order.order_no} 款项已全额确认，交易完成。感谢您的支持！",
            entity_type="MallOrder", entity_id=order.id,
        )
        if order.assigned_salesman_id:
            await notify_mall_user(
                db, mall_user_id=order.assigned_salesman_id,
                title="订单完结，提成已入账",
                content=f"订单 {order.order_no} 财务已确认收款，提成已入账待结算。",
                entity_type="MallOrder", entity_id=order.id,
            )
    else:
        order.payment_status = "partially_paid"
        order.status = MallOrderStatus.DELIVERED.value
        await db.flush()
        if order.assigned_salesman_id:
            await notify_mall_user(
                db, mall_user_id=order.assigned_salesman_id,
                title="部分收款已确认",
                content=(
                    f"订单 {order.order_no} 本次确认 {new_received} / 应收 {order.pay_amount}，"
                    "继续等待客户补齐款项。"
                ),
                entity_type="MallOrder", entity_id=order.id,
            )

    return order
