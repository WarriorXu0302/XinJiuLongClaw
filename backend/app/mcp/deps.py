"""
MCP 专用 DB 依赖——支持 JWT 和 Feishu 双认证，注入 RLS 上下文。
"""
from typing import Any, AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import app_session_factory, admin_session_factory
from app.mcp.auth import get_mcp_user, resolve_feishu_brand_scope


async def get_mcp_db(
    user: dict[str, Any] = Depends(get_mcp_user),
) -> AsyncGenerator[AsyncSession, None]:
    """MCP 请求用的 DB session。

    JWT 模式：走 app_engine（受 RLS 约束），和普通 API 一样。
    飞书模式：走 admin_engine + 手动品牌过滤（飞书用户不在 PG role 体系内）。
    """
    is_feishu = user.get("_auth_type") == "feishu"

    factory = admin_session_factory if is_feishu else app_session_factory

    async with factory() as session:
        try:
            if is_feishu:
                user = await resolve_feishu_brand_scope(user, session)

            # JWT 模式：注入 RLS 上下文（和 get_db 一致）
            if not is_feishu:
                roles = user.get("roles") or []
                brand_ids = user.get("brand_ids") or []
                await session.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": str(user.get("sub") or "")})
                await session.execute(text("SELECT set_config('app.employee_id', :v, true)"), {"v": str(user.get("employee_id") or "")})
                await session.execute(text("SELECT set_config('app.roles', :v, true)"), {"v": ",".join(roles)})
                await session.execute(text("SELECT set_config('app.brand_ids', :v, true)"), {"v": ",".join(brand_ids)})
                await session.execute(text("SELECT set_config('app.is_admin', :v, true)"), {"v": "true" if user.get("is_admin") else "false"})
                await session.execute(text("SELECT set_config('app.can_see_master', :v, true)"), {"v": "true" if user.get("can_see_master") else "false"})

            # 把 user 存到 session.info 供工具函数读取
            session.info["mcp_user"] = user

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
