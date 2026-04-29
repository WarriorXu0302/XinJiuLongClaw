"""
/api/mall/cart/*
"""
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.order import MallCartItem
from app.models.mall.product import MallProduct, MallProductSku
from app.schemas.mall.cart import (
    MallCartChangeItemRequest,
    MallCartInfoVO,
    MallCartItemVO,
)
from app.services.mall import auth_service
from app.services.mall.pricing_service import (
    apply_price_visibility,
    is_price_visible,
    set_price_visible,
)

router = APIRouter()


# =============================================================================
# 加购 / 改数 / 删除 — 合并成 POST /change (count=0 即删除)
# =============================================================================

@router.post("/change")
async def change_cart_item(
    current: CurrentMallUser,
    body: MallCartChangeItemRequest,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)

    sku = (
        await db.execute(select(MallProductSku).where(MallProductSku.id == body.sku_id))
    ).scalar_one_or_none()
    if sku is None or sku.status != "active":
        raise HTTPException(status_code=404, detail="SKU 不存在或已下架")

    item = (
        await db.execute(
            select(MallCartItem)
            .where(MallCartItem.user_id == user.id)
            .where(MallCartItem.sku_id == body.sku_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if item is None:
        if body.count <= 0:
            return {"success": True}
        db.add(MallCartItem(
            user_id=user.id,
            product_id=body.prod_id,
            sku_id=body.sku_id,
            quantity=body.count,
        ))
    else:
        new_qty = item.quantity + body.count
        if new_qty <= 0:
            await db.execute(delete(MallCartItem).where(MallCartItem.id == item.id))
        else:
            item.quantity = new_qty
    await db.flush()
    return {"success": True}


# =============================================================================
# 购物车列表
# =============================================================================

@router.get("", response_model=MallCartInfoVO)
async def cart_info(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)

    rows = (
        await db.execute(
            select(MallCartItem, MallProductSku, MallProduct)
            .join(MallProductSku, MallProductSku.id == MallCartItem.sku_id)
            .join(MallProduct, MallProduct.id == MallCartItem.product_id)
            .where(MallCartItem.user_id == user.id)
            .order_by(MallCartItem.created_at)
        )
    ).all()

    records = []
    total_price = Decimal("0")
    for cart, sku, prod in rows:
        records.append(MallCartItemVO.model_validate({
            "id": cart.id,
            "product_id": prod.id,
            "sku_id": sku.id,
            "prod_name": prod.name,
            "sku_name": sku.spec,
            "pic": sku.image or prod.main_image,
            "price": sku.price,
            "quantity": cart.quantity,
            "selected": cart.selected,
        }))
        if cart.selected:
            total_price += (sku.price * cart.quantity)

    return MallCartInfoVO(
        records=records,
        total=sum(r.quantity for r in records),
        total_price=total_price if is_price_visible() else None,
    )


# =============================================================================
# 购物车商品数（小程序首页角标用）
# =============================================================================

@router.get("/count")
async def cart_count(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    total = int((
        await db.execute(
            select(func.coalesce(func.sum(MallCartItem.quantity), 0))
            .where(MallCartItem.user_id == user.id)
        )
    ).scalar() or 0)
    return total


# =============================================================================
# 批量删除（body 是 basketId 列表）
# =============================================================================

@router.post("/delete")
async def delete_cart_items(
    current: CurrentMallUser,
    basket_ids: list[str] = Body(...),
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    if not basket_ids:
        return {"success": True}
    await db.execute(
        delete(MallCartItem)
        .where(MallCartItem.user_id == user.id)
        .where(MallCartItem.id.in_(basket_ids))
    )
    await db.flush()
    return {"success": True}
