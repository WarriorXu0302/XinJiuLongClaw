"""
飞书 Agent 绑定与 token 签发接口。

- POST /api/feishu/bind
    飞书 Bot 收到员工的 `/bind 用户名 密码` → Ingress 调此接口。
    校验用户名+密码 → 落 feishu_bindings → 返回员工基本信息。
    一个动作原子完成（CLAUDE.md §5）。

- POST /api/feishu/exchange-token
    服务间接口。Ingress 每次为绑定员工发消息前，用 open_id 换一个短期 JWT。
    验证 FEISHU_AGENT_SERVICE_KEY，不验 JWT（因为就是来签 JWT 的）。
    Token 字段和 /api/auth/login 完全一致，复用 build_jwt_payload。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.auth import build_jwt_payload
from app.core.config import settings
from app.core.database import get_db_anon
from app.core.security import create_access_token, verify_password
from app.models.external import FeishuBinding
from app.models.user import User, UserRole
from app.services.audit_service import log_audit

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# 服务间鉴权
# ─────────────────────────────────────────────────────────────────────


def require_service_key(
    x_agent_service_key: str = Header(..., alias="X-Agent-Service-Key"),
) -> None:
    """飞书 Ingress ↔ ERP 之间的共享密钥校验。

    Why：这些接口不走用户 JWT（绑定时用户还没 JWT，换 token 时 Ingress 也没有）。
    用服务间密钥把"内部可信调用方"拦在前门。
    """
    expected = settings.FEISHU_AGENT_SERVICE_KEY
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "FEISHU_AGENT_SERVICE_KEY 未配置",
        )
    if x_agent_service_key != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid service key")


# ─────────────────────────────────────────────────────────────────────
# /bind
# ─────────────────────────────────────────────────────────────────────


class BindRequest(BaseModel):
    open_id: str
    username: str
    password: str


class BindResponse(BaseModel):
    user_id: str
    username: str
    employee_id: str | None
    employee_name: str | None
    roles: list[str]
    bound_at: datetime


@router.post(
    "/bind",
    response_model=BindResponse,
    dependencies=[Depends(require_service_key)],
)
async def feishu_bind(body: BindRequest, db: AsyncSession = Depends(get_db_anon)):
    """绑定飞书 open_id 到 ERP 用户。

    幂等：同一 open_id 再次 /bind（用相同 username/password 也算）→ 更新为最新 user_id
    并重置为 active。防止员工离职换账号、新员工复用 open_id 这些情况。
    """
    user = (
        await db.execute(
            select(User)
            .where(User.username == body.username)
            .options(
                selectinload(User.roles).selectinload(UserRole.role),
                selectinload(User.employee),
            )
        )
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")

    now = datetime.now(timezone.utc)

    # open_id 已绑 → 更新为新 user，并把旧 user 解绑
    existing_by_open = (
        await db.execute(
            select(FeishuBinding).where(FeishuBinding.open_id == body.open_id)
        )
    ).scalar_one_or_none()

    # user_id 已绑其他 open_id → 同理更新
    existing_by_user = (
        await db.execute(
            select(FeishuBinding).where(FeishuBinding.user_id == user.id)
        )
    ).scalar_one_or_none()

    if existing_by_open and existing_by_user and existing_by_open.id != existing_by_user.id:
        # 交叉冲突：open_id 绑的是另一个用户，且当前用户已绑另一个 open_id
        # 最安全的做法是把两条都 soft-unbind，要求管理员介入
        existing_by_open.is_active = False
        existing_by_open.unbind_at = now
        existing_by_user.is_active = False
        existing_by_user.unbind_at = now
        await db.flush()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "open_id 或账号与历史绑定冲突，已自动解绑历史记录，请重新 /bind",
        )

    binding = existing_by_open or existing_by_user
    if binding is not None:
        binding.open_id = body.open_id
        binding.user_id = user.id
        binding.is_active = True
        binding.bound_at = now
        binding.unbind_at = None
    else:
        binding = FeishuBinding(
            open_id=body.open_id,
            user_id=user.id,
            is_active=True,
        )
        db.add(binding)

    await db.flush()
    await log_audit(
        db,
        action="feishu_bind",
        entity_type="FeishuBinding",
        entity_id=binding.id,
        user={"sub": user.id, "username": user.username},
        changes={"open_id_prefix": body.open_id[:8]},
    )

    return BindResponse(
        user_id=user.id,
        username=user.username,
        employee_id=user.employee_id,
        employee_name=user.employee.name if user.employee else None,
        roles=[ur.role.code for ur in user.roles if ur.role],
        bound_at=binding.bound_at,
    )


# ─────────────────────────────────────────────────────────────────────
# /exchange-token
# ─────────────────────────────────────────────────────────────────────


class ExchangeRequest(BaseModel):
    open_id: str


class ExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_min: int
    user_id: str
    username: str
    roles: list[str]


@router.post(
    "/exchange-token",
    response_model=ExchangeResponse,
    dependencies=[Depends(require_service_key)],
)
async def feishu_exchange_token(
    body: ExchangeRequest, db: AsyncSession = Depends(get_db_anon)
):
    """open_id → 短期 JWT。Ingress 在为员工调 /mcp 前调一次。

    Token TTL 短（默认 15 分钟），避免 Ingress 泄露 token 后长期可用。
    payload 字段 = login 一致（复用 build_jwt_payload）。
    """
    binding = (
        await db.execute(
            select(FeishuBinding).where(
                FeishuBinding.open_id == body.open_id,
                FeishuBinding.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "open_id 未绑定或已解绑")

    user = (
        await db.execute(
            select(User)
            .where(User.id == binding.user_id)
            .options(selectinload(User.roles).selectinload(UserRole.role))
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")

    binding.last_seen_at = datetime.now(timezone.utc)
    await db.flush()

    payload = await build_jwt_payload(db, user)
    ttl = timedelta(minutes=settings.FEISHU_AGENT_TOKEN_TTL_MIN)
    token = create_access_token(payload, expires_delta=ttl)

    return ExchangeResponse(
        access_token=token,
        expires_in_min=settings.FEISHU_AGENT_TOKEN_TTL_MIN,
        user_id=user.id,
        username=user.username,
        roles=payload["roles"],
    )


# ─────────────────────────────────────────────────────────────────────
# /unbind  (管理员从 ERP 前端调用；Ingress 不调)
# ─────────────────────────────────────────────────────────────────────


class UnbindRequest(BaseModel):
    open_id: str


@router.post(
    "/unbind",
    dependencies=[Depends(require_service_key)],
)
async def feishu_unbind(body: UnbindRequest, db: AsyncSession = Depends(get_db_anon)):
    """解绑。软删除：is_active=False + unbind_at。"""
    binding = (
        await db.execute(
            select(FeishuBinding).where(FeishuBinding.open_id == body.open_id)
        )
    ).scalar_one_or_none()
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "open_id 未绑定")
    binding.is_active = False
    binding.unbind_at = datetime.now(timezone.utc)
    await db.flush()
    return {"detail": "已解绑"}
