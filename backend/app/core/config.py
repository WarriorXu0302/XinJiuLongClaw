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
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

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
