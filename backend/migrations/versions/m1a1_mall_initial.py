"""mall M1: 初始表 mall_users/mall_addresses/mall_regions/mall_invite_codes/mall_login_logs

Revision ID: m1a1mallinitial
Revises: c9e1a2b3d4f5
Create Date: 2026-04-29

M1 小程序后端基建第一步：建立鉴权所需的 5 张表。

- mall_users：C 端 + 业务员统一表，带 CHECK(user_type='salesman' → linked_employee_id NOT NULL)
- mall_addresses：收货地址
- mall_regions：省市区字典（seed 数据）
- mall_invite_codes：业务员邀请码（2h 一次性，SQL FOR UPDATE 原子消费）
- mall_login_logs：登录日志（保留 90 天）

user_type 完整性触发器 T1/T2 留到 M4 前补一次性 migration，第一版靠 CHECK + 应用层。
"""
from alembic import op
import sqlalchemy as sa


revision = "m1a1mallinitial"
down_revision = "c9e1a2b3d4f5"
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # mall_users
    # =========================================================================
    op.create_table(
        "mall_users",
        sa.Column("id", sa.String(36), primary_key=True),

        sa.Column("openid", sa.String(64), nullable=True),
        sa.Column("unionid", sa.String(64), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("username", sa.String(50), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("gender", sa.Integer, nullable=True),

        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("token_version", sa.Integer, nullable=False, server_default="1"),

        sa.Column("user_type", sa.String(20), nullable=False, server_default="consumer"),

        sa.Column("linked_employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("assigned_brand_id", sa.String(36), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("is_accepting_orders", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wechat_qr_url", sa.String(500), nullable=True),
        sa.Column("alipay_qr_url", sa.String(500), nullable=True),
        sa.Column("default_warehouse_id", sa.String(36), nullable=True),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.text("false")),

        # 自引用 FK 得在建表后用 add_constraint 加，避免循环
        sa.Column("referrer_salesman_id", sa.String(36), nullable=True),
        sa.Column("referrer_bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referrer_last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referrer_change_reason", sa.Text, nullable=True),

        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),

        sa.UniqueConstraint("username", name="uq_mall_users_username"),
        sa.CheckConstraint(
            "user_type <> 'salesman' OR linked_employee_id IS NOT NULL",
            name="ck_mall_users_salesman_linked_employee",
        ),
    )
    # 自引用 FK
    op.create_foreign_key(
        "fk_mall_users_referrer",
        "mall_users", "mall_users",
        ["referrer_salesman_id"], ["id"],
        ondelete="RESTRICT",
    )
    # 索引
    op.create_index(
        "ix_mall_users_openid", "mall_users", ["openid"],
        unique=True, postgresql_where=sa.text("openid IS NOT NULL"),
    )
    op.create_index("ix_mall_users_phone", "mall_users", ["phone"])
    op.create_index("ix_mall_users_referrer", "mall_users", ["referrer_salesman_id"])
    op.create_index("ix_mall_users_last_order_at", "mall_users", ["last_order_at"])
    op.create_index("ix_mall_users_status", "mall_users", ["status"])

    # =========================================================================
    # mall_addresses
    # =========================================================================
    op.create_table(
        "mall_addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receiver", sa.String(50), nullable=False),
        sa.Column("mobile", sa.String(20), nullable=False),
        sa.Column("province_code", sa.String(12), nullable=True),
        sa.Column("city_code", sa.String(12), nullable=True),
        sa.Column("area_code", sa.String(12), nullable=True),
        sa.Column("province", sa.String(50), nullable=True),
        sa.Column("city", sa.String(50), nullable=True),
        sa.Column("area", sa.String(50), nullable=True),
        sa.Column("addr", sa.String(200), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_addresses_user", "mall_addresses", ["user_id"])

    # =========================================================================
    # mall_regions
    # =========================================================================
    op.create_table(
        "mall_regions",
        sa.Column("area_code", sa.String(12), primary_key=True),
        sa.Column("parent_code", sa.String(12), nullable=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
    )
    op.create_index("ix_mall_regions_parent", "mall_regions", ["parent_code"])

    # =========================================================================
    # mall_invite_codes
    # =========================================================================
    op.create_table(
        "mall_invite_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("issuer_salesman_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_mall_invite_codes_code_expires", "mall_invite_codes",
        ["code", "expires_at"],
    )
    op.create_index(
        "ix_mall_invite_codes_issuer_created", "mall_invite_codes",
        ["issuer_salesman_id", "created_at"],
    )

    # =========================================================================
    # mall_login_logs
    # =========================================================================
    op.create_table(
        "mall_login_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("login_method", sa.String(20), nullable=False),
        sa.Column("client_app", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("device_info", sa.JSON, nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("login_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mall_login_logs_user_login", "mall_login_logs", ["user_id", "login_at"])
    op.create_index("ix_mall_login_logs_login_at", "mall_login_logs", ["login_at"])
    op.create_index("ix_mall_login_logs_ip", "mall_login_logs", ["ip_address"])


def downgrade():
    op.drop_index("ix_mall_login_logs_ip", table_name="mall_login_logs")
    op.drop_index("ix_mall_login_logs_login_at", table_name="mall_login_logs")
    op.drop_index("ix_mall_login_logs_user_login", table_name="mall_login_logs")
    op.drop_table("mall_login_logs")

    op.drop_index("ix_mall_invite_codes_issuer_created", table_name="mall_invite_codes")
    op.drop_index("ix_mall_invite_codes_code_expires", table_name="mall_invite_codes")
    op.drop_table("mall_invite_codes")

    op.drop_index("ix_mall_regions_parent", table_name="mall_regions")
    op.drop_table("mall_regions")

    op.drop_index("ix_mall_addresses_user", table_name="mall_addresses")
    op.drop_table("mall_addresses")

    op.drop_index("ix_mall_users_status", table_name="mall_users")
    op.drop_index("ix_mall_users_last_order_at", table_name="mall_users")
    op.drop_index("ix_mall_users_referrer", table_name="mall_users")
    op.drop_index("ix_mall_users_phone", table_name="mall_users")
    op.drop_index("ix_mall_users_openid", table_name="mall_users")
    op.drop_constraint("fk_mall_users_referrer", "mall_users", type_="foreignkey")
    op.drop_table("mall_users")
