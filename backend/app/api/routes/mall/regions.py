"""
/api/mall/regions/*

省市区字典。parent_code=None 返一级省份。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.models.mall.user import MallRegion
from app.schemas.mall.product import MallRegionVO

router = APIRouter()


@router.get("", response_model=list[MallRegionVO])
async def list_regions(
    parent_code: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_mall_db),
):
    stmt = select(MallRegion).order_by(MallRegion.area_code)
    if parent_code is None:
        stmt = stmt.where(MallRegion.parent_code.is_(None))
    else:
        stmt = stmt.where(MallRegion.parent_code == parent_code)
    rows = (await db.execute(stmt)).scalars().all()
    return [MallRegionVO.model_validate(r, from_attributes=True) for r in rows]
