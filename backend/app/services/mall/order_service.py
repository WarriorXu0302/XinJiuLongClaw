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
    MallInventoryFlowType,
    MallOrderStatus,
    MallSkipAlertStatus,
    MallSkipType,
    MallUserStatus,
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
        if prod.status != "on_sale":
            raise HTTPException(
                status_code=400, detail=f"商品「{prod.name}」已下架，请从购物车移除",
            )

        subtotal = (sku.price * qty).quantize(Decimal("0.01"))
        total_amount += subtotal
        # 字段对齐 MallOrderItemVO 的驼峰 alias（prodId/skuId/prodName/skuName/count）
        # → 前端 submit-order + order-detail 能用同一套字段读取
        detailed_items.append({
            "skuId": sku_id,
            "prodId": prod.id,
            "prodName": prod.name,
            "skuName": sku.spec,
            "price": str(sku.price),
            "count": qty,
            "subtotal": str(subtotal),
            "pic": sku.image or prod.main_image,
            "brandId": prod.brand_id,
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
    # 推荐人被禁用时下单会进独占期但没人看到（开放期开始前订单悬空）→ 提前拒绝
    # 让用户去联系业务员换绑；admin 也能从"换绑推荐人"端点介入
    if user.user_type != "salesman" and user.referrer_salesman_id:
        ref = await db.get(MallUser, user.referrer_salesman_id)
        if ref is not None and ref.status != MallUserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=403,
                detail="您的推荐业务员已停用，请联系客服换绑新业务员",
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
        if prod is None:
            raise HTTPException(status_code=404, detail=f"商品 {sku.product_id} 不存在")
        if prod.status != "on_sale":
            raise HTTPException(
                status_code=400, detail=f"商品「{prod.name}」已下架，请从购物车移除",
            )

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

        # 成本快照优先级：inventory.avg_cost_price > sku.cost_price
        # 两者都 None → 拒绝下单（否则利润台账会按 0 成本算虚高利润）
        snapshot_cost = cost_snapshot if cost_snapshot is not None else sku.cost_price
        if snapshot_cost is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"商品「{prod.name}」尚未配置成本价，请联系运营配置后再下单"
                    f"（SKU {sku_id}）"
                ),
            )

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
            cost_price_snapshot=snapshot_cost,
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
    """C 端订单列表。status_filter 支持逗号分隔多值（与业务员端保持一致）。"""
    from sqlalchemy import desc, func

    stmt = (
        select(MallOrder)
        .where(MallOrder.user_id == user.id)
        .where(MallOrder.consumer_deleted_at.is_(None))  # 软删订单不进列表
    )
    if status_filter:
        parts = [s.strip() for s in status_filter.split(",") if s.strip()]
        if len(parts) == 1:
            stmt = stmt.where(MallOrder.status == parts[0])
        elif parts:
            stmt = stmt.where(MallOrder.status.in_(parts))
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
    request=None,
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

    # 退回库存 — 按原出库 flow 定位扣库存时的仓（而非当前默认仓，避免默认仓被换过后退错仓）
    from app.models.mall.inventory import MallInventory, MallInventoryFlow
    items = await get_order_items(db, order.id)
    # 先拉出本订单的所有出库 flow：inventory_id → warehouse_id/sku_id
    flows = (await db.execute(
        select(MallInventoryFlow, MallInventory)
        .join(MallInventory, MallInventoryFlow.inventory_id == MallInventory.id)
        .where(MallInventoryFlow.ref_type == "order")
        .where(MallInventoryFlow.ref_id == order.id)
        .where(MallInventoryFlow.flow_type == MallInventoryFlowType.OUT.value)
    )).all()
    # 按 sku 聚合原仓（防同 sku 被多次扣出）
    sku_to_warehouse: dict[int, str] = {inv.sku_id: inv.warehouse_id for _, inv in flows}

    for it in items:
        src_wh = sku_to_warehouse.get(it.sku_id)
        if src_wh is None:
            # 无出库 flow（理论不该发生：order 要么未扣库存要么一定有 flow）
            raise HTTPException(
                status_code=500,
                detail=f"找不到 SKU {it.sku_id} 的原出库流水，无法退回",
            )
        await restock_for_cancel(
            db,
            warehouse_id=src_wh,
            sku_id=it.sku_id,
            quantity=it.quantity,
            order_id=order.id,
            cost_price=it.cost_price_snapshot,
        )

    order.status = MallOrderStatus.CANCELLED.value
    order.cancellation_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)

    # 审计：C 端取消涉及退库存 + 金额冲销，客诉争议追溯
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.consumer_cancel",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "order_no": order.order_no,
            "pay_amount": str(order.pay_amount),
            "item_count": len(items),
            "reason": reason,
        },
    )

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


