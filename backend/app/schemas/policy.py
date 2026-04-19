"""
Pydantic v2 schemas for PolicyRequest, PolicyUsageRecord,
PolicyClaim, PolicyClaimItem, and ClaimSettlementLink.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import (
    AdvancePayerType,
    ApprovalMode,
    ClaimRecordStatus,
    ClaimStatusEnum,
    ExecutionStatus,
    PolicyRequestSource,
    PolicyRequestStatus,
)


# =============================================================================
# PolicyRequest
# =============================================================================

class PolicyRequestBase(BaseModel):
    request_source: str = PolicyRequestSource.ORDER
    approval_mode: str = ApprovalMode.INTERNAL_ONLY
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    target_name: Optional[str] = None
    usage_purpose: Optional[str] = None
    brand_id: Optional[str] = None
    policy_id: Optional[str] = None
    scheme_no: Optional[str] = None


class PolicyRequestItemCreate(BaseModel):
    benefit_type: str
    name: str
    quantity: int = 1
    quantity_unit: str = "次"
    standard_unit_value: Decimal = Decimal("0.00")
    unit_value: Decimal = Decimal("0.00")
    product_id: Optional[str] = None
    is_material: bool = False
    fulfill_mode: str = "claim"
    advance_payer_type: Optional[str] = None
    advance_payer_id: Optional[str] = None
    sort_order: int = 0


class PolicyItemExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    cost_amount: Decimal = Decimal("0.00")
    payer_type: Optional[str] = None
    reimburse_amount: Decimal = Decimal("0.00")
    reimburse_status: str = "pending"
    profit_loss: Decimal = Decimal("0.00")


class PolicyRequestItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    benefit_type: str
    name: str
    quantity: int
    standard_unit_value: Decimal = Decimal("0.00")
    standard_total: Decimal = Decimal("0.00")
    unit_value: Decimal
    total_value: Decimal
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    is_material: bool
    advance_payer_type: Optional[str] = None
    advance_payer_id: Optional[str] = None
    fulfill_status: str = "pending"
    applied_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None
    settled_amount: Decimal = Decimal("0.00")
    stock_flow_id: Optional[str] = None
    notes: Optional[str] = None
    sort_order: int = 0
    expenses: list[PolicyItemExpenseResponse] = []


class PolicyRequestCreate(PolicyRequestBase):
    policy_version_id: Optional[str] = None
    policy_snapshot: Optional[dict[str, Any]] = None
    material_items: Optional[list[dict[str, Any]]] = None
    policy_template_id: Optional[str] = None
    total_policy_value: Optional[Decimal] = None
    total_gap: Optional[Decimal] = None
    settlement_mode: Optional[str] = None
    request_items: Optional[list[PolicyRequestItemCreate]] = None


class PolicyRequestUpdate(BaseModel):
    request_source: Optional[str] = None
    approval_mode: Optional[str] = None
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    target_name: Optional[str] = None
    usage_purpose: Optional[str] = None
    brand_id: Optional[str] = None
    policy_id: Optional[str] = None
    policy_version_id: Optional[str] = None
    policy_snapshot: Optional[dict[str, Any]] = None
    material_items: Optional[list[dict[str, Any]]] = None
    policy_template_id: Optional[str] = None
    total_policy_value: Optional[Decimal] = None
    total_gap: Optional[Decimal] = None
    settlement_mode: Optional[str] = None
    scheme_no: Optional[str] = None
    status: Optional[str] = None
    internal_approved_by: Optional[str] = None
    manufacturer_approved_by: Optional[str] = None


class PolicyRequestResponse(PolicyRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_version_id: Optional[str] = None
    policy_snapshot: Optional[dict[str, Any]] = None
    material_items: Optional[list[dict[str, Any]]] = None
    policy_template_id: Optional[str] = None
    total_policy_value: Optional[Decimal] = None
    total_gap: Optional[Decimal] = None
    settlement_mode: Optional[str] = None
    internal_approved_by: Optional[str] = None
    manufacturer_approved_by: Optional[str] = None
    status: str
    brand_id: Optional[str] = None
    request_items: list[PolicyRequestItemResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# PolicyUsageRecord
# =============================================================================

class PolicyUsageRecordBase(BaseModel):
    policy_request_id: str
    benefit_item_type: str
    usage_scene: Optional[str] = None
    usage_applicant_id: Optional[str] = None
    planned_amount: Decimal = Decimal("0.00")
    actual_amount: Decimal = Decimal("0.00")
    reimbursement_amount: Decimal = Decimal("0.00")
    advance_payer_type: Optional[str] = None
    advance_employee_id: Optional[str] = None
    advance_customer_id: Optional[str] = None
    advance_company_account_id: Optional[str] = None
    surplus_handling_type: Optional[str] = None


class PolicyUsageRecordCreate(PolicyUsageRecordBase):
    pass


class PolicyUsageRecordUpdate(BaseModel):
    benefit_item_type: Optional[str] = None
    usage_scene: Optional[str] = None
    usage_applicant_id: Optional[str] = None
    planned_amount: Optional[Decimal] = None
    actual_amount: Optional[Decimal] = None
    reimbursement_amount: Optional[Decimal] = None
    advance_payer_type: Optional[str] = None
    advance_employee_id: Optional[str] = None
    advance_customer_id: Optional[str] = None
    advance_company_account_id: Optional[str] = None
    surplus_handling_type: Optional[str] = None
    execution_status: Optional[str] = None
    claim_status: Optional[str] = None


class PolicyUsageRecordResponse(PolicyUsageRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_status: str
    claim_status: str
    surplus_handling_type: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# PolicyClaimItem
# =============================================================================

class PolicyClaimItemBase(BaseModel):
    source_usage_record_id: Optional[str] = None
    source_request_item_id: Optional[str] = None
    declared_amount: Decimal = Decimal("0.00")
    approved_amount: Decimal = Decimal("0.00")
    advance_payer_type_snapshot: Optional[str] = None
    advance_payer_employee_snapshot: Optional[str] = None
    advance_payer_customer_snapshot: Optional[str] = None
    advance_payer_company_snapshot: Optional[str] = None


class PolicyClaimItemCreate(PolicyClaimItemBase):
    pass


class PolicyClaimItemUpdate(BaseModel):
    declared_amount: Optional[Decimal] = None
    approved_amount: Optional[Decimal] = None


class PolicyClaimItemResponse(PolicyClaimItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    source_request_item_id: Optional[str] = None
    created_at: datetime


# =============================================================================
# PolicyClaim
# =============================================================================

class PolicyClaimBase(BaseModel):
    manufacturer_id: Optional[str] = None
    brand_id: Optional[str] = None
    claim_batch_period: str
    notes: Optional[str] = None


class PolicyClaimCreate(PolicyClaimBase):
    items: list[PolicyClaimItemCreate] = []


class PolicyClaimUpdate(BaseModel):
    manufacturer_id: Optional[str] = None
    brand_id: Optional[str] = None
    claim_batch_period: Optional[str] = None
    claim_amount: Optional[Decimal] = None
    approved_total_amount: Optional[Decimal] = None
    settled_amount: Optional[Decimal] = None
    unsettled_amount: Optional[Decimal] = None
    status: Optional[str] = None
    claimed_by: Optional[str] = None
    notes: Optional[str] = None


class PolicyClaimResponse(PolicyClaimBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_no: str
    claim_amount: Decimal
    approved_total_amount: Decimal
    settled_amount: Decimal
    unsettled_amount: Decimal
    status: str
    submitted_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: list[PolicyClaimItemResponse] = []


# =============================================================================
# ClaimSettlementLink
# =============================================================================

class ClaimSettlementLinkBase(BaseModel):
    claim_id: str
    settlement_id: str
    allocated_amount: Decimal


class ClaimSettlementLinkCreate(ClaimSettlementLinkBase):
    confirmed_by: Optional[str] = None


class ClaimSettlementLinkUpdate(BaseModel):
    allocated_amount: Optional[Decimal] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None


class ClaimSettlementLinkResponse(ClaimSettlementLinkBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
