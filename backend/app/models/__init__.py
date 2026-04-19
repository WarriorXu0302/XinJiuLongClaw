"""
ORM models package.
Import all models here to make them available via `from app.models import ...`.
"""
from app.models.base import Base

from app.models.user import Employee, Role, User, UserRole
from app.models.customer import Customer, Receivable
from app.models.product import (
    Account,
    Brand,
    Product,
    Supplier,
    Warehouse,
)
from app.models.order import Order, OrderItem
from app.models.inventory import (
    Inventory,
    InventoryBarcode,
    StockFlow,
    StockOutAllocation,
)
from app.models.policy_template import PolicyTemplate, PolicyAdjustment
from app.models.policy_template_benefit import PolicyTemplateBenefit
from app.models.policy_request_item import PolicyRequestItem
from app.models.policy_item_expense import PolicyItemExpense
from app.models.policy import (
    ClaimSettlementLink,
    PolicyClaim,
    PolicyClaimItem,
    PolicyRequest,
    PolicyUsageRecord,
)
from app.models.finance import (
    Expense,
    ExpenseCategory,
    FinancePaymentRequest,
    ManufacturerSettlement,
    Payment,
    Receipt,
)
from app.models.tasting import TastingWineUsage
from app.models.inspection import InspectionCase, MarketCleanupCase
from app.models.external import ManufacturerExternalIdentity
from app.models.audit_log import AuditLog
from app.models.notification_log import NotificationLog
from app.models.financing import FinancingOrder, FinancingRepayment
from app.models.expense_claim import ExpenseClaim

__all__ = [
    "Base",
    # User & Auth
    "User",
    "Role",
    "UserRole",
    "Employee",
    # Customer
    "Customer",
    "Receivable",
    # Product
    "Brand",
    "Product",
    "Warehouse",
    "Account",
    "Supplier",
    # Order
    "Order",
    "OrderItem",
    # Inventory
    "Inventory",
    "InventoryBarcode",
    "StockFlow",
    "StockOutAllocation",
    # Policy
    "PolicyTemplate",
    "PolicyAdjustment",
    "PolicyTemplateBenefit",
    "PolicyRequestItem",
    "PolicyItemExpense",
    "PolicyRequest",
    "PolicyUsageRecord",
    "PolicyClaim",
    "PolicyClaimItem",
    "ClaimSettlementLink",
    # Finance
    "Receipt",
    "Payment",
    "Expense",
    "ExpenseCategory",
    "ManufacturerSettlement",
    "FinancePaymentRequest",
    # Tasting
    "TastingWineUsage",
    # Inspection
    "InspectionCase",
    "MarketCleanupCase",
    # External
    "ManufacturerExternalIdentity",
    # Audit & Notification
    "AuditLog",
    "NotificationLog",
    # Financing
    "FinancingOrder",
    "FinancingRepayment",
    "ExpenseClaim",
]