async def delete_my_order(
    db: AsyncSession, user: MallUser, order_no: str, request=None,
) -> None:
    """C 端从订单列表"删除"订单。实际上软删（consumer_deleted_at=now），
    订单本身保留给利润/审计/业务员视角。

    只允许终态订单被删：
      - completed（已完成，订单闭环结束）
      - cancelled（已取消）
      - partial_closed（坏账折损关单）

    其他状态（在途/待付款）禁止删除，避免用户误操作隐藏未处理订单。
    幂等：已删过不抛错。
    """
    order = (await db.execute(
        select(MallOrder)
        .where(MallOrder.order_no == order_no)
        .where(MallOrder.user_id == user.id)
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.consumer_deleted_at is not None:
        return  # 幂等

    if order.status not in (
        MallOrderStatus.COMPLETED.value,
        MallOrderStatus.CANCELLED.value,
        MallOrderStatus.PARTIAL_CLOSED.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可删除（仅已完成/已取消订单可从列表移除）",
        )

    order.consumer_deleted_at = datetime.now(timezone.utc)

    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.consumer_delete",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "order_no": order.order_no,
            "prev_status": order.status,
        },
    )
    await db.flush()


async def confirm_receipt(
    db: AsyncSession, user: MallUser, order_no: str, request=None,
) -> MallOrder:
    """C 端"确认收货"。

    状态不由此推进（真正驱动：业务员送达 → 上传凭证 → 财务确认收款）；
    但必须记录 customer_confirmed_at，出现"我明明点过确认"争议时有 DB 凭证。

    规则：
      - 必须处于 delivered（其他状态都不合逻辑）
      - 幂等：重复点不抛错，不更新时间（保留首次点击时间）
      - 通知配送业务员：客户已确认收货，尽快收款
    """
    order = await get_my_order(db, user, order_no)
    # 允许状态：delivered / pending_payment_confirmation / completed / partial_closed
    # 客户点确认可能晚于业务员上传凭证或财务确认，都应接受并记录时间戳
    if order.status not in (
        MallOrderStatus.DELIVERED.value,
        MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        MallOrderStatus.COMPLETED.value,
        MallOrderStatus.PARTIAL_CLOSED.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可确认收货",
        )

    # 幂等：已确认过就直接返回
    if order.customer_confirmed_at is not None:
        return order

    now = datetime.now(timezone.utc)
    order.customer_confirmed_at = now

    # 审计：客户明示已收货，事后争议追溯
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.customer_confirm_receipt",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "order_no": order.order_no,
            "pay_amount": str(order.pay_amount),
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        },
    )

    # 通知配送业务员
    if order.assigned_salesman_id:
        from app.services.notification_service import notify_mall_user
        await notify_mall_user(
            db, mall_user_id=order.assigned_salesman_id,
            title="客户已确认收货",
            content=f"订单 {order.order_no} 客户已确认收货，请尽快完成收款。",
            entity_type="MallOrder", entity_id=order.id,
        )

    await db.flush()
    return order


# =============================================================================
# 订单统计（orderCount）
# =============================================================================

