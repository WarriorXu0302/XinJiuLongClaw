"""
Mall 订单服务（M3 范围：预览 / 建单 / 列表 / 详情 / 取消 / 确认收货）。

M4 再补：抢单池 / claim/release/ship/deliver / upload_voucher / confirm_payment /
profit/commission 回写 / partial_close。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import MallOrderStatus
from app.models.mall.order import (
    MallCartItem,
    MallOrder,
    MallOrderItem,
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
