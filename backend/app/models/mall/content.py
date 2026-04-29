"""
Mall 内容域：公告等 CMS 内容。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mall.base import MallNoticeStatus


class MallNotice(Base):
    """店铺公告。小程序"最新公告"页用这张表。"""

    __tablename__ = "mall_notices"
    __table_args__ = (
        Index("ix_mall_notices_status_sort", "status", "sort_order"),
        Index("ix_mall_notices_publish", "publish_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 发布时间；<= now 的才展示给 C 端
    publish_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MallNoticeStatus.DRAFT.value
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )
