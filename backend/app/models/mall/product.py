"""
Mall 商品相关模型。

- MallCategory       分类树（Integer 自增 PK，契合小程序 categoryId 字段）
- MallProductTag     首页楼层/标签（Integer 自增 PK）
- MallProductTagRel  tag ↔ product 多对多
- MallProduct        商品主表（Integer 自增 PK = prodId）
- MallProductSku     SKU（Integer 自增 PK = skuId）
- MallCollection     收藏（UniqueConstraint(user_id, product_id)）

价格脱敏不在 ORM 层做，由 Pydantic response serializer 按 ContextVar 决定是否 null 化。
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mall.base import MallProductStatus


# =============================================================================
# MallCategory
# =============================================================================

class MallCategory(Base):
    """商品分类树。parent_id=NULL 为一级分类。"""

    __tablename__ = "mall_categories"
    __table_args__ = (
        Index("ix_mall_categories_parent", "parent_id"),
        Index("ix_mall_categories_status_sort", "status", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("mall_categories.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallProductTag + rel
# =============================================================================

class MallProductTag(Base):
    """首页楼层/标签（"新品"、"热卖"、"白酒楼层" 等）。"""

    __tablename__ = "mall_product_tags"
    __table_args__ = (
        Index("ix_mall_product_tags_status_sort", "status", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MallProductTagRel(Base):
    """tag ↔ product 多对多关联。"""

    __tablename__ = "mall_product_tag_rels"
    __table_args__ = (
        UniqueConstraint("tag_id", "product_id", name="uq_mall_product_tag_rel"),
        Index("ix_mall_product_tag_rels_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_tags.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# =============================================================================
# MallProduct
# =============================================================================

class MallProduct(Base):
    """商品主表（小程序 prodId = 本表 id）。

    - source_product_id：指向 ERP products.id；NULL = 纯商城 SKU
    - brand_id：用于利润/提成分账
    """

    __tablename__ = "mall_products"
    __table_args__ = (
        Index("ix_mall_products_category", "category_id"),
        Index("ix_mall_products_brand", "brand_id"),
        Index("ix_mall_products_status", "status"),
        Index("ix_mall_products_source", "source_product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    source_product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("mall_categories.id"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brief: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    main_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    images: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    detail_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 展示用价格区间（从 SKU 计算回填；脱敏在 schema 层做）
    min_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    max_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    total_sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MallProductStatus.DRAFT.value
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallProductSku
# =============================================================================

class MallProductSku(Base):
    """SKU。纯商城 SKU（source_product_id=NULL）必填 cost_price。"""

    __tablename__ = "mall_product_skus"
    __table_args__ = (
        Index("ix_mall_product_skus_product", "product_id"),
        Index("ix_mall_product_skus_status", "status"),
        Index("ix_mall_product_skus_barcode", "barcode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False
    )
    spec: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # 纯商城 SKU 必填；source_product_id 不为空时 cost 从 ERP 成本溯源
    cost_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallCollection
# =============================================================================

class MallCollection(Base):
    """C 端用户收藏。"""

    __tablename__ = "mall_collections"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_mall_collections_user_prod"),
        Index("ix_mall_collections_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
