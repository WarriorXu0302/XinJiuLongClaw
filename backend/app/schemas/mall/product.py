"""
Mall 商品相关 Pydantic schemas。

字段名通过 serialization_alias 保持小程序 mall4j 契约（prodId/prodName/skuId/categoryId…），
这样第一版小程序模板不用改。

价格字段通过 `mask_price` 在 model_serializer 里按 ContextVar 脱敏。
"""
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.mall.pricing_service import mask_price


# =============================================================================
# 基础 Page
# =============================================================================

class MallPage(BaseModel):
    """小程序统一分页外壳（对齐 mall4j 的 {records,total,pages,current}）。"""
    records: List[Any]
    total: int
    pages: int = 1
    current: int = 1


# =============================================================================
# 分类
# =============================================================================

class MallCategoryVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    category_id: int = Field(alias="id", serialization_alias="categoryId")
    parent_id: Optional[int] = Field(default=None, serialization_alias="parentId")
    category_name: str = Field(alias="name", serialization_alias="categoryName")
    icon: Optional[str] = None
    sort_order: int = Field(default=0, serialization_alias="seq")
    # 预留子节点（递归），默认空
    children: List["MallCategoryVO"] = Field(default_factory=list)


MallCategoryVO.model_rebuild()


# =============================================================================
# 标签
# =============================================================================

class MallTagVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    title: str
    icon: Optional[str] = None


# =============================================================================
# SKU
# =============================================================================

class MallSkuVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    sku_id: int = Field(alias="id", serialization_alias="skuId")
    prod_id: int = Field(alias="product_id", serialization_alias="prodId")
    sku_name: Optional[str] = Field(alias="spec", serialization_alias="skuName", default=None)
    price: Optional[Decimal] = None
    pic: Optional[str] = Field(alias="image", serialization_alias="pic", default=None)
    barcode: Optional[str] = None
    status: str = "active"
    # 库存字段走独立端点（/api/mall/products/{id} 含 skuList 时可选填）
    stocks: Optional[int] = Field(default=None, serialization_alias="stocks")

    @field_serializer("price", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


# =============================================================================
# 商品列表项
# =============================================================================

class MallProductListItemVO(BaseModel):
    """商品列表展示字段（prodList / search 列表共用）。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    prod_id: int = Field(alias="id", serialization_alias="prodId")
    prod_name: str = Field(alias="name", serialization_alias="prodName")
    brief: Optional[str] = None
    pic: Optional[str] = Field(alias="main_image", serialization_alias="pic", default=None)

    price: Optional[Decimal] = Field(alias="min_price", serialization_alias="price", default=None)
    max_price: Optional[Decimal] = Field(default=None, serialization_alias="maxPrice")

    total_sales: int = Field(default=0, serialization_alias="soldNum")
    status: str = "draft"

    @field_serializer("price", "max_price", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


# =============================================================================
# 商品详情
# =============================================================================

class MallProductDetailVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    prod_id: int = Field(alias="id", serialization_alias="prodId")
    prod_name: str = Field(alias="name", serialization_alias="prodName")
    brief: Optional[str] = None
    pic: Optional[str] = Field(alias="main_image", serialization_alias="pic", default=None)
    imgs: Optional[List[str]] = Field(alias="images", serialization_alias="imgs", default=None)
    content: Optional[str] = Field(alias="detail_html", serialization_alias="content", default=None)

    price: Optional[Decimal] = Field(alias="min_price", serialization_alias="price", default=None)
    max_price: Optional[Decimal] = Field(default=None, serialization_alias="maxPrice")

    total_sales: int = Field(default=0, serialization_alias="soldNum")
    brand_id: Optional[str] = Field(default=None, serialization_alias="brandId")
    category_id: Optional[int] = Field(default=None, serialization_alias="categoryId")
    status: str = "draft"

    sku_list: List[MallSkuVO] = Field(default_factory=list, serialization_alias="skuList")

    @field_serializer("price", "max_price", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


# =============================================================================
# 公告
# =============================================================================

class MallNoticeListItemVO(BaseModel):
    """公告列表项（不含正文，减少响应体积）。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    title: str
    publish_at: Optional[Any] = Field(default=None, serialization_alias="publishTime")


class MallNoticeVO(MallNoticeListItemVO):
    """公告详情。"""
    content: Optional[str] = None


# =============================================================================
# 省市区
# =============================================================================

class MallRegionVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    area_code: str = Field(serialization_alias="areaId")
    parent_code: Optional[str] = Field(default=None, serialization_alias="parentId")
    name: str
    level: int
