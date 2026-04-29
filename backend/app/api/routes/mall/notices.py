"""
/api/mall/notices/*

匿名可访问。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.models.mall.base import MallNoticeStatus
from app.models.mall.content import MallNotice
from app.schemas.mall.product import MallNoticeListItemVO, MallNoticeVO, MallPage

router = APIRouter()


@router.get("", response_model=MallPage)
async def list_notices(
    db: AsyncSession = Depends(get_mall_db),
):
    rows = (
        await db.execute(
            select(MallNotice)
            .where(MallNotice.status == MallNoticeStatus.PUBLISHED.value)
            .order_by(desc(MallNotice.sort_order), desc(MallNotice.publish_at))
        )
    ).scalars().all()
    return MallPage(
        records=[MallNoticeListItemVO.model_validate(r, from_attributes=True) for r in rows],
        total=len(rows),
    )


@router.get("/{notice_id}", response_model=MallNoticeVO)
async def get_notice(
    notice_id: int,
    db: AsyncSession = Depends(get_mall_db),
):
    row = (
        await db.execute(select(MallNotice).where(MallNotice.id == notice_id))
    ).scalar_one_or_none()
    if row is None or row.status != MallNoticeStatus.PUBLISHED.value:
        raise HTTPException(status_code=404, detail="公告不存在")
    return MallNoticeVO.model_validate(row, from_attributes=True)
