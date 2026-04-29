"""
/api/mall/orders/*  （C 端订单）
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.schemas.mall.order import (
    MallOrderCancelRequest,
    MallOrderCreateRequest,
    MallOrderDetailVO,
    MallOrderItemVO,
    MallOrderListItemVO,
    MallOrderPreviewRequest,
    MallOrderPreviewResponse,
    MallOrderStatsVO,
)
from app.schemas.mall.product import MallPage
from app.services.mall import auth_service, order_service
from app.services.mall.pricing_service import apply_price_visibility

router = APIRouter()


# =============================================================================
# Preview
# =============================================================================

@router.post("/preview", response_model=MallOrderPreviewResponse)
async def preview(
    body: MallOrderPreviewRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    result = await order_service.preview_order(
        db, user,
        items=[{"sku_id": i.sku_id, "quantity": i.quantity} for i in body.items],
        address_id=body.address_id,
    )
    return MallOrderPreviewResponse.model_validate(result)


# =============================================================================
# Create
# =============================================================================

@router.post("", response_model=MallOrderDetailVO)
async def create(
    body: MallOrderCreateRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.create_order(
        db, user,
        items=[{"sku_id": i.sku_id, "quantity": i.quantity} for i in body.items],
        address_id=body.address_id,
        remarks=body.remarks,
    )
    items = await order_service.get_order_items(db, order.id)
    return _build_detail_vo(order, items)


# =============================================================================
# List / stats / detail
# =============================================================================

@router.get("/stats", response_model=MallOrderStatsVO)
async def stats(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    return MallOrderStatsVO(**await order_service.order_stats(db, user))


@router.get("", response_model=MallPage)
async def list_orders(
    current: CurrentMallUser,
    status: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows, total = await order_service.list_my_orders(db, user, status, skip, limit)
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        pages=pages,
        current=min(skip // limit + 1, pages),
    )


@router.get("/{order_no}", response_model=MallOrderDetailVO)
async def detail(
    order_no: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.get_my_order(db, user, order_no)
    items = await order_service.get_order_items(db, order.id)
    return _build_detail_vo(order, items)


# =============================================================================
# Cancel / Confirm receipt
# =============================================================================

@router.post("/{order_no}/cancel", response_model=MallOrderDetailVO)
async def cancel(
    order_no: str,
    current: CurrentMallUser,
    body: Optional[MallOrderCancelRequest] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.cancel_order(
        db, user, order_no, reason=body.reason if body else None
    )
    items = await order_service.get_order_items(db, order.id)
    return _build_detail_vo(order, items)


@router.post("/{order_no}/confirm-receipt", response_model=MallOrderDetailVO)
async def confirm_receipt(
    order_no: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.confirm_receipt(db, user, order_no)
    items = await order_service.get_order_items(db, order.id)
    return _build_detail_vo(order, items)


# =============================================================================
# 内部工具
# =============================================================================

def _build_detail_vo(order, items) -> MallOrderDetailVO:
    vo = MallOrderDetailVO.model_validate(order, from_attributes=True)
    vo.items = [
        MallOrderItemVO.model_validate({
            "product_id": it.product_id,
            "sku_id": it.sku_id,
            "prod_name": (it.sku_snapshot or {}).get("product_name"),
            "sku_name": (it.sku_snapshot or {}).get("sku_name"),
            "pic": (it.sku_snapshot or {}).get("pic"),
            "price": it.price,
            "quantity": it.quantity,
            "subtotal": it.subtotal,
        })
        for it in items
    ]
    return vo
