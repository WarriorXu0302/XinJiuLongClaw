"""MCP tool 目录——供 /mcp/sse bridge 列出 + 路由到真实 REST handler。

设计约束（CLAUDE.md §7 §13）：
- 这张表**不**是权威权限——权威还是每个 handler 里的 require_mcp_role(...)
- 这张表的作用：让 LLM 看到"自己权限内"的工具清单；真实执行仍然走 ERP /mcp/xxx
  REST endpoint，RBAC 由 handler 自己兜底
- handler 里改了角色白名单，这里**必须**跟着改（grep "tool_name" 看一下）

roles 字段：
- "*" = 任何登录员工（对应 require_mcp_employee）
- 具体角色列表 = 对应 require_mcp_role(user, ...)
- admin 总是可见（require_mcp_role 已内置放行）
"""
from typing import Any, TypedDict


class ToolEntry(TypedDict):
    name: str          # MCP 工具名（和 endpoint 同名，横线分隔）
    path: str          # 真实 REST endpoint 路径
    roles: list[str]   # 允许的 role codes; ["*"] = 任何员工
    description: str   # 给 LLM 看的描述（中文，短，含触发场景）
    # input_schema 先不写死 —— 从 FastAPI 的 openapi.json 动态抽，避免两处写


# ─── 查询类（11）─────────────────────────────────────────────
QUERY_TOOLS: list[ToolEntry] = [
    {"name": "query-orders", "path": "/mcp/query-orders", "roles": ["*"],
     "description": "查询销售订单列表。支持按品牌/状态/付款状态/关键字过滤。"},
    {"name": "query-order-detail", "path": "/mcp/query-order-detail", "roles": ["*"],
     "description": "按 order_no 查单个订单详情（含收款记录、商品明细）。"},
    {"name": "query-customers", "path": "/mcp/query-customers", "roles": ["*"],
     "description": "查询客户列表。支持按品牌/关键字过滤。"},
    {"name": "query-inventory", "path": "/mcp/query-inventory", "roles":
     ["boss", "warehouse", "salesman", "sales_manager", "purchase", "finance"],
     "description": "查询库存（含低库存预警）。可按品牌/商品名筛选。"},
    {"name": "query-profit-summary", "path": "/mcp/query-profit-summary",
     "roles": ["boss", "finance", "sales_manager"],
     "description": "查询利润台账汇总（11 个科目）。"},
    {"name": "query-account-balances", "path": "/mcp/query-account-balances",
     "roles": ["boss", "finance"],
     "description": "查询各品牌账户余额（master 现金池、F 类账户）。"},
    {"name": "query-salary-records", "path": "/mcp/query-salary-records",
     "roles": ["boss", "finance"],
     "description": "查询月度工资单列表。"},
    {"name": "query-sales-targets", "path": "/mcp/query-sales-targets",
     "roles": ["boss", "finance", "sales_manager", "salesman"],
     "description": "查询销售目标与完成率。"},
    {"name": "query-inspection-cases", "path": "/mcp/query-inspection-cases",
     "roles": ["boss", "finance"],
     "description": "查询稽查案件列表（窜货、市场清理）。"},
    {"name": "query-manufacturer-subsidies", "path": "/mcp/query-manufacturer-subsidies",
     "roles": ["boss", "finance"],
     "description": "查询厂家工资补贴应收。"},
    {"name": "query-attendance-summary", "path": "/mcp/query-attendance-summary",
     "roles": ["boss", "finance"],
     "description": "查询某月员工考勤汇总（迟到、请假、满勤）。"},
    {"name": "query-policy-templates", "path": "/mcp/query-policy-templates",
     "roles": ["*"],
     "description": "查询政策模板列表（含 ID、指导价、客户到手价）。建单时需要 policy_template_id。"},
    {"name": "query-brands", "path": "/mcp/query-brands",
     "roles": ["*"],
     "description": "查询所有品牌（含 ID）。建单/建客户/绑岗位时需要 brand_id。"},
    {"name": "query-positions", "path": "/mcp/query-positions",
     "roles": ["*"],
     "description": "查询岗位代码列表。绑定员工品牌岗位时需要 position_code。"},
]

