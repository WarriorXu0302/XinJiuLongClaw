"""
Pydantic v2 schemas for Receipt, Payment, Expense,
ManufacturerSettlement, and FinancePaymentRequest.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import (
    ExpenseStatus,
    OrderPaymentMethod,
    PayeeType,
    PaymentRequestStatus,
    PaymentType,
)


# =============================================================================
# Receipt
# =============================================================================

class ReceiptBase(BaseModel):
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    account_id: Optional[str] = None
    amount: Decimal
    payment_method: str = OrderPaymentMethod.BANK
    receipt_date: Optional[date] = None
    notes: Optional[str] = None
    source_type: str = "customer"  # customer / employee_advance / company_advance


class ReceiptCreate(ReceiptBase):
    pass


class ReceiptUpdate(BaseModel):
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    account_id: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_method: Optional[str] = None
    receipt_date: Optional[date] = None
    notes: Optional[str] = None


class ReceiptResponse(ReceiptBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    receipt_no: str
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# Payment
# =============================================================================

class PaymentBase(BaseModel):
    payee: str
    account_id: Optional[str] = None
    amount: Decimal
    payment_type: str = PaymentType.EXPENSE
    payment_method: str = OrderPaymentMethod.BANK
    payment_date: Optional[date] = None
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    payee: Optional[str] = None
    account_id: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_type: Optional[str] = None
    payment_method: Optional[str] = None
    payment_date: Optional[date] = None
    notes: Optional[str] = None


class PaymentResponse(PaymentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    payment_no: str
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# Expense
# =============================================================================

class ExpenseBase(BaseModel):
    category_id: Optional[str] = None
    brand_id: Optional[str] = None
    amount: Decimal
    payment_account_id: Optional[str] = None
    reimbursement_account_id: Optional[str] = None
    reimbursement_ratio: Decimal = Decimal("1.000")
    actual_cost: Decimal = Decimal("0.00")
    description: Optional[str] = None
    voucher_urls: Optional[list[str]] = None
    applicant_id: Optional[str] = None
    payment_date: Optional[date] = None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    category_id: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_account_id: Optional[str] = None
    reimbursement_account_id: Optional[str] = None
    reimbursement_ratio: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    description: Optional[str] = None
    applicant_id: Optional[str] = None
    approved_by: Optional[str] = None
    payment_date: Optional[date] = None
    status: Optional[str] = None


class ExpenseResponse(ExpenseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    expense_no: str
    approved_by: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# ManufacturerSettlement
# =============================================================================

class ManufacturerSettlementBase(BaseModel):
    manufacturer_id: Optional[str] = None
    brand_id: Optional[str] = None
    settlement_amount: Decimal
    settlement_date: Optional[date] = None
    notes: Optional[str] = None


class ManufacturerSettlementCreate(ManufacturerSettlementBase):
    approved_claim_amount: Decimal = Decimal("0.00")
    unsettled_amount: Optional[Decimal] = None


class ManufacturerSettlementUpdate(BaseModel):
    manufacturer_id: Optional[str] = None
    brand_id: Optional[str] = None
    settlement_amount: Optional[Decimal] = None
    approved_claim_amount: Optional[Decimal] = None
    settled_amount: Optional[Decimal] = None
    unsettled_amount: Optional[Decimal] = None
    settlement_date: Optional[date] = None
    status: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None


class ManufacturerSettlementResponse(ManufacturerSettlementBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    settlement_no: str
    approved_claim_amount: Decimal
    settled_amount: Decimal
    unsettled_amount: Decimal
    status: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# FinancePaymentRequest (payment_requests table)
# =============================================================================

class PaymentRequestBase(BaseModel):
    source_usage_record_id: Optional[str] = None
    related_claim_id: Optional[str] = None
    payee_type: Optional[str] = None
    payee_employee_id: Optional[str] = None
    payee_customer_id: Optional[str] = None
    payee_other_name: Optional[str] = None
    amount: Decimal
    payable_account_type: Optional[str] = None
    payable_account_id: Optional[str] = None


class PaymentRequestCreate(PaymentRequestBase):
    pass


class PaymentRequestUpdate(BaseModel):
    payee_type: Optional[str] = None
    payee_employee_id: Optional[str] = None
    payee_customer_id: Optional[str] = None
    payee_other_name: Optional[str] = None
    amount: Optional[Decimal] = None
    status: Optional[str] = None
    payable_account_type: Optional[str] = None
    payable_account_id: Optional[str] = None
    approved_by: Optional[str] = None
    paid_at: Optional[datetime] = None


class PaymentRequestResponse(PaymentRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_no: str
    status: str
    approved_by: Optional[str] = None
    payment_voucher_urls: Optional[list[str]] = None
    signed_photo_urls: Optional[list[str]] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
