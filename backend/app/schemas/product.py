"""
Pydantic v2 schemas for Product and Brand.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProductBase(BaseModel):
    code: str
    name: str
    category: str = "liquor"  # liquor/gift/material/other
    brand_id: Optional[str] = None
    unit: str = "瓶"
    bottles_per_case: int = 6
    purchase_price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    barcode: Optional[str] = None
    spec: Optional[str] = None
    notes: Optional[str] = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    brand_id: Optional[str] = None
    unit: Optional[str] = None
    bottles_per_case: Optional[int] = None
    purchase_price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    barcode: Optional[str] = None
    spec: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
