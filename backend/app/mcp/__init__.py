"""
MCP (Model Context Protocol) — AI Agent 工具集。

支持两种调用方：
1. JWT Bearer Token（Claude Code / 外部 Agent）→ 走 RLS 行级安全
2. X-External-Open-Id（飞书 AI 网关）→ 走 brand_scope 品牌范围

工具分类：
- tools_query    — 只读查询（10 个：订单/客户/库存/利润/账户/工资/目标/稽查/补贴/考勤）
- tools_action   — 写入操作（6 个：建单/收款/建客户/请假/生成工资/生成补贴）
- tools_approval — 审批操作（5 个：确认收款/审批请假/工资/目标/调拨）
- tools（旧）    — 飞书专用（7 个：对账分配/厂家审批/条码追溯/推送通知等）
"""
from fastapi import APIRouter

from app.mcp.tools_query import router as query_router
from app.mcp.tools_action import router as action_router
from app.mcp.tools_approval import router as approval_router
from app.mcp.tools import router as legacy_router

mcp_router = APIRouter()
mcp_router.include_router(query_router, tags=["MCP-Query"])
mcp_router.include_router(action_router, tags=["MCP-Action"])
mcp_router.include_router(approval_router, tags=["MCP-Approval"])
mcp_router.include_router(legacy_router, tags=["MCP-Feishu"])
