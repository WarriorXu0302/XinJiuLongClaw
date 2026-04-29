"""Mall 购物车 schemas。"""
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.mall.pricing_service import mask_price


class MallCartChangeItemRequest(BaseModel):
    """对齐 mall4j /p/shopCart/changeItem：`count` 可正可负（加减数量），0 = 删除。"""
    count: int
    prod_id: int = Field(alias="prodId")
    sku_id: int = Field(alias="skuId")
    model_config = ConfigDict(populate_by_name=True)


class MallCartItemVO(BaseModel):
    """购物车条目（含 SKU 快照 + 价格）。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    basket_id: str = Field(alias="id", serialization_alias="basketId")
    prod_id: int = Field(alias="product_id", serialization_alias="prodId")
    sku_id: int = Field(serialization_alias="skuId")
    prod_name: Optional[str] = Field(default=None, serialization_alias="prodName")
    sku_name: Optional[str] = Field(default=None, serialization_alias="skuName")
    pic: Optional[str] = None
    price: Optional[Decimal] = None
    quantity: int = Field(serialization_alias="count")
    selected: bool = True

    @field_serializer("price", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


class MallCartInfoVO(BaseModel):
    """整个购物车。对齐 mall4j /p/shopCart/info 响应。"""
    records: List[MallCartItemVO]
    total: int
    total_price: Optional[Decimal] = Field(default=None, serialization_alias="totalPrice")

    @field_serializer("total_price", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)
