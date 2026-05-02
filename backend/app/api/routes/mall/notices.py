"""
/api/mall/notices/*

匿名可访问。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_, select
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
    # 过滤 publish_at：未来发布时间的公告不给 C 端展示（即使 status=published）
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(MallNotice)
            .where(MallNotice.status == MallNoticeStatus.PUBLISHED.value)
            .where(or_(MallNotice.publish_at.is_(None), MallNotice.publish_at <= now))
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
    # 未到发布时间同样 404 —— 避免通过直链泄漏预发公告内容
    if row.publish_at is not None and row.publish_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="公告不存在")
    return MallNoticeVO.model_validate(row, from_attributes=True)
