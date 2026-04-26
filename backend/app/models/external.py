"""
External identity binding models.

- ManufacturerExternalIdentity：飞书 open_id ↔ 厂家，用于厂家外部审批
- FeishuBinding：飞书 open_id ↔ ERP 内部员工账号，用于飞书 Agent 代员工操控 ERP
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ManufacturerExternalStatus

if TYPE_CHECKING:
    from app.models.product import Supplier
    from app.models.user import User


class ManufacturerExternalIdentity(Base):
    """Manufacturer external identity binding — maps Feishu open_id to manufacturer.
    Used for headless external approval and policy scheme number backfill.
    """

    __tablename__ = "manufacturer_external_identities"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    open_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    manufacturer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id"), nullable=False
    )
    brand_scope: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=ManufacturerExternalStatus.ACTIVE,
        nullable=False,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    bound_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    manufacturer: Mapped["Supplier"] = relationship("Supplier", lazy="selectin")


class FeishuBinding(Base):
    """飞书 open_id ↔ ERP 用户 绑定表。

    员工在飞书里对 Bot 发 `/bind 用户名 密码` → 后端校验密码 → 落一行。
    此后飞书 Ingress 用 open_id 向 /api/feishu/exchange-token 换短期 JWT，
    代这个员工调 /mcp 工具。

    - 一个 open_id 只能绑定一个 user_id（open_id unique）
    - 同一个 user_id 理论上也只绑一个 open_id（员工只有一个飞书账号）——用 unique 约束兜底
    - is_active=False 等于"解绑"；保留历史记录便于审计
    """

    __tablename__ = "feishu_bindings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    open_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    unbind_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship("User", lazy="selectin")
