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
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(r, from_attributes=True) for r in rows],
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
    body: Optional[_ReasonBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.release_order(
        db, user, order_id, reason=body.reason if body else None
    )
    return {"order_no": order.order_no, "status": order.status}


# =============================================================================
# Ship / Deliver / Upload voucher
# =============================================================================

class _ShipBody(BaseModel):
    warehouse_id: Optional[str] = None


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
    body: Optional[_ShipBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.ship_order(
        db, user, order_id, warehouse_id=body.warehouse_id if body else None
    )
    return {"order_no": order.order_no, "status": order.status}


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
    status: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)

    stmt = select(MallOrder).where(MallOrder.assigned_salesman_id == user.id)
    if status:
        stmt = stmt.where(MallOrder.status == status)
    stmt = stmt.order_by(desc(MallOrder.created_at))

    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(r, from_attributes=True) for r in rows],
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
    vo = MallOrderDetailVO.model_validate(order, from_attributes=True)
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
    return vo