async def order_stats(db: AsyncSession, user: MallUser) -> dict[str, int]:
    """对齐 mall4j /p/myOrder/orderCount：
    { unPay, payed, consignment, unComment } 四个计数。

    C 端视角（小程序第一版线下收款，付款发生在业务员送达时）：
      unPay       = 尚未送达收款的所有订单（下单/接单/出库/送达/财务确认中）
      payed       = 已全款确认 → completed；加上已关单的 partial_closed（对 C 端都是"订单已结束"）
      consignment = 配送中（已出库未送达）
      unComment   = 已评价功能暂不做

    过滤 consumer_deleted_at：C 端从列表删除的订单不在任何角标里显示。
    """
    from sqlalchemy import func

    async def _count(*statuses: str) -> int:
        return int((
            await db.execute(
                select(func.count(MallOrder.id))
                .where(MallOrder.user_id == user.id)
                .where(MallOrder.consumer_deleted_at.is_(None))
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
        "payed": await _count(
            MallOrderStatus.COMPLETED.value,
            MallOrderStatus.PARTIAL_CLOSED.value,
        ),
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


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    """138****1234 风格脱敏；位数不够就整串脱敏保留首末。"""
    if not phone:
        return None
    s = str(phone)
    if len(s) < 7:
        return s[:1] + "*" * (len(s) - 2) + s[-1:] if len(s) >= 2 else "***"
    return f"{s[:3]}****{s[-4:]}"


def _brief_address(snap: Optional[dict]) -> Optional[str]:
    """省市区 + 街道（不含门牌号）。"""
    if not snap:
        return None
    parts = [snap.get("province"), snap.get("city"), snap.get("area")]
    return " ".join(p for p in parts if p) or None


async def enrich_list_items(
    db: AsyncSession, rows: list[MallOrder], *, include_contact: bool = False
) -> list[dict]:
    """把 MallOrder 列表补上业务员工作台展示字段。

    include_contact=False：抢单池场景（还没抢到）— 手机号脱敏、地址去门牌号
    include_contact=True：已抢到的订单（我的订单 tab）— 手机号完整、地址完整
    """
    if not rows:
        return []

    # 批量拉订单项（按 order_id 聚合 brief）
    order_ids = [o.id for o in rows]
    items_rows = (
        await db.execute(
            select(MallOrderItem).where(MallOrderItem.order_id.in_(order_ids))
        )
    ).scalars().all()
    items_by_order: dict[str, list[MallOrderItem]] = {}
    for it in items_rows:
        items_by_order.setdefault(it.order_id, []).append(it)

    # 批量拉客户昵称
    user_ids = list({o.user_id for o in rows})
    users_rows = (
        await db.execute(select(MallUser).where(MallUser.id.in_(user_ids)))
    ).scalars().all()
    user_by_id = {u.id: u for u in users_rows}

    out: list[dict] = []
    for o in rows:
        items = items_by_order.get(o.id, [])
        # items_brief：取前 2 个 SKU 名 + 数量
        brief_parts: list[str] = []
        for it in items[:2]:
            snap = it.sku_snapshot or {}
            name = snap.get("product_name") or snap.get("sku_name") or ""
            brief_parts.append(f"{name}×{it.quantity}")
        if len(items) > 2:
            brief_parts.append(f"等{len(items)}件")
        items_brief = "，".join(brief_parts) if brief_parts else None

        cust = user_by_id.get(o.user_id)
        addr = o.address_snapshot or {}
        full_mobile = addr.get("mobile")

        # 独占期到期时间（仅 pending_assignment 阶段有意义）
        expires_at = None
        if (
            o.status == MallOrderStatus.PENDING_ASSIGNMENT.value
            and o.created_at is not None
        ):
            expires_at = o.created_at + timedelta(
                minutes=settings.MALL_UNCLAIMED_TIMEOUT_MINUTES
            )

        d = {
            "id": o.id,
            "order_no": o.order_no,
            "status": o.status,
            "payment_status": o.payment_status,
            "pay_amount": o.pay_amount,
            "total_amount": o.total_amount,
            "created_at": o.created_at,
            "remarks": o.remarks,
            "customer_nick": (cust.nickname if cust else None) or addr.get("receiver"),
            "masked_phone": full_mobile if include_contact else _mask_phone(full_mobile),
            "brief_address": _brief_address(addr) if not include_contact else (
                _brief_address(addr) + (" " + (addr.get("addr") or "") if addr.get("addr") else "")
            ),
            "items_brief": items_brief,
            "expires_at": expires_at,
        }
        out.append(d)
    return out


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
    # 接单开关 = 业务员是否接受派单/抢单。关闭时不能抢（否则业务员可能抢了不履约）
    if not salesman.is_accepting_orders:
        raise HTTPException(
            status_code=403,
            detail="您的接单开关已关闭，请先在「我的」页打开接单",
        )
    # 绑 employee 才能入提成表（改派也有同样校验，这里保持一致）
    if not salesman.linked_employee_id:
        raise HTTPException(
            status_code=400, detail="账号未绑定 ERP 员工，无法抢单",
        )

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
    db: AsyncSession, salesman: MallUser, order_id: str,
    reason: Optional[str] = None, request=None,
) -> MallOrder:
    """业务员主动释放。订单回到 pending_assignment，若原业务员是推荐人则记 skip_log。

    仅允许 `assigned` 状态释放：shipped 后条码已 OUTBOUND 绑定到原业务员，
    若允许释放会导致新接单人的库存状态和条码归属不一致，须走"管理员改派"路径。
    """
    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能释放自己接的订单")
    if order.status != MallOrderStatus.ASSIGNED.value:
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不可释放（仅刚接单未出库可释放，出库后请联系管理员改派）",
        )

    prev_salesman = order.assigned_salesman_id
    prev_status = order.status
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
    # 边缘场景：业务员给自己下单（释放 == 自释自订），不记 skip（同 admin_reassign 的理由）
    is_referrer = order.referrer_salesman_id == prev_salesman
    is_self_order = order.user_id == prev_salesman
    if is_referrer and not is_self_order:
        await _record_skip_log(
            db, order, prev_salesman, MallSkipType.RELEASED.value
        )

    # 合规审计：业务员释放订单属于异常动作（直接触发 skip_log）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.release",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=salesman.id, actor_type="mall_user",
        request=request,
        changes={
            "order_no": order.order_no,
            "prev_status": prev_status,
            "is_referrer": is_referrer,  # True 会触发 skip_log
            "reason": reason,
        },
    )

    await db.flush()
    return order


