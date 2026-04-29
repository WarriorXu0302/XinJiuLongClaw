"""
Security utilities: password hashing, JWT tokens, auth dependencies.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict[str, Any]:
    """FastAPI dependency to get the current authenticated user from JWT."""
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# Type alias for dependency injection
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


# =============================================================================
# Mall (小程序) 独立鉴权链路
# =============================================================================
# 设计要点（见 plan "安全设计 · 鉴权/授权加固"）：
#   - JWT secret 独立（settings.MALL_JWT_SECRET），和 ERP SECRET_KEY 隔离泄漏面
#   - payload.type 固定 "mall_access" / "mall_refresh"（和 ERP "access"/"refresh" 不互认）
#   - payload 包含 token_version：封禁/换绑/停用时 MallUser.token_version +1，旧 token 解码后
#     比对失败即失效（即时吊销，不需 Redis 黑名单）
#   - 拿 mall_token 调 ERP 端点 → 401；拿 ERP_token 调 mall 端点 → 401

# 独立的 bearer 提取器（和 ERP 用同一个 HTTPBearer 实例在功能上等价，留独立变量便于未来改 scheme）
mall_security = HTTPBearer()


def _build_mall_payload(user: Any, token_type: str) -> dict[str, Any]:
    """构造 mall JWT payload。

    user 是 MallUser 实例（避免循环 import 用 Any）。
    """
    return {
        "sub": user.id,
        "user_type": user.user_type,
        "token_version": user.token_version,
        "linked_employee_id": user.linked_employee_id,
        "assigned_brand_id": user.assigned_brand_id,
        "type": token_type,
    }


def create_mall_access_token(
    user: Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Mall access token。默认 30 天，由 settings.MALL_ACCESS_TOKEN_EXPIRE_MINUTES 控制。"""
    payload = _build_mall_payload(user, "mall_access")
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.MALL_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.MALL_JWT_SECRET, algorithm=settings.ALGORITHM)


def create_mall_refresh_token(
    user: Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Mall refresh token。默认 30 天。"""
    payload = _build_mall_payload(user, "mall_refresh")
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(days=settings.MALL_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.MALL_JWT_SECRET, algorithm=settings.ALGORITHM)


def decode_mall_token(token: str, expected_type: str = "mall_access") -> dict[str, Any]:
    """解码 mall JWT。校验 type 字段防止 ERP token 混入。"""
    try:
        payload = jwt.decode(
            token, settings.MALL_JWT_SECRET, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_mall_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(mall_security)],
) -> dict[str, Any]:
    """FastAPI 依赖：从 mall JWT 拿出 payload。

    注意只校验 JWT 本身；token_version 一致性和 status=='active' 的校验在
    services/mall/auth_service 或具体路由里查 DB 比对后拒绝。
    保持"纯 JWT 层 + DB 层两步"分离，避免每个依赖都注入 DB session。
    """
    return decode_mall_token(credentials.credentials, expected_type="mall_access")


# 允许未登录的依赖（浏览类端点用；返回 None 表示匿名）
mall_security_optional = HTTPBearer(auto_error=False)


async def get_current_mall_user_optional(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(mall_security_optional),
    ],
) -> dict[str, Any] | None:
    if credentials is None:
        return None
    try:
        return decode_mall_token(credentials.credentials, expected_type="mall_access")
    except HTTPException:
        # 带了坏 token 等同于匿名；拒绝的语义交给需要鉴权的路由自己处理
        return None


# Type alias for dependency injection（和 CurrentUser 对应）
CurrentMallUser = Annotated[dict[str, Any], Depends(get_current_mall_user)]
CurrentMallUserOptional = Annotated[dict[str, Any] | None, Depends(get_current_mall_user_optional)]
