"""
Pydantic v2 schemas for Customer and Receivable.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CustomerBase(BaseModel):
    code: str
    name: str
    customer_type: str = "channel"
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_address: Optional[str] = None
    settlement_mode: str = "cash"
    credit_days: int = 0
    credit_limit: float = 0.0
    salesman_id: Optional[str] = None
    notes: Optional[str] = None


class CustomerCreate(CustomerBase):
    # 归属品牌（salesman 建客户时必填；boss/admin 建时可选，稍后在品牌绑定页设）
    brand_id: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    customer_type: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_address: Optional[str] = None
    settlement_mode: Optional[str] = None
    credit_days: Optional[int] = None
    credit_limit: Optional[float] = None
    salesman_id: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_type: str = "channel"
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
