"""
/api/mall/products/*

端点：
  GET /tags                         标签楼层
  GET ?tag_id= / ?category_id= / ?filter=lasted|discount|hot   商品列表
  GET /{prod_id}                    商品详情（含 skuList）

价格字段脱敏：未登录或未绑推荐人返 null。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUserOptional
from app.models.mall.base import MallProductStatus
from app.models.mall.product import (
    MallProduct,
    MallProductSku,
    MallProductTag,
    MallProductTagRel,
)
from app.schemas.mall.product import (
    MallPage,
    MallProductDetailVO,
    MallProductListItemVO,
    MallSkuVO,
    MallTagVO,
)
from app.services.mall.pricing_service import apply_price_visibility

router = APIRouter()


# =============================================================================
# 标签列表
# =============================================================================

@router.get("/tags", response_model=list[MallTagVO])
async def list_tags(
    current: CurrentMallUserOptional,  # 不强制登录，但保持签名一致
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    rows = (
        await db.execute(
            select(MallProductTag)
            .where(MallProductTag.status == "active")
            .order_by(MallProductTag.sort_order, MallProductTag.id)
        )
    ).scalars().all()
    return [MallTagVO.model_validate(r, from_attributes=True) for r in rows]


# =============================================================================
# 商品列表
# =============================================================================

@router.get("", response_model=MallPage)
async def list_products(
    current: CurrentMallUserOptional,
    tag_id: Optional[int] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    sort: Optional[str] = Query(default=None, pattern="^(lasted|discount|hot)$", alias="filter"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)

    stmt = select(MallProduct).where(
        MallProduct.status == MallProductStatus.ON_SALE.value
    )

    if tag_id is not None:
        stmt = (
            stmt.join(MallProductTagRel, MallProductTagRel.product_id == MallProduct.id)
            .where(MallProductTagRel.tag_id == tag_id)
        )
    if category_id is not None:
        stmt = stmt.where(MallProduct.category_id == category_id)

    # sort 控制排序：hot=销量倒序，lasted=创建时间倒序，discount=暂按销量倒序（M5 有折扣字段再细分）
    if sort == "hot":
        stmt = stmt.order_by(desc(MallProduct.total_sales), desc(MallProduct.id))
    elif sort == "lasted":
        stmt = stmt.order_by(desc(MallProduct.created_at), desc(MallProduct.id))
    elif sort == "discount":
        stmt = stmt.order_by(desc(MallProduct.total_sales), desc(MallProduct.id))
    else:
        stmt = stmt.order_by(desc(MallProduct.id))

    total_count = int((
        await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
    ).scalar() or 0)
    rows = (
        await db.execute(stmt.offset(skip).limit(limit))
    ).scalars().all()

    pages = max((total_count + limit - 1) // limit, 1)
    return MallPage(
        records=[MallProductListItemVO.model_validate(r, from_attributes=True) for r in rows],
        total=total_count,
        pages=pages,
        current=min(skip // limit + 1, pages),
    )


# =============================================================================
# 商品详情
# =============================================================================

@router.get("/{prod_id}", response_model=MallProductDetailVO)
async def get_product(
    prod_id: int,
    current: CurrentMallUserOptional,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)

    prod = (
        await db.execute(select(MallProduct).where(MallProduct.id == prod_id))
    ).scalar_one_or_none()
    if prod is None or prod.status != MallProductStatus.ON_SALE.value:
        raise HTTPException(status_code=404, detail="商品不存在或已下架")

    skus = (
        await db.execute(
            select(MallProductSku)
            .where(MallProductSku.product_id == prod_id)
            .where(MallProductSku.status == "active")
            .order_by(MallProductSku.id)
        )
    ).scalars().all()

    detail = MallProductDetailVO.model_validate(prod, from_attributes=True)
    detail.sku_list = [MallSkuVO.model_validate(s, from_attributes=True) for s in skus]
    return detail