# ─── 写入类（6）─────────────────────────────────────────────
ACTION_TOOLS: list[ToolEntry] = [
    {"name": "create-order", "path": "/mcp/create-order",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "创建销售订单。salesman 调用时 salesman_id 强制=本人。"},
    {"name": "register-payment", "path": "/mcp/register-payment",
     "roles": ["boss", "finance", "salesman"],
     "description": "登记订单收款（上传凭证等价动作）。建 Receipt+更新 payment_status。"},
    {"name": "create-customer", "path": "/mcp/create-customer",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "创建客户并绑定品牌-业务员关系。"},
    {"name": "create-leave-request", "path": "/mcp/create-leave-request",
     "roles": ["*"],
     "description": "提交请假申请。employee_id 自动=当前用户（admin/boss 除外可代提）。"},
    {"name": "create-employee", "path": "/mcp/create-employee",
     "roles": ["boss", "hr"],
     "description": "创建员工档案（工号、姓名、岗位、社保等）。"},
    {"name": "query-employees", "path": "/mcp/query-employees",
     "roles": ["boss", "hr", "finance", "sales_manager"],
     "description": "查询员工列表。支持按关键字/状态/品牌过滤。"},
    {"name": "bind-employee-brand", "path": "/mcp/bind-employee-brand",
     "roles": ["boss", "hr"],
     "description": "绑定员工到品牌×岗位（设提成比例、厂家补贴、是否主品牌）。"},
    {"name": "create-user", "path": "/mcp/create-user",
     "roles": ["boss"],
     "description": "创建 ERP 登录账号并分配角色。需要 boss 权限。"},
    {"name": "generate-salary", "path": "/mcp/generate-salary",
     "roles": ["boss", "finance"],
     "description": "一键生成本期工资单。"},
    {"name": "generate-subsidy-expected", "path": "/mcp/generate-subsidy-expected",
     "roles": ["boss", "finance"],
     "description": "生成本月厂家工资补贴应收。"},
    {"name": "create-fund-transfer", "path": "/mcp/create-fund-transfer",
     "roles": ["boss", "finance"],
     "description": "创建资金调拨申请（master→品牌现金）。可按品牌名自动查账户。需审批后才执行。"},
]

# ─── 审批类（5）─────────────────────────────────────────────
APPROVAL_TOOLS: list[ToolEntry] = [
    {"name": "confirm-order-payment", "path": "/mcp/confirm-order-payment",
     "roles": ["boss", "finance"],
     "description": "财务确认订单收款（delivered+fully_paid → completed）。"},
    {"name": "approve-leave", "path": "/mcp/approve-leave",
     "roles": ["boss", "finance"],
     "description": "审批请假单。"},
    {"name": "approve-salary", "path": "/mcp/approve-salary",
     "roles": ["boss", "finance"],
     "description": "审批工资单。"},
    {"name": "approve-sales-target", "path": "/mcp/approve-sales-target",
     "roles": ["boss", "sales_manager"],
     "description": "审批销售目标。"},
    {"name": "approve-fund-transfer", "path": "/mcp/approve-fund-transfer",
     "roles": ["boss", "finance"],
     "description": "批准资金调拨。"},
]

# ─── Legacy（6，不含 external-approve-and-fill-scheme）──────
# external-approve-and-fill-scheme 走的是 X-External-Open-Id 厂家外部身份，
# 不走 JWT，不在本 catalog —— Bridge 不暴露它给员工 Agent。
LEGACY_TOOLS: list[ToolEntry] = [
    {"name": "allocate-settlement-to-claims", "path": "/mcp/allocate-settlement-to-claims",
     "roles": ["boss", "finance"],
     "description": "预览厂家到账金额如何分配到各政策兑付理赔单（只算不写）。"},
    {"name": "query-barcode-tracing", "path": "/mcp/query-barcode-tracing",
     "roles": ["boss", "warehouse", "salesman", "sales_manager", "finance"],
     "description": "条码追溯：商品→批次→订单→客户→业务员的全链路。"},
    {"name": "submit-policy-approval", "path": "/mcp/submit-policy-approval",
     "roles": ["boss", "finance", "sales_manager", "salesman"],
     "description": "提交政策申请内部/厂家审批。"},
    {"name": "create-policy-usage-record", "path": "/mcp/create-policy-usage-record",
     "roles": ["boss", "finance", "salesman"],
     "description": "手工建政策使用记录（非出货场景，如品鉴）。"},
    {"name": "push-manufacturer-update", "path": "/mcp/push-manufacturer-update",
     "roles": ["boss", "finance", "sales_manager"],
     "description": "推送厂家动态通知并建 NotificationLog。"},
    {"name": "create-order-from-text", "path": "/mcp/create-order-from-text",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "用自然语言文本批量建单（salesman_id 强制=本人）。"},
]


ALL_TOOLS: list[ToolEntry] = QUERY_TOOLS + ACTION_TOOLS + APPROVAL_TOOLS + LEGACY_TOOLS


def tools_for_user(user: dict[str, Any]) -> list[ToolEntry]:
    """根据 JWT 的 roles 过滤可见工具。admin 看全部；其他按交集。"""
    roles = set(user.get("roles") or [])
    if "admin" in roles:
        return list(ALL_TOOLS)
    visible: list[ToolEntry] = []
    for t in ALL_TOOLS:
        allowed = t["roles"]
        if "*" in allowed or roles & set(allowed):
            visible.append(t)
    return visible


def get_tool(name: str) -> ToolEntry | None:
    for t in ALL_TOOLS:
        if t["name"] == name:
            return t
    return None
