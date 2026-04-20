"""
MCP 双认证：JWT Bearer Token（内部 Agent）+ Feishu Open ID（飞书 AI 网关）。

认证优先级：
1. Authorization: Bearer <jwt> → 走 CurrentUser + RLS
2. X-External-Open-Id: <feishu_open_id> → 查 manufacturer_external_identities 表
3. 都没有 → 401
"""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token

# Optional bearer — 不强制（飞书调用没有 JWT）
_optional_bearer = HTTPBearer(auto_error=False)


async def get_mcp_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    x_external_open_id: Optional[str] = Header(None, alias="X-External-Open-Id"),
) -> dict[str, Any]:
    """解析 MCP 调用方身份。返回 dict 兼容 CurrentUser 格式。

    JWT 模式：直接解码 token，返回 payload（含 roles/brand_ids/is_admin 等）。
    飞书模式：查 manufacturer_external_identities 表，构造等价 payload。
    """

    # ── 优先 JWT ──
    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
            if payload.get("type") != "access":
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
            return payload
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid JWT token")

    # ── Feishu Open ID ──
    if x_external_open_id:
        return {
            "sub": f"feishu:{x_external_open_id}",
            "username": f"feishu_{x_external_open_id[:8]}",
            "employee_id": None,
            "roles": ["manufacturer_staff"],
            "brand_ids": [],  # 后续从 identity.brand_scope 填充
            "is_admin": False,
            "can_see_master": False,
            "_auth_type": "feishu",
            "_open_id": x_external_open_id,
        }

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要 JWT Bearer Token 或 X-External-Open-Id")


async def resolve_feishu_brand_scope(
    user: dict[str, Any], db: AsyncSession,
) -> dict[str, Any]:
    """飞书认证时，从 manufacturer_external_identities 读取 brand_scope 并注入 user。"""
    if user.get("_auth_type") != "feishu":
        return user

    from app.models.external import ManufacturerExternalIdentity
    from app.models.base import ManufacturerExternalStatus

    open_id = user["_open_id"]
    identity = (await db.execute(
        select(ManufacturerExternalIdentity).where(
            ManufacturerExternalIdentity.open_id == open_id,
            ManufacturerExternalIdentity.status == ManufacturerExternalStatus.ACTIVE,
        )
    )).scalar_one_or_none()

    if identity is None:
        raise HTTPException(403, "飞书身份未注册或已停用")

    identity.last_seen_at = datetime.now(timezone.utc)

    brand_scope = identity.brand_scope or []
    user["brand_ids"] = brand_scope
    user["_manufacturer_id"] = identity.manufacturer_id
    return user