async def admin_reassign(
    db: AsyncSession,
    order_id: str,
    target_salesman_id: str,
    operator_erp_user_id: str,
    reason: Optional[str] = None,
    request=None,  # 可选 Request 用于记审计 IP
    actor_employee_id: Optional[str] = None,  # 操作人的 employee_id，用于审计
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

    # 出库后改派：把原业务员名下的 OUTBOUND 条码过户到新业务员，避免归属错乱
    # （归属错乱会导致 HR 追溯"谁真正送达"时 outbound_by ≠ assigned 互相不对）
    if prev_salesman and prev_salesman != target.id and order.status in (
        MallOrderStatus.SHIPPED.value,
        MallOrderStatus.DELIVERED.value,
        MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
    ):
        from sqlalchemy import update as sa_update
        from app.models.mall.inventory import MallInventoryBarcode
        await db.execute(
            sa_update(MallInventoryBarcode)
            .where(MallInventoryBarcode.outbound_order_id == order.id)
            .values(outbound_by_user_id=target.id)
        )

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
    # 边缘场景：业务员给自己下单（user_id == referrer_salesman_id），改派不记 skip
    #   原因：skip 的语义是"推荐人不服务自己推荐的客户"，但自买订单的"客户"就是自己，
    #   被改派时不涉及"未服务推荐客户"的违约含义；记 skip 只会污染自己的告警统计
    if (
        prev_salesman
        and order.referrer_salesman_id == prev_salesman
        and order.user_id != prev_salesman
    ):
        await _record_skip_log(
            db, order, prev_salesman, MallSkipType.ADMIN_REASSIGNED.value
        )

    # 合规审计（管理员强制改派是敏感操作）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.admin_reassign",
        entity_type="MallOrder", entity_id=order.id,
        actor_id=actor_employee_id, request=request,
        changes={
            "order_no": order.order_no,
            "from_salesman_id": prev_salesman,
            "to_salesman_id": target.id,
            "reason": reason,
        },
    )

    # 通知新业务员接单 + 旧业务员订单被改派 + 消费者（已接单后 C 端能看到配送员换了）
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
    # 只有在曾经有过 assigned_salesman 的情况下（消费者已在订单里看到配送员信息），才通知消费者
    if prev_salesman and prev_salesman != target.id:
        target_nick = target.nickname or target.username or "新业务员"
        await notify_mall_user(
            db, mall_user_id=order.user_id,
            title="配送员已变更",
            content=f"您的订单 {order.order_no} 配送员已调整为 {target_nick}，请查看订单详情联系。",
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
        # 自买单不记 skip（业务员自己下单又自己超时没抢 → 记 skip 毫无业务意义）
        if order.user_id == order.referrer_salesman_id:
            continue
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
    db: AsyncSession, salesman: MallUser, alert_id: str, reason: str,
    request=None,
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

    # 审计（业务员申诉是单向表达，后续管理员裁决有独立 resolve 审计）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_skip_alert.appeal",
        entity_type="MallSkipAlert", entity_id=alert.id,
        mall_user_id=salesman.id, actor_type="mall_user",
        request=request,
        changes={"reason": reason, "skip_count": alert.skip_count},
    )

    # 通知 admin/boss 有新申诉待裁决
    from app.services.notification_service import notify_roles
    nick = salesman.nickname or salesman.username or "业务员"
    await notify_roles(
        db, role_codes=["admin", "boss"],
        title="跳单告警申诉待裁决",
        content=f"业务员「{nick}」对累计 {alert.skip_count} 次跳单告警提申诉：{reason[:80]}",
        entity_type="MallSkipAlert", entity_id=alert.id,
    )

    await db.flush()
    return alert


