"""
Pydantic v2 schemas for InspectionCase and MarketCleanupCase.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import InspectionCaseStatus, InspectionCaseType, MarketCleanupStatus


# =============================================================================
# InspectionCase
# =============================================================================

class InspectionCaseBase(BaseModel):
    case_type: str = InspectionCaseType.INSPECTION_VIOLATION
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    batch_no: Optional[str] = None
    product_id: Optional[str] = None
    brand_id: Optional[str] = None
    found_location: Optional[str] = None
    found_time: Optional[datetime] = None
    found_by: Optional[str] = None
    original_order_id: Optional[str] = None
    original_customer_id: Optional[str] = None
    original_sale_price: Optional[Decimal] = None
    recovery_price: Optional[Decimal] = None
    manufacturer_price: Optional[Decimal] = None
    penalty_amount: Decimal = Decimal("0.00")
    rebate_deduction_amount: Decimal = Decimal("0.00")
    into_backup_stock: bool = False
    backup_stock_cost: Optional[Decimal] = None
    direction: str = "outflow"
    quantity: int = 0
    quantity_unit: str = "瓶"
    purchase_price: Decimal = Decimal("0.00")
    resell_price: Decimal = Decimal("0.00")
    transfer_amount: Decimal = Decimal("0.00")
    rebate_loss: Decimal = Decimal("0.00")
    reward_amount: Decimal = Decimal("0.00")
    profit_loss: Decimal = Decimal("0.00")
    counterparty: Optional[str] = None
    no_rebate: bool = False
    voucher_urls: Optional[list[str]] = None
    notes: Optional[str] = None


class InspectionCaseCreate(InspectionCaseBase):
    pass


class InspectionCaseUpdate(BaseModel):
    case_type: Optional[str] = None
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    batch_no: Optional[str] = None
    product_id: Optional[str] = None
    brand_id: Optional[str] = None
    found_location: Optional[str] = None
    found_time: Optional[datetime] = None
    found_by: Optional[str] = None
    original_order_id: Optional[str] = None
    original_customer_id: Optional[str] = None
    original_sale_price: Optional[Decimal] = None
    recovery_price: Optional[Decimal] = None
    manufacturer_price: Optional[Decimal] = None
    penalty_amount: Optional[Decimal] = None
    rebate_deduction_amount: Optional[Decimal] = None
    into_backup_stock: Optional[bool] = None
    backup_stock_cost: Optional[Decimal] = None
    direction: Optional[str] = None
    quantity: Optional[int] = None
    quantity_unit: Optional[str] = None
    purchase_price: Optional[Decimal] = None
    resell_price: Optional[Decimal] = None
    transfer_amount: Optional[Decimal] = None
    rebate_loss: Optional[Decimal] = None
    reward_amount: Optional[Decimal] = None
    profit_loss: Optional[Decimal] = None
    counterparty: Optional[str] = None
    no_rebate: Optional[bool] = None
    voucher_urls: Optional[list[str]] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ProductBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str

class InspectionCaseResponse(InspectionCaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_no: str
    product: Optional[ProductBrief] = None
    related_inventory_flow_id: Optional[str] = None
    related_payment_id: Optional[str] = None
    status: str
    created_at: datetime
    closed_at: Optional[datetime] = None


# =============================================================================
# MarketCleanupCase
# =============================================================================

class MarketCleanupCaseBase(BaseModel):
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    batch_no: Optional[str] = None
    product_id: Optional[str] = None
    brand_id: Optional[str] = None
    found_location: Optional[str] = None
    found_time: Optional[datetime] = None
    found_by: Optional[str] = None
    buyback_price: Decimal = Decimal("0.00")
    total_buyback_amount: Decimal = Decimal("0.00")
    manufacturer_price: Optional[Decimal] = None
    into_main_warehouse: bool = False
    main_warehouse_id: Optional[str] = None
    rebate_increase_amount: Decimal = Decimal("0.00")
    notes: Optional[str] = None


class MarketCleanupCaseCreate(MarketCleanupCaseBase):
    pass


class MarketCleanupCaseUpdate(BaseModel):
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    batch_no: Optional[str] = None
    product_id: Optional[str] = None
    brand_id: Optional[str] = None
    found_location: Optional[str] = None
    found_time: Optional[datetime] = None
    found_by: Optional[str] = None
    buyback_price: Optional[Decimal] = None
    total_buyback_amount: Optional[Decimal] = None
    manufacturer_price: Optional[Decimal] = None
    into_main_warehouse: Optional[bool] = None
    main_warehouse_id: Optional[str] = None
    rebate_increase_amount: Optional[Decimal] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class MarketCleanupCaseResponse(MarketCleanupCaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_no: str
    related_inventory_flow_id: Optional[str] = None
    related_payment_id: Optional[str] = None
    status: str
    created_at: datetime
    closed_at: Optional[datetime] = None
