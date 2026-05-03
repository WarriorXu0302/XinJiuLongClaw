"""
SQLAlchemy 2.0 Declarative Base and shared enum definitions.
All ORM models inherit from `Base`.
"""
import enum
import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    type_annotation_map = {
        uuid.UUID: String(36),
        datetime: DateTime(timezone=True),
    }


# --- Common column type aliases ---
StrPK = Annotated[str, mapped_column(String(36), primary_key=True)]
IntPK = Annotated[int, mapped_column(primary_key=True)]
CreatedAt = Annotated[datetime, mapped_column(server_default=func.now())]
UpdatedAt = Annotated[
    datetime,
    mapped_column(server_default=func.now(), onupdate=func.now()),
]


# =============================================================================
# Enumerations
# =============================================================================

class OrderStatus(str, enum.Enum):
    """Order fulfillment status."""

    PENDING = "pending"
    POLICY_PENDING_INTERNAL = "policy_pending_internal"
    POLICY_PENDING_EXTERNAL = "policy_pending_external"
    APPROVED = "approved"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    REJECTED = "policy_rejected"


class PaymentStatus(str, enum.Enum):
    """Order payment status.

    pending_confirmation 说明：业务员上传了凭证建了 Receipt，
    但财务尚未在审批中心确认。此状态下凭证不动账、订单不锁定。
    财务确认后 Receipt.status=confirmed，根据累计金额转为 partially_paid 或 fully_paid。
    """

    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PENDING_CONFIRMATION = "pending_confirmation"
    FULLY_PAID = "fully_paid"


class OrderPaymentMethod(str, enum.Enum):
    """Payment method for receipts/payments."""

    CASH = "cash"
    BANK = "bank"
    WECHAT = "wechat"
    ALIPAY = "alipay"


class PaymentType(str, enum.Enum):
    """Payment type for payments table."""

    PURCHASE = "purchase"
    EXPENSE = "expense"
    REFUND = "refund"


class AccountType(str, enum.Enum):
    """Account type for financial accounts."""

    CASH = "cash"
    F_CLASS = "f_class"
    FINANCING = "financing"


class PurchasePaymentMethod(str, enum.Enum):
    """Payment method for purchase orders."""

    SUPPLIER_CASH = "supplier_cash"
    MANUFACTURER_CASH_F_CLASS = "manufacturer_cash_f_class"
    MANUFACTURER_FINANCING = "manufacturer_financing"


class PurchaseStatus(str, enum.Enum):
    """Purchase order status."""

    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    SHIPPED = "shipped"
    RECEIVED = "received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PurchaseOrderPaymentStatus(str, enum.Enum):
    """Purchase order payment status."""

    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    FULLY_PAID = "fully_paid"


class PolicyRequestSource(str, enum.Enum):
    """Policy request source."""

    ORDER = "order"
    F_CLASS = "f_class"
    HOSPITALITY = "hospitality"
    MARKET_ACTIVITY = "market_activity"
    MANUAL = "manual"


class ApprovalMode(str, enum.Enum):
    """Approval mode."""

    INTERNAL_ONLY = "internal_only"
    INTERNAL_PLUS_EXTERNAL = "internal_plus_external"


class PolicyRequestStatus(str, enum.Enum):
    """Policy request status."""

    PENDING_INTERNAL = "pending_internal"
    PENDING_EXTERNAL = "pending_external"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(str, enum.Enum):
    """Policy usage execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ClaimStatusEnum(str, enum.Enum):
    """Policy claim status."""

    UNCLAIMED = "unclaimed"
    PARTIALLY_CLAIMED = "partially_claimed"
    FULLY_CLAIMED = "fully_claimed"


class ClaimRecordStatus(str, enum.Enum):
    """Policy claim record (policy_claims) status."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PARTIALLY_SETTLED = "partially_settled"
    SETTLED = "settled"
    REJECTED = "rejected"


class AdvancePayerType(str, enum.Enum):
    """Advance payer type."""

    EMPLOYEE = "employee"
    COMPANY = "company"
    CUSTOMER = "customer"


class PayeeType(str, enum.Enum):
    """Payee type for payment requests."""

    EMPLOYEE = "employee"
    CUSTOMER = "customer"
    OTHER = "other"


class CostAllocationMode(str, enum.Enum):
    """Cost allocation mode for stock out."""

    BARCODE_EXACT = "barcode_exact"
    FIFO_FALLBACK = "fifo_fallback"


class InventoryBarcodeType(str, enum.Enum):
    """Barcode type."""

    CASE = "case"
    BOTTLE = "bottle"


class InventoryBarcodeStatus(str, enum.Enum):
    """Barcode status."""

    IN_STOCK = "in_stock"
    OUTBOUND = "outbound"
    LOCKED = "locked"
    INVALID = "invalid"


class ManufacturerExternalStatus(str, enum.Enum):
    """Manufacturer external identity status."""

    ACTIVE = "active"
    DISABLED = "disabled"


class InspectionCaseType(str, enum.Enum):
    """Inspection case type."""

    INSPECTION_VIOLATION = "inspection_violation"
    INSPECTION_REDEMPTION = "inspection_redemption"
    REBATE_DEDUCTION = "rebate_deduction"


class InspectionCaseStatus(str, enum.Enum):
    """Inspection case status."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    RECOVERED = "recovered"
    PENALTY_PROCESSED = "penalty_processed"
    CLOSED = "closed"


class MarketCleanupStatus(str, enum.Enum):
    """Market cleanup case status."""

    PENDING = "pending"
    BOUGHT_BACK = "bought_back"
    STOCKED_IN = "stocked_in"
    REBATE_RECORDED = "rebate_recorded"
    CLOSED = "closed"


class ExpenseStatus(str, enum.Enum):
    """Expense record status."""

    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"


class PaymentRequestStatus(str, enum.Enum):
    """Payment request status."""

    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class UserRoleCode(str, enum.Enum):
    """User role code."""

    ADMIN = "admin"
    BOSS = "boss"
    FINANCE = "finance"
    SALESMAN = "salesman"
    SALES_MANAGER = "sales_manager"
    WAREHOUSE = "warehouse"
    HR = "hr"
    PURCHASE = "purchase"
    MANUFACTURER_STAFF = "manufacturer_staff"


class EmployeeStatus(str, enum.Enum):
    """Employee status."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    LEFT = "left"


class CustomerSettlementMode(str, enum.Enum):
    """Customer settlement mode."""

    CASH = "cash"
    CREDIT = "credit"


class SupplierType(str, enum.Enum):
    """Supplier type."""

    SUPPLIER = "supplier"
    MANUFACTURER = "manufacturer"


class WarehouseType(str, enum.Enum):
    """Warehouse type."""

    MAIN = "main"
    BACKUP = "backup"
    ACTIVITY = "activity"
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    STORE = "store"        # 专卖店 / 门店仓（青花郎/五粮液/华致名酒库/鑫久酒）
    TASTING = "tasting"    # 品鉴仓（早期业务，warehouses 表已有此值但 enum 漏写，补全）


class FinancingOrderStatus(str, enum.Enum):
    """Financing order lifecycle status."""

    ACTIVE = "active"
    PARTIALLY_REPAID = "partially_repaid"
    FULLY_REPAID = "fully_repaid"
    DEFAULTED = "defaulted"
