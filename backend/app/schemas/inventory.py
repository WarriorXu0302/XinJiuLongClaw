"""
Pydantic v2 schemas for Inventory, InventoryBarcode,
StockOutAllocation, and StockFlow.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.base import (
    CostAllocationMode,
    InventoryBarcodeStatus,
    InventoryBarcodeType,
)


# =============================================================================
# Inventory
# =============================================================================

class InventoryBase(BaseModel):
    product_id: str
    warehouse_id: str
    batch_no: str
    quantity: int = 0
    cost_price: Decimal


class InventoryCreate(InventoryBase):
    stock_in_date: Optional[datetime] = None
    source_purchase_order_id: Optional[str] = None


class InventoryUpdate(BaseModel):
    quantity: Optional[int] = None
    cost_price: Optional[Decimal] = None
    stock_in_date: Optional[datetime] = None
    source_purchase_order_id: Optional[str] = None


class InventoryResponse(InventoryBase):
    model_config = ConfigDict(from_attributes=True)

    stock_in_date: Optional[datetime] = None
    source_purchase_order_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# InventoryBarcode
# =============================================================================

class InventoryBarcodeBase(BaseModel):
    barcode: str
    barcode_type: str = InventoryBarcodeType.CASE
    product_id: str
    warehouse_id: str
    batch_no: str


class InventoryBarcodeCreate(InventoryBarcodeBase):
    stock_in_id: Optional[str] = None
    parent_barcode: Optional[str] = None


class InventoryBarcodeUpdate(BaseModel):
    barcode_type: Optional[str] = None
    warehouse_id: Optional[str] = None
    batch_no: Optional[str] = None
    status: Optional[str] = None
    parent_barcode: Optional[str] = None
    outbound_stock_flow_id: Optional[str] = None


class InventoryBarcodeResponse(InventoryBarcodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stock_in_id: Optional[str] = None
    parent_barcode: Optional[str] = None
    status: str
    outbound_stock_flow_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# StockOutAllocation
# =============================================================================

class StockOutAllocationBase(BaseModel):
    order_item_id: str
    batch_no: str
    allocated_quantity: int = 0
    allocated_cost_price: Decimal
    cost_allocation_mode: str = CostAllocationMode.FIFO_FALLBACK


class StockOutAllocationCreate(StockOutAllocationBase):
    stock_flow_id: Optional[str] = None


class StockOutAllocationUpdate(BaseModel):
    allocated_quantity: Optional[int] = None
    allocated_cost_price: Optional[Decimal] = None
    cost_allocation_mode: Optional[str] = None


class StockOutAllocationResponse(StockOutAllocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stock_flow_id: Optional[str] = None
    created_at: datetime


# =============================================================================
# StockFlow
# =============================================================================

class StockFlowBase(BaseModel):
    product_id: str
    warehouse_id: str
    batch_no: str
    flow_type: str
    quantity: int = 0
    cost_price: Optional[Decimal] = None


class StockFlowCreate(StockFlowBase):
    source_order_id: Optional[str] = None
    reference_no: Optional[str] = None
    operator_id: Optional[str] = None
    notes: Optional[str] = None


class StockFlowUpdate(BaseModel):
    quantity: Optional[int] = None
    cost_price: Optional[Decimal] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None


class _ProductBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    bottles_per_case: Optional[int] = 1


class _WarehouseBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    warehouse_type: Optional[str] = None


class StockFlowResponse(StockFlowBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_no: str
    source_order_id: Optional[str] = None
    reference_no: Optional[str] = None
    operator_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    product: Optional[_ProductBrief] = None
    warehouse: Optional[_WarehouseBrief] = None
