"""
Audit log model — records sensitive system actions for compliance.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Immutable audit trail for sensitive operations."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    # 业务员/消费者等 mall_user 发起的操作用此列；FK 强约束。
    # actor_type 决定该选 actor_id 还是 mall_user_id：
    #   'employee' → actor_id 指向 employees.id
    #   'mall_user' → mall_user_id 指向 mall_users.id
    mall_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(20), default="employee", nullable=False
    )
    changes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