async def resolve_skip_alert(
    db: AsyncSession,
    alert_id: str,
    operator_id: str,
    operator_type: str,
    resolution_status: str,  # resolved / dismissed
    note: Optional[str] = None,
    request=None,
    actor_employee_id: Optional[str] = None,  # operator_type='erp_user' 时传
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
    dismissed_log_count = 0
    if resolution_status == MallSkipAlertStatus.DISMISSED.value and alert.trigger_log_ids:
        from sqlalchemy import update as sql_update
        res = await db.execute(
            sql_update(MallCustomerSkipLog)
            .where(MallCustomerSkipLog.id.in_(alert.trigger_log_ids))
            .values(dismissed=True)
        )
        dismissed_log_count = int(res.rowcount or 0)

    # 审计（裁决业务员申诉是合规必留痕）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action=f"mall_skip_alert.{resolution_status}",
        entity_type="MallSkipAlert", entity_id=alert.id,
        actor_id=actor_employee_id if operator_type == "erp_user" else None,
        actor_type=operator_type,
        request=request,
        changes={
            "salesman_user_id": alert.salesman_user_id,
            "customer_user_id": alert.customer_user_id,
            "skip_count": alert.skip_count,
            "appeal_reason": alert.appeal_reason,
            "resolution_note": note,
            "dismissed_skip_logs": dismissed_log_count,
        },
    )

    # 通知业务员裁决结果（业务员提了申诉/未申诉都该被告知）
    from app.services.notification_service import notify_mall_user
    if resolution_status == MallSkipAlertStatus.DISMISSED.value:
        title = "跳单告警已驳回"
        content = (
            f"您的跳单告警（累计 {alert.skip_count} 次）经审核被驳回，"
            "不计入后续阈值。"
        ) + (f"\n运营说明：{note}" if note else "")
    else:
        title = "跳单告警已确认"
        content = (
            f"您的跳单告警（累计 {alert.skip_count} 次）经审核确认成立，"
            "请调整接单节奏。"
        ) + (f"\n运营说明：{note}" if note else "")
    await notify_mall_user(
        db, mall_user_id=alert.salesman_user_id,
        title=title, content=content,
        entity_type="MallSkipAlert", entity_id=alert.id,
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
    scanned_barcodes: Optional[list[str]] = None,
    request=None,
) -> MallOrder:
    """业务员扫码出库。assigned → shipped。

    白酒业务硬规矩：**每瓶必须扫厂家防伪码**（防串货/防假货/可追溯）。
    收货入库时每瓶已录进 mall_inventory_barcodes.status='in_stock'，出库时
    逐码核销 in_stock → outbound。绝不允许按数量散装出库。

    对齐 ERP 扫码规则：
      (1) scanned_barcodes 必传，长度 == 订单应发总瓶数
      (2) 每个条码在库 + status='in_stock' + 指向订单 SKU 之一
      (3) 按 SKU 核数：应发 vs 扫码数必须一一匹配
      (4) 不允许扫到订单外的 SKU，不允许重复扫
      (5) 核销成功 → 条码 IN_STOCK → OUTBOUND；回填 outbound_order_id/user/at
      (6) 任一校验失败整笔回滚，绝不允许"散装"或"扫一半"
    """
    from app.models.mall.base import MallInventoryBarcodeStatus, MallInventoryBarcodeType
    from app.models.mall.inventory import MallInventoryBarcode
    from app.models.mall.order import MallShipment

    order = await _require_order_for_claim(db, order_id)
    if order.assigned_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="只能操作自己接的订单")
    if order.status != MallOrderStatus.ASSIGNED.value:
        raise HTTPException(status_code=409, detail=f"订单状态 {order.status} 不可出库")

    # 白酒硬要求：必须扫码，不允许缺省
    if not scanned_barcodes:
        raise HTTPException(
            status_code=400,
            detail="白酒出库必须扫防伪码（每瓶一码），不允许按数量出库",
        )

    now = datetime.now(timezone.utc)

    # ── 扫码核销 ────────────────────────────────────────────
    if scanned_barcodes is not None:
        # 按 SKU 统计订单应发数量
        order_items = await get_order_items(db, order.id)
        required_by_sku: dict[int, int] = {}
        for oi in order_items:
            required_by_sku[oi.sku_id] = required_by_sku.get(oi.sku_id, 0) + oi.quantity

        if len(scanned_barcodes) != sum(required_by_sku.values()):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"扫码数量不符：应发 {sum(required_by_sku.values())} 瓶，"
                    f"实际扫 {len(scanned_barcodes)} 瓶"
                ),
            )

        # 查条码 + FOR UPDATE 锁
        bcs = (await db.execute(
            select(MallInventoryBarcode)
            .where(MallInventoryBarcode.barcode.in_(scanned_barcodes))
            .with_for_update()
        )).scalars().all()
        bc_by_code = {b.barcode: b for b in bcs}
        missing = [c for c in scanned_barcodes if c not in bc_by_code]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"以下条码不存在：{', '.join(missing[:5])}",
            )

        # 所有条码状态 = in_stock
        not_in_stock = [
            b.barcode for b in bcs
            if b.status != MallInventoryBarcodeStatus.IN_STOCK.value
        ]
        if not_in_stock:
            raise HTTPException(
                status_code=400,
                detail=f"以下条码状态异常，不可出库：{', '.join(not_in_stock[:5])}",
            )

        # 重复扫同一条码
        if len(set(scanned_barcodes)) != len(scanned_barcodes):
            raise HTTPException(status_code=400, detail="扫码包含重复条码")

        # 按 SKU 核对数量
        scanned_by_sku: dict[int, int] = {}
        for b in bcs:
            scanned_by_sku[b.sku_id] = scanned_by_sku.get(b.sku_id, 0) + 1
        for sku_id, req in required_by_sku.items():
            got = scanned_by_sku.get(sku_id, 0)
            if got != req:
                raise HTTPException(
                    status_code=400,
                    detail=f"SKU {sku_id} 扫码数 {got} ≠ 应发数 {req}",
                )
        extra_skus = set(scanned_by_sku) - set(required_by_sku)
        if extra_skus:
            raise HTTPException(
                status_code=400,
                detail=f"扫到了订单外的 SKU：{sorted(extra_skus)}",
            )

        # 所有校验通过 → 批量核销
        for b in bcs:
            b.status = MallInventoryBarcodeStatus.OUTBOUND.value
            b.outbound_order_id = order.id
            b.outbound_by_user_id = salesman.id
            b.outbound_at = now

    # ── 物流记录 ────────────────────────────────────────────
    ship = (await db.execute(
        select(MallShipment).where(MallShipment.order_id == order.id)
    )).scalar_one_or_none()
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

    # 审计：出库涉及库存流动，供应链合规必记
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.ship",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=salesman.id, actor_type="mall_user",
        request=request,
        changes={
            "order_no": order.order_no,
            "warehouse_id": warehouse_id,
            "scanned_barcode_count": len(scanned_barcodes) if scanned_barcodes else 0,
            "used_scan_verification": scanned_barcodes is not None,
        },
    )

    # 通知消费者：订单已出库
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db, mall_user_id=order.user_id,
        title="订单已出库",
        content=f"您的订单 {order.order_no} 商品已出库，业务员正在为您配送。",
        entity_type="MallOrder", entity_id=order.id,
    )

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

    # 审计：送达照片 sha256 入库，合规留痕
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.deliver",
        entity_type="MallOrder", entity_id=order.id,
        mall_user_id=salesman.id, actor_type="mall_user",
        ip_address=request_ip,
        changes={
            "order_no": order.order_no,
            "photo_count": len(delivery_photos),
            "photo_sha256": [p.get("sha256") for p in delivery_photos][:5],
        },
    )

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

    # 合规审计（凭证上传=真金白银入账前的最后一步，必记）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_payment.upload_voucher",
        entity_type="MallPayment", entity_id=payment.id,
        mall_user_id=salesman.id, actor_type="mall_user",
        ip_address=request_ip,
        changes={
            "order_no": order.order_no,
            "amount": str(amount),
            "payment_method": payment_method,
            "voucher_count": len(vouchers),
            "sha256_list": [v.get("sha256") for v in vouchers][:5],  # 最多留 5 个便于追溯
        },
    )

    await db.flush()
    return payment


