"""mall M2: 商品 + 仓储 + 内容表

Revision ID: m2a1mallcatalog
Revises: m1a1mallinitial
Create Date: 2026-04-29

建表：
  - mall_categories / mall_product_tags / mall_product_tag_rels
  - mall_products / mall_product_skus / mall_collections
  - mall_warehouses / mall_inventory / mall_inventory_flows
  - mall_notices
"""
from alembic import op
import sqlalchemy as sa


revision = "m2a1mallcatalog"
down_revision = "m1a1mallinitial"
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # mall_categories（自引用 FK，建表 + 后加 FK）
    # =========================================================================
    op.create_table(
        "mall_categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parent_id", sa.Integer, nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_mall_categories_parent",
        "mall_categories", "mall_categories",
        ["parent_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_mall_categories_parent", "mall_categories", ["parent_id"])
    op.create_index(
        "ix_mall_categories_status_sort", "mall_categories",
        ["status", "sort_order"],
    )

    # =========================================================================
    # mall_product_tags
    # =========================================================================
    op.create_table(
        "mall_product_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_mall_product_tags_status_sort", "mall_product_tags",
        ["status", "sort_order"],
    )

    # =========================================================================
    # mall_products
    # =========================================================================
    op.create_table(
        "mall_products",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_product_id", sa.String(36),
                  sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("brand_id", sa.String(36),
                  sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("category_id", sa.Integer,
                  sa.ForeignKey("mall_categories.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brief", sa.String(500), nullable=True),
        sa.Column("main_image", sa.String(500), nullable=True),
        sa.Column("images", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("detail_html", sa.Text, nullable=True),
        sa.Column("min_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_sales", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_products_category", "mall_products", ["category_id"])
    op.create_index("ix_mall_products_brand", "mall_products", ["brand_id"])
    op.create_index("ix_mall_products_status", "mall_products", ["status"])
    op.create_index("ix_mall_products_source", "mall_products", ["source_product_id"])

    # =========================================================================
    # mall_product_skus
    # =========================================================================
    op.create_table(
        "mall_product_skus",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("cost_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("image", sa.String(500), nullable=True),
        sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_product_skus_product", "mall_product_skus", ["product_id"])
    op.create_index("ix_mall_product_skus_status", "mall_product_skus", ["status"])
    op.create_index("ix_mall_product_skus_barcode", "mall_product_skus", ["barcode"])

    # =========================================================================
    # mall_product_tag_rels（依赖 tags + products）
    # =========================================================================
    op.create_table(
        "mall_product_tag_rels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tag_id", sa.Integer,
                  sa.ForeignKey("mall_product_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("tag_id", "product_id", name="uq_mall_product_tag_rel"),
    )
    op.create_index("ix_mall_product_tag_rels_product", "mall_product_tag_rels", ["product_id"])

    # =========================================================================
    # mall_collections
    # =========================================================================
    op.create_table(
        "mall_collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "product_id", name="uq_mall_collections_user_prod"),
    )
    op.create_index("ix_mall_collections_user", "mall_collections", ["user_id"])

    # =========================================================================
    # mall_warehouses
    # =========================================================================
    op.create_table(
        "mall_warehouses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("manager_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_warehouses_code", "mall_warehouses", ["code"], unique=True)
    op.create_index("ix_mall_warehouses_manager", "mall_warehouses", ["manager_user_id"])

    # =========================================================================
    # mall_inventory
    # =========================================================================
    op.create_table(
        "mall_inventory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("warehouse_id", sa.String(36),
                  sa.ForeignKey("mall_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Integer,
                  sa.ForeignKey("mall_product_skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_cost_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("warehouse_id", "sku_id", name="uq_mall_inventory_wh_sku"),
    )
    op.create_index("ix_mall_inventory_sku", "mall_inventory", ["sku_id"])

    # =========================================================================
    # mall_inventory_flows
    # =========================================================================
    op.create_table(
        "mall_inventory_flows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("inventory_id", sa.String(36),
                  sa.ForeignKey("mall_inventory.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("flow_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("cost_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("ref_type", sa.String(30), nullable=True),
        sa.Column("ref_id", sa.String(36), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mall_inventory_flows_inv", "mall_inventory_flows", ["inventory_id"])
    op.create_index("ix_mall_inventory_flows_type", "mall_inventory_flows", ["flow_type"])
    op.create_index(
        "ix_mall_inventory_flows_ref", "mall_inventory_flows",
        ["ref_type", "ref_id"],
    )

    # =========================================================================
    # mall_notices
    # =========================================================================
    op.create_table(
        "mall_notices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_notices_status_sort", "mall_notices", ["status", "sort_order"])
    op.create_index("ix_mall_notices_publish", "mall_notices", ["publish_at"])


def downgrade():
    for ix in ["ix_mall_notices_publish", "ix_mall_notices_status_sort"]:
        op.drop_index(ix, table_name="mall_notices")
    op.drop_table("mall_notices")

    for ix in ["ix_mall_inventory_flows_ref", "ix_mall_inventory_flows_type", "ix_mall_inventory_flows_inv"]:
        op.drop_index(ix, table_name="mall_inventory_flows")
    op.drop_table("mall_inventory_flows")

    op.drop_index("ix_mall_inventory_sku", table_name="mall_inventory")
    op.drop_table("mall_inventory")

    for ix in ["ix_mall_warehouses_manager", "ix_mall_warehouses_code"]:
        op.drop_index(ix, table_name="mall_warehouses")
    op.drop_table("mall_warehouses")

    op.drop_index("ix_mall_collections_user", table_name="mall_collections")
    op.drop_table("mall_collections")

    op.drop_index("ix_mall_product_tag_rels_product", table_name="mall_product_tag_rels")
    op.drop_table("mall_product_tag_rels")

    for ix in ["ix_mall_product_skus_barcode", "ix_mall_product_skus_status", "ix_mall_product_skus_product"]:
        op.drop_index(ix, table_name="mall_product_skus")
    op.drop_table("mall_product_skus")

    for ix in ["ix_mall_products_source", "ix_mall_products_status", "ix_mall_products_brand", "ix_mall_products_category"]:
        op.drop_index(ix, table_name="mall_products")
    op.drop_table("mall_products")

    op.drop_index("ix_mall_product_tags_status_sort", table_name="mall_product_tags")
    op.drop_table("mall_product_tags")

    for ix in ["ix_mall_categories_status_sort", "ix_mall_categories_parent"]:
        op.drop_index(ix, table_name="mall_categories")
    op.drop_constraint("fk_mall_categories_parent", "mall_categories", type_="foreignkey")
    op.drop_table("mall_categories")
