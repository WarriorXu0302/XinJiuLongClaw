"""
Pydantic v2 schemas for PurchaseOrder and PurchaseOrderItem.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import PurchasePaymentMethod, PurchaseStatus


class PurchaseOrderItemBase(BaseModel):
    product_id: str
    quantity: int = 0
    unit_price: Decimal = Decimal("0.00")


class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass


class PurchaseOrderItemResponse(PurchaseOrderItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    po_id: str
    created_at: datetime


class PurchaseOrderBase(BaseModel):
    supplier_id: str
    warehouse_id: Optional[str] = None
    payment_method: str = PurchasePaymentMethod.SUPPLIER_CASH
    expected_date: Optional[date] = None
    notes: Optional[str] = None


class PurchaseOrderCreate(PurchaseOrderBase):
    items: list[PurchaseOrderItemCreate] = []


class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    payment_method: Optional[str] = None
    total_amount: Optional[Decimal] = None
    paid_amount: Optional[Decimal] = None
    status: Optional[str] = None
    expected_date: Optional[date] = None
    actual_date: Optional[date] = None
    notes: Optional[str] = None


class PurchaseOrderResponse(PurchaseOrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    po_no: str
    total_amount: Decimal
    paid_amount: Decimal
    status: str
    actual_date: Optional[date] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: list[PurchaseOrderItemResponse] = []
