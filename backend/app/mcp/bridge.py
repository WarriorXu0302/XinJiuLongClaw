"""MCP Streamable-HTTP Bridge.

把 ERP 的 28 个 /mcp/* REST endpoint 包装成标准 MCP 协议。

Per-user 权限设计：
- openclaw config 里的 static JWT（admin）用于 list_tools 返回全量工具清单
- call_tool 时，agent 必须在参数里带 _open_id（飞书用户 open_id）
- bridge 用 _open_id 调 /api/feishu/exchange-token 换该用户的短期 JWT
- 用该用户 JWT 打 ERP → RBAC + RLS 按该用户真实角色生效
- 换来的 JWT 带内存缓存（10 分钟），不会每次 tool call 都打 ERP
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import time
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

_current_user: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mcp_bridge_user", default=None
)
_current_bearer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bridge_bearer", default=None
)
_current_loopback: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bridge_loopback", default=None
)

# ─────────────────────────────────────────────────────────────────────
# Per-user JWT cache:  open_id → (jwt, roles, expire_ts)
# ─────────────────────────────────────────────────────────────────────
_jwt_cache: dict[str, tuple[str, list[str], float]] = {}
_CACHE_TTL = 600  # 10 分钟，小于 ERP 端 FEISHU_AGENT_TOKEN_TTL_MIN(15min)


async def _get_user_jwt(open_id: str, loopback: str) -> tuple[str, list[str]]:
    """用 open_id 换 per-user JWT。有缓存。"""
    now = time.time()
    cached = _jwt_cache.get(open_id)
    if cached and cached[2] > now + 30:
        return cached[0], cached[1]

    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        resp = await client.post(
            f"{loopback}/api/feishu/exchange-token",
            json={"open_id": open_id},
            headers={"X-Agent-Service-Key": settings.FEISHU_AGENT_SERVICE_KEY},
        )
    if resp.status_code == 404:
        raise ValueError(f"飞书用户 {open_id[:12]}... 未绑定 ERP 账号，请先发 /bind 用户名 密码")
    if resp.status_code != 200:
        raise ValueError(f"换 token 失败 ({resp.status_code}): {resp.text[:200]}")

    d = resp.json()
    jwt = d["access_token"]
    roles = d.get("roles", [])
    _jwt_cache[open_id] = (jwt, roles, now + _CACHE_TTL)
    return jwt, roles


# ─────────────────────────────────────────────────────────────────────
# MCP Handlers
# ─────────────────────────────────────────────────────────────────────

mcp_server = Server("xjl-erp-mcp")


@mcp_server.list_tools()
async def _list_tools() -> list[types.Tool]:
    """返回全量工具清单（用 static admin JWT）。

    原因：list_tools 没有参数，无法知道"谁在问"。
    安全兜底：call_tool 时用 per-user JWT，ERP 端 403 会拒绝越权调用。
    LLM 看到全集不是漏洞——它只是"知道有这些工具"，调不调得动看 call_tool。
    """
    user = _current_user.get()
    if user is None:
        log.warning("list_tools called without JWT context")
        return []

    visible = tools_for_user(user)

    open_id_prop = {
        "type": "string",
        "description": "【必填】当前飞书用户的 open_id（从会话 session key 末段提取）",
    }

    tools: list[types.Tool] = []

    # 绑定工具——所有人都能看到（未绑定也要能调）
    tools.append(types.Tool(
        name="bind-feishu-account",
        description="绑定飞书账号到 ERP。用户说'绑定 xxx xxx'或'/bind xxx xxx'时调用。",
        inputSchema={
            "type": "object",
            "properties": {
                "_open_id": open_id_prop,
                "username": {"type": "string", "description": "ERP 用户名"},
                "password": {"type": "string", "description": "ERP 密码"},
            },
            "required": ["_open_id", "username", "password"],
        },
    ))
    tools.append(types.Tool(
        name="unbind-feishu-account",
        description="解绑飞书账号。用户说'解绑'时调用。",
        inputSchema={
            "type": "object",
            "properties": {"_open_id": open_id_prop},
            "required": ["_open_id"],
        },
    ))

    # ERP 业务工具——从 FastAPI openapi schema 动态提取参数定义
    openapi_schemas = _get_tool_schemas()

    for t in visible:
        props: dict[str, Any] = {"_open_id": open_id_prop}
        required = ["_open_id"]

        # 合并 FastAPI 端点的 body schema
        tool_schema = openapi_schemas.get(t["name"])
        if tool_schema and "properties" in tool_schema:
            for k, v in tool_schema["properties"].items():
                props[k] = v
            for r in tool_schema.get("required", []):
                if r not in required:
                    required.append(r)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": props,
            "required": required,
        }
        tools.append(types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=schema,
        ))
    return tools


def _get_tool_schemas() -> dict[str, dict[str, Any]]:
    """从 FastAPI app 的 openapi schema 提取每个 MCP 工具的 request body 定义。"""
    try:
        from app.main import app as _app
        spec = _app.openapi()
        schemas = spec.get("components", {}).get("schemas", {})
        result: dict[str, dict[str, Any]] = {}

        for path, methods in spec.get("paths", {}).items():
            if not path.startswith("/mcp/"):
                continue
            tool_name = path.replace("/mcp/", "")
            post = methods.get("post", {})
            body_ref = (post.get("requestBody", {}).get("content", {})
                       .get("application/json", {}).get("schema", {}))

            # 解引用 $ref
            ref = body_ref.get("$ref", "")
            if ref:
                schema_name = ref.split("/")[-1]
                resolved = schemas.get(schema_name, {})
            else:
                resolved = body_ref

            if resolved and "properties" in resolved:
                result[tool_name] = resolved
        return result
    except Exception as e:
        log.warning("Failed to extract openapi schemas for MCP tools: %s", e)
        return {}


async def _handle_bind(loopback: str, arguments: dict[str, Any]) -> list[types.Content]:
    """处理 bind-feishu-account 工具调用。"""
    open_id = arguments.get("_open_id", "")
    username = arguments.get("username", "")
    password = arguments.get("password", "")
    if not open_id or not username or not password:
        return [types.TextContent(type="text", text="缺少参数：需要 _open_id、username、password")]

    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        resp = await client.post(
            f"{loopback}/api/feishu/bind",
            json={"open_id": open_id, "username": username, "password": password},
            headers={"X-Agent-Service-Key": settings.FEISHU_AGENT_SERVICE_KEY},
        )
    if resp.status_code == 200:
        d = resp.json()
        _jwt_cache.pop(open_id, None)  # 清缓存，下次调工具会换新 JWT
        return [types.TextContent(type="text", text=json.dumps({
            "status": "绑定成功",
            "username": d.get("username"),
            "employee_name": d.get("employee_name"),
            "roles": d.get("roles"),
        }, ensure_ascii=False))]
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    return [types.TextContent(type="text", text=f"绑定失败（{resp.status_code}）：{detail}")]


async def _handle_unbind(loopback: str, arguments: dict[str, Any]) -> list[types.Content]:
    open_id = arguments.get("_open_id", "")
    if not open_id:
        return [types.TextContent(type="text", text="缺少 _open_id")]
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        resp = await client.post(
            f"{loopback}/api/feishu/unbind",
            json={"open_id": open_id},
            headers={"X-Agent-Service-Key": settings.FEISHU_AGENT_SERVICE_KEY},
        )
    _jwt_cache.pop(open_id, None)
    if resp.status_code == 200:
        return [types.TextContent(type="text", text="已解绑 ERP 账号")]
    return [types.TextContent(type="text", text=f"解绑失败（{resp.status_code}）")]


@mcp_server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.Content]:
    """Per-user JWT: 从 _open_id 换 token，用该用户身份调 ERP。"""
    loopback = _current_loopback.get()
    if not loopback:
        raise ValueError("loopback base URL missing")

    # 绑定/解绑：特殊工具，不走 catalog
    if name == "bind-feishu-account":
        return await _handle_bind(loopback, arguments)
    if name == "unbind-feishu-account":
        return await _handle_unbind(loopback, arguments)

    entry = get_tool(name)
    if entry is None:
        raise ValueError(f"未知工具: {name}")

    # 提取 _open_id
    open_id = arguments.pop("_open_id", None)
    if not open_id:
        bearer = _current_bearer.get()
        if not bearer:
            raise ValueError("缺少 _open_id 参数或 Authorization Bearer token")
    else:
        try:
            bearer, roles = await _get_user_jwt(open_id, loopback)
        except ValueError as e:
            return [types.TextContent(type="text", text=str(e))]
        log.info("call_tool per-user: open_id=%s roles=%s tool=%s", open_id[:12], roles, name)

    url = f"{loopback}{entry['path']}"
    headers = {"Authorization": f"Bearer {bearer}"}

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=arguments or {})

    if resp.status_code >= 400:
        body = resp.text
        try:
            body = json.dumps(resp.json(), ensure_ascii=False)
        except Exception:
            pass
        return [types.TextContent(type="text", text=f"[HTTP {resp.status_code}] {body}")]

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
    stateless=True,
    json_response=True,
)


def _extract_bearer(scope: Scope) -> str | None:
    for name_bytes, value_bytes in scope.get("headers", []):
        if name_bytes == b"authorization":
            v = value_bytes.decode("latin-1", errors="replace")
            if v.lower().startswith("bearer "):
                return v[7:].strip()
    return None


async def mcp_bridge_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":
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

    server = scope.get("server") or ("127.0.0.1", 8000)
    host, port = server[0], server[1]
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    loopback = f"http://{host}:{port}"

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
    async with session_manager.run():
        yield
