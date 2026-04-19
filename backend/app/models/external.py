"""
External identity binding model for manufacturer staff.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ManufacturerExternalStatus

if TYPE_CHECKING:
    from app.models.product import Supplier


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
    bound_at: Mapped[datetime] = mapped_column(server_default="now()")
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    manufacturer: Mapped["Supplier"] = relationship("Supplier", lazy="selectin")
