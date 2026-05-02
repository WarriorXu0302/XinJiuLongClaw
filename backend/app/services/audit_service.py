"""
Audit logging utility — records sensitive operations to audit_logs.

调用约定：
- 所有状态变更类端点（审批、执行、撤销、删除、入库、出库、资金流动等）
  应在 db.flush 之前调用 log_audit。
- actor_id 从 CurrentUser 的 employee_id 自动取（传 user dict 即可）。
- changes 是 dict，尽量记录关键字段的前后值或金额，不必全量。
- IP 走 middleware + ContextVar 自动注入，端点无需显式传 request。
  只有在没有 request 上下文（后台定时任务）时才可能为 null。
"""
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


# 由 AuditRequestMiddleware 每个请求 set 一次
_current_request: ContextVar[Request | None] = ContextVar(
    "audit_current_request", default=None
)


def set_current_request(request: Request | None) -> None:
    """middleware 调用。业务代码不应直接用。"""
    _current_request.set(request)


def _client_ip(request: Request | None) -> str | None:
    """从 Request 里取客户端 IP。优先走 X-Forwarded-For（反代场景取首跳真实 IP）。"""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip() or None
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip() or None
    if request.client and request.client.host:
        return request.client.host
    return None


def _current_ip() -> str | None:
    return _client_ip(_current_request.get())


async def log_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: str | None = None,
    actor_type: str = "employee",
    mall_user_id: str | None = None,
    changes: dict | None = None,
    ip_address: str | None = None,
    request: Request | None = None,  # 可选：传 Request 自动取 IP（含 X-Forwarded-For）
    user: dict[str, Any] | None = None,  # 传 CurrentUser dict，自动提取 employee_id
    mall_user: dict[str, Any] | None = None,  # 传 CurrentMallUser payload，自动提 mall_user_id
) -> None:
    """在当前事务里插入一条审计日志。

    ERP 员工操作：
        await log_audit(db, action="approve_order", entity_type="Order",
                        entity_id=o.id, user=user, request=request,
                        changes={"from": "pending", "to": "approved"})

    mall 业务员 / 消费者操作（actor_type 自动设为 mall_user）：
        await log_audit(db, action="mall_invite_code.invalidate_by_salesman",
                        entity_type="MallInviteCode", entity_id=c.id,
                        mall_user=current_mall, request=request,
                        changes={...})
    """
    if user and not actor_id:
        actor_id = user.get("employee_id")
    if mall_user and not mall_user_id:
        # CurrentMallUser payload 里 sub 就是 mall_user.id（JWT 规范）
        mall_user_id = mall_user.get("mall_user_id") or mall_user.get("sub")
        # 自动切换 actor_type（调用方没显式指定才切）
        if mall_user_id and actor_type == "employee":
            actor_type = "mall_user"
    # IP 优先级：显式 ip_address > 显式 request > ContextVar 自动
    if ip_address is None:
        ip_address = _client_ip(request) if request is not None else _current_ip()
    entry = AuditLog(
        id=str(uuid.uuid4()),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_type=actor_type,
        mall_user_id=mall_user_id,
        changes=changes,
        ip_address=ip_address,
    )
    db.add(entry)
