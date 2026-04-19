"""
User, Role, and Employee models.
"""
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    ApprovalMode,
    Base,
    ClaimRecordStatus,
    ClaimStatusEnum,
    CostAllocationMode,
    CustomerSettlementMode,
    EmployeeStatus,
    ExecutionStatus,
    ExpenseStatus,
    InspectionCaseStatus,
    InspectionCaseType,
    InventoryBarcodeStatus,
    InventoryBarcodeType,
    ManufacturerExternalStatus,
    OrderPaymentMethod,
    OrderStatus,
    PayeeType,
    PaymentRequestStatus,
    PaymentStatus,
    PaymentType,
    PolicyRequestSource,
    PolicyRequestStatus,
    PurchaseOrderPaymentStatus,
    PurchasePaymentMethod,
    PurchaseStatus,
    SupplierType,
    UserRoleCode,
    WarehouseType,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.order import Order
    from app.models.product import Warehouse


# =============================================================================
# User & Auth Models
# =============================================================================

class User(Base):
    """System user account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", back_populates="user", lazy="selectin"
    )
    roles: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="user", lazy="selectin"
    )


class Role(Base):
    """Role definition."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    users: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="role", lazy="selectin"
    )


class UserRole(Base):
    """Many-to-many association between users and roles."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    user: Mapped["User"] = relationship("User", back_populates="roles")
    role: Mapped["Role"] = relationship("Role", back_populates="users")


class EmployeeBrand(Base):
    """Many-to-many: employee manages multiple brands."""

    __tablename__ = "employee_brands"
    __table_args__ = (
        UniqueConstraint("employee_id", "brand_id", name="uq_employee_brand"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")


class Employee(Base):
    """Employee record."""

    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    employee_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    open_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    hire_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    leave_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # 个人差异项（底薪、全勤奖走 BrandSalaryScheme 主属品牌×岗位）
    social_security: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    company_social_security: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    expected_manufacturer_subsidy: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(
        String(20),
        default=EmployeeStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="employee", uselist=False
    )


# =============================================================================
# KPI & Commission Models
# =============================================================================


class KPI(Base):
    """Employee KPI tracking record."""

    __tablename__ = "kpis"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_value: Mapped[str] = mapped_column(String(20), nullable=False)
    kpi_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    actual_value: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id], lazy="selectin"
    )


class Commission(Base):
    """Sales commission record."""

    __tablename__ = "commissions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id], lazy="selectin"
    )
    order: Mapped[Optional["Order"]] = relationship(
        "Order", foreign_keys=[order_id], lazy="selectin"
    )
