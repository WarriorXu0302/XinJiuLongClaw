"""
Pydantic v2 schemas for TastingWineUsage.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# TastingWineUsage
# =============================================================================


class TastingWineUsageBase(BaseModel):
    source_usage_record_id: str
    usage_type: str
    product_id: Optional[str] = None
    quantity: int = 0
    batch_no: Optional[str] = None
    stock_flow_id: Optional[str] = None
    target_warehouse_id: Optional[str] = None
    into_company_backup_stock: bool = False
    notes: Optional[str] = None


class TastingWineUsageCreate(TastingWineUsageBase):
    pass


class TastingWineUsageUpdate(BaseModel):
    source_usage_record_id: Optional[str] = None
    usage_type: Optional[str] = None
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    batch_no: Optional[str] = None
    stock_flow_id: Optional[str] = None
    target_warehouse_id: Optional[str] = None
    into_company_backup_stock: Optional[bool] = None
    notes: Optional[str] = None


class TastingWineUsageResponse(TastingWineUsageBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
