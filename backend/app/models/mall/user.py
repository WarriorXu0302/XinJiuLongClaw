"""
Mall 用户相关模型。

涵盖：
  - MallUser       C 端消费者 + 业务员统一表
  - MallAddress    C 端收货地址
  - MallRegion     省市区字典（seed 数据）
  - MallInviteCode 业务员邀请码（2 小时一次性，SQL FOR UPDATE 原子消费）
  - MallLoginLog   登录日志（保留 90 天）

关键业务规则：
  - user_type='salesman' ⇒ linked_employee_id NOT NULL（CHECK 约束 + 应用层 + 未来触发器三层防御）
  - token_version：封禁/换绑推荐人/停用触发 +1，mall JWT 解码时校验
  - last_order_at：用于 30/90/180 天停用策略
  - referrer_salesman_id：注册时由邀请码消费逻辑写入
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mall.base import MallUserStatus, MallUserType


# =============================================================================
# MallUser
# =============================================================================

class MallUser(Base):
    """小程序用户（消费者 + 业务员）。

    铁律：user_type='salesman' 时必须绑定 ERP employees.id，否则 ERP 复用模块
    （考勤/报销/提成）无法归属到员工。
    """

    __tablename__ = "mall_users"
    __table_args__ = (
        CheckConstraint(
            "user_type <> 'salesman' OR linked_employee_id IS NOT NULL",
            name="ck_mall_users_salesman_linked_employee",
        ),
        Index(
            "ix_mall_users_openid",
            "openid",
            unique=True,
            postgresql_where="openid IS NOT NULL",
        ),
        Index("ix_mall_users_phone", "phone"),
        Index("ix_mall_users_referrer", "referrer_salesman_id"),
        Index("ix_mall_users_last_order_at", "last_order_at"),
        Index("ix_mall_users_status", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    openid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unionid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    gender: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MallUserStatus.ACTIVE.value
    )

    # JWT 即时失效：封禁/换绑/停用时 +1，mall JWT payload 带此值
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MallUserType.CONSUMER.value
    )

    linked_employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    assigned_brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    is_accepting_orders: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wechat_qr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    alipay_qr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_warehouse_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    referrer_salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True
    )
    referrer_bound_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    referrer_last_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    referrer_change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    last_order_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallAddress
# =============================================================================

class MallAddress(Base):
    """C 端收货地址。同一 user 最多一条 is_default=True（应用层保证）。"""

    __tablename__ = "mall_addresses"
    __table_args__ = (
        Index("ix_mall_addresses_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False
    )
    receiver: Mapped[str] = mapped_column(String(50), nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)

    province_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    city_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    area_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    area: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    addr: Mapped[str] = mapped_column(String(200), nullable=False)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallRegion
# =============================================================================

class MallRegion(Base):
    """省/市/区三级行政区划字典（seed 数据）。"""

    __tablename__ = "mall_regions"
    __table_args__ = (
        Index("ix_mall_regions_parent", "parent_code"),
    )

    area_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    parent_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=省 2=市 3=区


# =============================================================================
# MallInviteCode
# =============================================================================

class MallInviteCode(Base):
    """业务员邀请码（2 小时一次性）。

    - 消费走 SQL FOR UPDATE 原子化，防并发双用
    - 每业务员每日上限走 settings.MALL_INVITE_CODE_DAILY_LIMIT
    - 8 位短码，排除 0/O/1/l/I
    """

    __tablename__ = "mall_invite_codes"
    __table_args__ = (
        Index("ix_mall_invite_codes_code_expires", "code", "expires_at"),
        Index(
            "ix_mall_invite_codes_issuer_created",
            "issuer_salesman_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    issuer_salesman_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True
    )

    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# =============================================================================
# MallLoginLog
# =============================================================================

class MallLoginLog(Base):
    """登录日志（每次登录 + refresh 写一条；保留 90 天后清理）。"""

    __tablename__ = "mall_login_logs"
    __table_args__ = (
        Index("ix_mall_login_logs_user_login", "user_id", "login_at"),
        Index("ix_mall_login_logs_login_at", "login_at"),
        Index("ix_mall_login_logs_ip", "ip_address"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False
    )
    login_method: Mapped[str] = mapped_column(String(20), nullable=False)
    client_app: Mapped[str] = mapped_column(String(20), nullable=False)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    device_info: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    login_at: Mapped[datetime] = mapped_column(server_default=func.now())
