"""
/api/mall/salesman/orders/*

业务员履约端点。
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.order import MallOrder
from app.schemas.mall.order import (
    MallOrderDetailVO,
    MallOrderItemVO,
    MallOrderListItemVO,
)
from app.schemas.mall.product import MallPage
from app.services.mall import auth_service, order_service
from app.services.mall.pricing_service import apply_price_visibility

router = APIRouter()


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


# =============================================================================
# Pool
# =============================================================================

@router.get("/pool", response_model=MallPage)
async def get_pool(
    current: CurrentMallUser,
    scope: str = Query(default="my", pattern="^(my|public)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows, total = await order_service.list_order_pool(
        db, user, scope=scope, skip=skip, limit=limit
    )
    # 抢单池：手机号脱敏 + 地址去门牌号（业务员还没抢到）
    items = await order_service.enrich_list_items(db, rows, include_contact=False)
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(d) for d in items],
        total=total, pages=pages,
        current=min(skip // limit + 1, pages),
    )


# =============================================================================
# Claim / Release
# =============================================================================

class _ReasonBody(BaseModel):
    reason: Optional[str] = None


@router.post("/{order_id}/claim")
async def claim(
    order_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.claim_order(db, user, order_id)
    return {"order_no": order.order_no, "status": order.status}


@router.post("/{order_id}/release")
async def release(
    order_id: str,
    current: CurrentMallUser,
    request: Request,
    body: Optional[_ReasonBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.release_order(
        db, user, order_id, reason=body.reason if body else None,
        request=request,
    )
    return {"order_no": order.order_no, "status": order.status}


# =============================================================================
# Ship / Deliver / Upload voucher
# =============================================================================

class _ShipBody(BaseModel):
    warehouse_id: Optional[str] = None
    # 扫码出库：每瓶一个条码。数量必须精确等于订单应发总瓶数。
    scanned_barcodes: Optional[list[str]] = None


class _AttachmentPayload(BaseModel):
    url: str
    sha256: str
    size: Optional[int] = None
    mime_type: Optional[str] = None


class _DeliverBody(BaseModel):
    delivery_photos: list[_AttachmentPayload] = Field(default_factory=list)


class _VoucherBody(BaseModel):
    amount: Decimal
    payment_method: str
    vouchers: list[_AttachmentPayload] = Field(default_factory=list)
    remarks: Optional[str] = None


@router.post("/{order_id}/ship")
async def ship(
    order_id: str,
    current: CurrentMallUser,
    request: Request,
    body: Optional[_ShipBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.ship_order(
        db, user, order_id,
        warehouse_id=body.warehouse_id if body else None,
        scanned_barcodes=body.scanned_barcodes if body else None,
        request=request,
    )
    return {"order_no": order.order_no, "status": order.status}


# ── 实时校验单个条码（小程序扫一次请求一次，失败立刻提示） ────────────────
@router.get("/{order_id}/verify-barcode")
async def verify_barcode(
    order_id: str,
    barcode: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """前端扫到一个条码立刻请求校验：
    返回 {ok, sku_id, product_name, sku_name, message}
    仅校验条码合法性（存在 + IN_STOCK + 属于订单应发 SKU），不做核销。
    真正核销在 /ship 批量提交时。
    """
    from app.models.mall.base import MallInventoryBarcodeStatus
    from app.models.mall.inventory import MallInventoryBarcode
    from app.models.mall.order import MallOrder, MallOrderItem

    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)

    order = (await db.execute(
        select(MallOrder).where(MallOrder.id == order_id)
    )).scalar_one_or_none()
    if order is None or order.assigned_salesman_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在或无权操作")

    bc = (await db.execute(
        select(MallInventoryBarcode).where(MallInventoryBarcode.barcode == barcode)
    )).scalar_one_or_none()
    if bc is None:
        return {"ok": False, "message": "条码不存在"}
    if bc.status != MallInventoryBarcodeStatus.IN_STOCK.value:
        return {"ok": False, "message": f"条码状态 {bc.status}，不可出库"}

    # 必须属于订单内的 SKU
    order_sku_ids = {
        r.sku_id for r in (await db.execute(
            select(MallOrderItem).where(MallOrderItem.order_id == order.id)
        )).scalars()
    }
    if bc.sku_id not in order_sku_ids:
        return {"ok": False, "sku_id": bc.sku_id, "message": "此条码对应的商品不在本订单"}

    sku_snap = (await db.execute(
        select(MallOrderItem.sku_snapshot)
        .where(MallOrderItem.order_id == order.id, MallOrderItem.sku_id == bc.sku_id)
    )).scalar() or {}
    return {
        "ok": True,
        "sku_id": bc.sku_id,
        "product_name": sku_snap.get("product_name"),
        "sku_name": sku_snap.get("sku_name"),
        "batch_no": bc.batch_no,
    }


@router.post("/{order_id}/deliver")
async def deliver(
    order_id: str,
    body: _DeliverBody,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.deliver_order(
        db, user, order_id,
        delivery_photos=[p.model_dump() for p in body.delivery_photos],
        request_ip=request.client.host if request.client else None,
        request_ua=request.headers.get("user-agent"),
    )
    return {"order_no": order.order_no, "status": order.status}


@router.post("/{order_id}/upload-payment-voucher")
async def upload_voucher(
    order_id: str,
    body: _VoucherBody,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    payment = await order_service.upload_payment_voucher(
        db, user, order_id,
        amount=body.amount,
        payment_method=body.payment_method,
        vouchers=[v.model_dump() for v in body.vouchers],
        remarks=body.remarks,
        request_ip=request.client.host if request.client else None,
        request_ua=request.headers.get("user-agent"),
    )
    return {"payment_id": payment.id, "amount": str(payment.amount), "status": payment.status}


# =============================================================================
# 我的订单列表 / 详情
# =============================================================================

@router.get("", response_model=MallPage)
async def my_orders(
    current: CurrentMallUser,
    status: Optional[str] = Query(default=None, description="单个状态；或用逗号分隔多个，如 assigned,shipped"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)

    stmt = select(MallOrder).where(MallOrder.assigned_salesman_id == user.id)
    if status:
        parts = [s.strip() for s in status.split(",") if s.strip()]
        if len(parts) == 1:
            stmt = stmt.where(MallOrder.status == parts[0])
        elif parts:
            stmt = stmt.where(MallOrder.status.in_(parts))
    stmt = stmt.order_by(desc(MallOrder.created_at))

    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    # 我的订单 tab：业务员已抢到的单 → 完整手机号 + 完整地址
    items = await order_service.enrich_list_items(db, rows, include_contact=True)
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(d) for d in items],
        total=total, pages=pages,
        current=min(skip // limit + 1, pages),
    )


@router.get("/{order_id}", response_model=MallOrderDetailVO)
async def order_detail(
    order_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)

    order = (await db.execute(
        select(MallOrder).where(MallOrder.id == order_id)
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.assigned_salesman_id != user.id and order.referrer_salesman_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看此订单")

    items = await order_service.get_order_items(db, order.id)
    # 补客户昵称 / 完整手机号 / 完整地址 / 商品摘要（详情页需要完整信息，业务员已抢到）
    enriched = (await order_service.enrich_list_items(
        db, [order], include_contact=True
    ))[0]
    vo = MallOrderDetailVO.model_validate(order, from_attributes=True)
    vo.customer_nick = enriched.get("customer_nick")
    vo.masked_phone = enriched.get("masked_phone")
    vo.brief_address = enriched.get("brief_address")
    vo.items_brief = enriched.get("items_brief")
    vo.items = [
        MallOrderItemVO.model_validate({
            "product_id": it.product_id, "sku_id": it.sku_id,
            "prod_name": (it.sku_snapshot or {}).get("product_name"),
            "sku_name": (it.sku_snapshot or {}).get("sku_name"),
            "pic": (it.sku_snapshot or {}).get("pic"),
            "price": it.price, "quantity": it.quantity, "subtotal": it.subtotal,
        })
        for it in items
    ]
    # 凭证列表（业务员端详情要能看到是否被驳回 + 原因，方便重传）
    from app.models.mall.order import MallPayment
    from app.schemas.mall.order import MallOrderPaymentVO
    pays = (await db.execute(
        select(MallPayment)
        .where(MallPayment.order_id == order.id)
        .order_by(MallPayment.created_at.desc())
    )).scalars().all()
    vo.payments = [MallOrderPaymentVO.model_validate(p, from_attributes=True) for p in pays]
    return vo
