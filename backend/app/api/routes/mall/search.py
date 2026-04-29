"""
/api/mall/search/*
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUserOptional
from app.models.mall.base import MallProductStatus
from app.models.mall.product import MallProduct
from app.schemas.mall.product import MallPage, MallProductListItemVO
from app.services.mall.pricing_service import apply_price_visibility

router = APIRouter()


HOT_KEYWORDS = ["飞天茅台", "五粮液", "青岛啤酒", "汾酒", "水井坊"]


@router.get("/products", response_model=MallPage)
async def search_products(
    current: CurrentMallUserOptional,
    q: Optional[str] = Query(default=None, description="关键词"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)

    stmt = select(MallProduct).where(
        MallProduct.status == MallProductStatus.ON_SALE.value
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(MallProduct.name.ilike(like), MallProduct.brief.ilike(like))
        )
    stmt = stmt.order_by(desc(MallProduct.total_sales), desc(MallProduct.id))

    total_count = int((
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    pages = max((total_count + limit - 1) // limit, 1)
    return MallPage(
        records=[
            MallProductListItemVO.model_validate(r, from_attributes=True) for r in rows
        ],
        total=total_count,
        pages=pages,
        current=min(skip // limit + 1, pages),
    )


@router.get("/hot-keywords")
async def hot_keywords():
    return {"records": HOT_KEYWORDS}
