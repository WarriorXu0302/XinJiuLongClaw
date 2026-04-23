"""
Pydantic v2 schemas for Order and OrderItem.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import OrderPaymentMethod, OrderStatus, PaymentStatus


# =============================================================================
# OrderItem
# =============================================================================

class OrderItemBase(BaseModel):
    product_id: Optional[str] = None
    quantity: int = 0
    quantity_unit: str = "瓶"
    unit_price: Decimal = Decimal("0.00")


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemUpdate(BaseModel):
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[Decimal] = None


class ProductBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str

class OrderItemResponse(OrderItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    cost_price_snapshot: Optional[Decimal] = None
    product: Optional[ProductBrief] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# Order
# =============================================================================

class OrderBase(BaseModel):
    customer_id: Optional[str] = None
    salesman_id: Optional[str] = None
    settlement_mode_snapshot: Optional[str] = None
    notes: Optional[str] = None


class OrderCreate(OrderBase):
    items: list[OrderItemCreate] = []
    policy_template_id: Optional[str] = None  # 可选：不传则按品牌+箱数自动匹配
    settlement_mode: str  # customer_pay / employee_pay / company_pay
    advance_payer_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    deal_unit_price: Optional[Decimal] = None  # 可选覆盖，默认用模板 customer_unit_price


class OrderUpdate(BaseModel):
    customer_id: Optional[str] = None
    salesman_id: Optional[str] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    settlement_mode_snapshot: Optional[str] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[list[OrderItemCreate]] = None


class NameBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str

class OrderResponse(OrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_no: str
    brand_id: Optional[str] = None
    customer: Optional[NameBrief] = None
    salesman: Optional[NameBrief] = None
    total_amount: Decimal
    deal_unit_price: Optional[Decimal] = None
    deal_amount: Optional[Decimal] = None
    policy_template_id: Optional[str] = None
    policy_gap: Optional[Decimal] = None
    policy_value: Optional[Decimal] = None
    policy_surplus: Optional[Decimal] = None
    settlement_mode: Optional[str] = None
    advance_payer_id: Optional[str] = None
    customer_paid_amount: Optional[Decimal] = None
    policy_receivable: Optional[Decimal] = None
    warehouse_id: Optional[str] = None
    delivery_photos: Optional[list[str]] = None
    payment_voucher_urls: Optional[list[str]] = None
    status: str
    payment_status: str
    rejection_reason: Optional[str] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: list[OrderItemResponse] = []
