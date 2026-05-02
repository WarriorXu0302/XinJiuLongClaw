"""
Application configuration loaded from environment variables.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "NewERP System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Database ---
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "erpuser"
    DB_PASSWORD: str = "erppassword"
    DB_NAME: str = "newerp"
    DATABASE_URL: str = ""

    # App-level DB role (NOBYPASSRLS) — used by FastAPI request handlers
    # Migrations/seed/startup 继续用 DB_USER（superuser）以绕过 RLS
    APP_DB_USER: str = "erp_app"
    APP_DB_PASSWORD: str = "erp_app_pw"

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # --- Security ---
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- CORS ---
    # 5175 前端（5173 常被微信/支付宝小程序开发工具占用）；5173 保留兼容
    CORS_ORIGINS: list[str] = [
        "http://localhost:5175",
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # --- AI / LLM ---
    LLM_PROVIDER: Literal["dashscope", "anthropic"] = "dashscope"
    DASHSCOPE_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # --- Upload ---
    UPLOAD_DIR: str = "uploads"
    UPLOAD_MAX_SIZE_MB: int = 10

    # --- Feishu (Lark) ---
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_VERIFICATION_TOKEN: str = ""
    FEISHU_ENCRYPT_KEY: str = ""

    # --- Agent ingress ↔ ERP 服务间共享密钥 ---
    # 飞书 Ingress 用这个 key 调 /api/feishu/exchange-token
    FEISHU_AGENT_SERVICE_KEY: str = ""
    FEISHU_AGENT_TOKEN_TTL_MIN: int = 15

    # --- Mall (小程序) TODO(M1): 在 M1 阶段实现 ---
    # 全局开关，关闭后采购页/ERP 前端不显示 mall 仓选项
    MALL_INTEGRATION_ENABLED: bool = True
    # 微信小程序
    MP_APPID: str = ""
    MP_SECRET: str = ""
    # JWT（独立于 ERP SECRET_KEY，泄漏互不影响）
    MALL_JWT_SECRET: str = "change-me-mall-in-production"
    MALL_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    MALL_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # 邀请码
    MALL_INVITE_CODE_TTL_MINUTES: int = 120  # 2 小时
    MALL_INVITE_CODE_DAILY_LIMIT: int = 20
    MALL_INVITE_CODE_EXHIBITION_LIMIT: int = 100
    # 邀请码二维码深链接基址（扫码跳 H5 注册页自动填 code）
    MALL_INVITE_DEEPLINK_BASE: str = "https://mall.xinjiulong.com/register"
    # 小程序码扫码跳转到的小程序页面路径（不能带 query，scene 从 launch options 读）
    MALL_INVITE_SCAN_PAGE: str = "pages/register-by-scan/register-by-scan"
    # 用户停用策略（3 级）
    MALL_INACTIVE_DAYS_NEW_USER: int = 30     # 注册未下单
    MALL_INACTIVE_DAYS_FEW_ORDERS: int = 90   # 1-2 次下单
    MALL_INACTIVE_DAYS_LOYAL: int = 180       # 3+ 次下单老客户
    MALL_INACTIVE_PRE_NOTICE_DAYS: int = 7    # 停用前多少天发预告
    # 订单折损
    MALL_PARTIAL_CLOSE_DAYS: int = 60         # delivered 后多久未全款自动折损
    # 提成
    MALL_DEFAULT_COMMISSION_RATE: str = "0.03"  # 无 BrandSalaryScheme 时兜底
    # 跳单告警
    MALL_UNCLAIMED_TIMEOUT_MINUTES: int = 30
    MALL_SKIP_ALERT_THRESHOLD: int = 3
    MALL_SKIP_ALERT_WINDOW_DAYS: int = 30
    # 日志保留
    MALL_LOGIN_LOG_RETENTION_DAYS: int = 90
    # 限流
    MALL_MAX_LOGIN_ATTEMPTS_PER_IP_PER_MIN: int = 10
    MALL_MAX_PRICE_VIEW_PER_USER_PER_HOUR: int = 200
    # 上传
    MALL_UPLOAD_MAX_SIZE_MB: int = 5
    MALL_UPLOAD_ALLOWED_MIMES: list[str] = [
        "image/jpeg", "image/png", "image/webp"
    ]

    @property
    def database_url(self) -> str:
        """Admin/superuser URL — 给 Alembic / seed / 启动钩子用，绕过 RLS。"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def app_database_url(self) -> str:
        """应用请求用的 URL，走非特权 erp_app 角色，受 RLS 约束。"""
        return (
            f"postgresql+asyncpg://{self.APP_DB_USER}:{self.APP_DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
