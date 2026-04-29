"""
Notification log model — 通知记录（ERP 飞书/站内 + 小程序 in-app 共用）。
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationLog(Base):
    """Record of outbound notifications.

    recipient_type 区分两端：
      - erp_user: 指向 users 表（recipient 字段存 user_id）；ERP 路由查询
      - mall_user: 小程序用户；mall_user_id 指向 mall_users.id
    """

    __tablename__ = "notification_logs"
    __table_args__ = (
        # 覆盖 mall workspace 查询：WHERE recipient_type='mall_user' AND mall_user_id=? ORDER BY created_at DESC
        Index(
            "ix_notif_mall_user_created",
            "recipient_type",
            "mall_user_id",
            "created_at",
        ),
        Index("ix_notif_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    recipient: Mapped[str] = mapped_column(String(200), nullable=False)

    # erp_user 默认；mall 侧设 mall_user
    recipient_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="erp_user"
    )
    mall_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    related_entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    # unread / read / pending / sent / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
