"""
Database connection and session management.

两套 engine：
- `engine`      → erpuser 超级用户，Alembic/seed/startup 用，绕过 RLS
- `app_engine`  → erp_app 受 RLS 约束，FastAPI 请求处理用

`get_db` 依赖必须配合 `CurrentUser`（JWT），否则 SET LOCAL 没上下文，RLS 全拒绝。
"""
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.security import CurrentUser

# ─── Admin engine（超级用户，绕过 RLS）───────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

admin_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ─── App engine（erp_app，受 RLS）──────────────────────────────
# statement_cache_size=0 防止 asyncpg prepared statement 跨 session 复用泄露上下文
app_engine = create_async_engine(
    settings.app_database_url,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"statement_cache_size": 0},
)

app_session_factory = async_sessionmaker(
    app_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def _set_session_context(session: AsyncSession, user: dict[str, Any]) -> None:
    """写入 PG session 变量，供 RLS policy 读取。
    用 set_config(..., true)（等价 SET LOCAL），只在当前事务生效，COMMIT/ROLLBACK 后自动清空。
    """
    roles = user.get("roles") or []
    brand_ids = user.get("brand_ids") or []
    is_admin = bool(user.get("is_admin", False))
    can_see_master = bool(user.get("can_see_master", False))
    employee_id = user.get("employee_id") or ""

    # 逐条 set_config（asyncpg 不允许 multi-statement）
    await session.execute(
        text("SELECT set_config('app.user_id', :v, true)"),
        {"v": str(user.get("sub") or "")},
    )
    await session.execute(
        text("SELECT set_config('app.employee_id', :v, true)"),
        {"v": str(employee_id)},
    )
    await session.execute(
        text("SELECT set_config('app.roles', :v, true)"),
        {"v": ",".join(roles)},
    )
    await session.execute(
        text("SELECT set_config('app.brand_ids', :v, true)"),
        {"v": ",".join(brand_ids)},
    )
    await session.execute(
        text("SELECT set_config('app.is_admin', :v, true)"),
        {"v": "true" if is_admin else "false"},
    )
    await session.execute(
        text("SELECT set_config('app.can_see_master', :v, true)"),
        {"v": "true" if can_see_master else "false"},
    )


async def get_db(user: CurrentUser) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 请求依赖。受 RLS 约束，需 JWT 上下文。"""
    async with app_session_factory() as session:
        try:
            # 事务内 SET LOCAL 上下文
            await _set_session_context(session, user)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_anon() -> AsyncGenerator[AsyncSession, None]:
    """无鉴权场景（/auth/login、/auth/refresh）用的 DB session。
    绕过 RLS —— 通过 admin engine 访问 users/roles 等表做身份校验。
    绝不在业务路由里使用。
    """
    async with admin_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """后台任务/脚本用的 admin session，绕过 RLS。"""
    async with admin_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables. 仅开发启动辅助；生产用 Alembic。"""
    from app.models.base import Base
    from app.models import (  # noqa
        user, product, customer, order, inventory, policy, policy_request_item,
        policy_template, inspection, finance, financing, purchase, tasting,
        expense_claim, notification_log, audit_log, fund_flow, payroll, sales_target,
        attendance,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close all DB connections."""
    await engine.dispose()
    await app_engine.dispose()
