"""MCP Streamable-HTTP Bridge.

把 ERP 的 28 个 /mcp/* REST endpoint 包装成标准 MCP 协议，让 Bisheng/Claude 等
标准 MCP client 能连过来。

设计：
- 挂载在 /mcp/stream（区别于旧的 REST /mcp/xxx）
- 使用 Streamable-HTTP transport（stateless=True），每次请求一个回复，无长会话
- 客户端必须在 HTTP header 带 Authorization: Bearer <JWT>
- list_tools：根据 JWT 的 roles，从 catalog.py 过滤可见工具
- call_tool：用 httpx POST 本地 http://localhost:{port}/mcp/<tool-name>，
  把 Authorization 透传——由 ERP 原有 get_mcp_db + require_mcp_role + RLS 兜底

这个 bridge 只做两件事：协议翻译 + 工具清单过滤。真相仍在 handler。
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
from typing import Any

import httpx
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.core.security import decode_token
from app.mcp.catalog import ALL_TOOLS, get_tool, tools_for_user

log = logging.getLogger(__name__)

# 把 HTTP 请求层的 JWT payload 放进 ContextVar,供 list_tools / call_tool 读取。
# StreamableHTTP 的 session 跑在 anyio TaskGroup 内,ContextVar 能跨 await 正常传递。
_current_user: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mcp_bridge_user", default=None
)
_current_bearer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bridge_bearer", default=None
)
# 当前请求的 loopback base URL，通过 ASGI scope['server'] 动态探测,避免写死端口。
# settings.PORT 可能和 uvicorn 实际端口不一致(--port 覆盖)——不可信。
_current_loopback: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bridge_loopback", default=None
)


# ─────────────────────────────────────────────────────────────────────
# Handlers（绑定到同一个 Server）
# ─────────────────────────────────────────────────────────────────────

mcp_server = Server("xjl-erp-mcp")


@mcp_server.list_tools()
async def _list_tools() -> list[types.Tool]:
    user = _current_user.get()
    if user is None:
        log.warning("list_tools called without JWT context")
        return []

    visible = tools_for_user(user)
    log.info("list_tools: user=%s roles=%s → %d tools",
             user.get("username"), user.get("roles"), len(visible))

    return [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": True,  # 具体 schema 交给 ERP handler 校验
            },
        )
        for t in visible
    ]


@mcp_server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.Content]:
    """把 MCP tools/call 转发到本地 REST /mcp/<name>。"""
    entry = get_tool(name)
    if entry is None:
        raise ValueError(f"未知工具: {name}")

    bearer = _current_bearer.get()
    if not bearer:
        raise ValueError("缺少 Authorization Bearer token")

    loopback = _current_loopback.get()
    if not loopback:
        raise ValueError("loopback base URL missing (scope?)")

    # 本地回调自己的 /mcp/<tool>  — 权威 RBAC + RLS 都在那边
    url = f"{loopback}{entry['path']}"
    headers = {"Authorization": f"Bearer {bearer}"}

    # trust_env=False:绕开系统 http_proxy 环境变量(ClashX 这类代理
    # 会把 localhost 劫持成 502)。loopback 不需要走任何代理。
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=arguments or {})

    if resp.status_code >= 400:
        # 把 ERP 的错误透传给 LLM（LLM 能理解 403 含义）
        body = resp.text
        try:
            body = json.dumps(resp.json(), ensure_ascii=False)
        except Exception:
            pass
        return [types.TextContent(
            type="text",
            text=f"[HTTP {resp.status_code}] {body}",
        )]

    # 成功:JSON 字符串化返回（LLM 会看到结构化输出）
    try:
        data = resp.json()
        text = json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        text = resp.text
    return [types.TextContent(type="text", text=text)]


# ─────────────────────────────────────────────────────────────────────
# Session manager + ASGI wrapper
# ─────────────────────────────────────────────────────────────────────

session_manager = StreamableHTTPSessionManager(
    app=mcp_server,
    stateless=True,       # 无 session 状态—每次请求独立处理
    json_response=True,   # 纯 JSON 回复,不走 SSE
)


def _extract_bearer(scope: Scope) -> str | None:
    """从 ASGI scope.headers 取 Authorization: Bearer xxx。"""
    for name_bytes, value_bytes in scope.get("headers", []):
        if name_bytes == b"authorization":
            v = value_bytes.decode("latin-1", errors="replace")
            if v.lower().startswith("bearer "):
                return v[7:].strip()
    return None


async def mcp_bridge_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    """被 FastAPI mount 的 ASGI app。

    流程:
    1. 从 header 读 Bearer token
    2. decode JWT → 塞进 ContextVar
    3. 调 session_manager.handle_request —— handler 内部能通过 ContextVar 读到 user
    4. 无 token 或 token 非法 → 401
    """
    if scope["type"] != "http":
        # MCP streamable 只处理 HTTP
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"only http"})
        return

    bearer = _extract_bearer(scope)
    if not bearer:
        await _send_401(send, "missing Authorization: Bearer")
        return

    try:
        payload = decode_token(bearer)
        if payload.get("type") != "access":
            raise ValueError("not an access token")
    except Exception as e:
        log.warning("MCP bridge reject bad JWT: %s", e)
        await _send_401(send, "invalid JWT")
        return

    # 从 ASGI scope 取真实 host/port(uvicorn 启动时 --port 覆盖 settings.PORT 常见)。
    server = scope.get("server") or ("127.0.0.1", 8000)
    host, port = server[0], server[1]
    # 宿主机内 loopback:即使 server host 是 0.0.0.0,回环用 127.0.0.1 也通。
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    loopback = f"http://{host}:{port}"

    # 把 user payload + bearer + loopback 串入 ContextVar,handler 里读
    token_u = _current_user.set(payload)
    token_b = _current_bearer.set(bearer)
    token_l = _current_loopback.set(loopback)
    try:
        await session_manager.handle_request(scope, receive, send)
    finally:
        _current_user.reset(token_u)
        _current_bearer.reset(token_b)
        _current_loopback.reset(token_l)


async def _send_401(send: Send, reason: str) -> None:
    body = json.dumps({"error": reason}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", b'Bearer realm="mcp"'),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


@contextlib.asynccontextmanager
async def bridge_lifespan():
    """FastAPI 启动时调用——session_manager 必须在 app lifespan 内运行。"""
    async with session_manager.run():
        yield