# =============================================================================
# 财务确认收款（admin/boss/finance 调用）
# =============================================================================

async def confirm_payment(
    db: AsyncSession,
    order_id: str,
    operator_employee_id: str,
    request=None,  # 可选：记审计 IP
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

        # 累加商品销量（每个 product 按订单里的总数量）
        items = await get_order_items(db, order.id)
        qty_by_product: dict[int, int] = {}
        for it in items:
            qty_by_product[it.product_id] = qty_by_product.get(it.product_id, 0) + it.quantity
        for pid, qty in qty_by_product.items():
            prod = await db.get(MallProduct, pid)
            if prod is not None:
                prod.total_sales = (prod.total_sales or 0) + qty

        await db.flush()
        await post_commission_for_order(db, order)

        # 标记已入利润台账（实时聚合，表本身不存；这个标志让报表查询能 WHERE 过滤）
        order.profit_ledger_posted = True

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

    # 合规审计：财务确认真金白银入账，必记
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_order.confirm_payment",
        entity_type="MallOrder", entity_id=order.id,
        actor_id=operator_employee_id, request=request,
        changes={
            "order_no": order.order_no,
            "pay_amount": str(order.pay_amount),
            "received_amount": str(new_received),
            "status_after": order.status,
            "confirmed_count": len(payments),
        },
    )

    return order
