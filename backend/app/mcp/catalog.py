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


# ─── 查询类（24）─────────────────────────────────────────────
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
     "roles": ["boss", "hr"],
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
    {"name": "query-purchase-orders", "path": "/mcp/query-purchase-orders",
     "roles": ["boss", "purchase", "warehouse", "finance"],
     "description": "查询采购单列表。支持按品牌/状态/关键字过滤。"},
    {"name": "query-expenses", "path": "/mcp/query-expenses",
     "roles": ["boss", "finance"],
     "description": "查询费用/报销列表。支持按品牌/状态过滤。"},
    {"name": "query-products", "path": "/mcp/query-products",
     "roles": ["*"],
     "description": "查询商品列表。支持按品牌/关键字过滤，返回商品 ID、编码、名称、售价。"},
    {"name": "query-suppliers", "path": "/mcp/query-suppliers",
     "roles": ["boss", "purchase", "warehouse"],
     "description": "查询供应商列表。创建采购单时需要 supplier_id。"},
    {"name": "query-fund-flows", "path": "/mcp/query-fund-flows",
     "roles": ["boss", "finance"],
     "description": "查询资金流水记录。支持按账户/品牌/流水类型过滤。"},
    {"name": "query-financing-orders", "path": "/mcp/query-financing-orders",
     "roles": ["boss", "finance"],
     "description": "查询融资单列表。含本金余额、利率、到期日等信息。"},
    {"name": "query-expense-claims", "path": "/mcp/query-expense-claims",
     "roles": ["boss", "finance"],
     "description": "查询报销理赔单列表。支持按品牌/状态过滤。"},
    {"name": "query-commissions", "path": "/mcp/query-commissions",
     "roles": ["boss", "hr", "finance"],
     "description": "查询提成列表。支持按员工/品牌/状态过滤。"},
    {"name": "query-leave-requests", "path": "/mcp/query-leave-requests",
     "roles": ["boss", "hr", "finance"],
     "description": "查询请假记录。支持按员工/状态/月份过滤。"},
    {"name": "query-warehouses", "path": "/mcp/query-warehouses",
     "roles": ["*"],
     "description": "查询仓库列表。创建采购单/订单时需要 warehouse_id。"},
]

# ─── 写入类（40）─────────────────────────────────────────────
ACTION_TOOLS: list[ToolEntry] = [
    {"name": "preview-order", "path": "/mcp/preview-order",
     "roles": ["*"],
     "description": "预览订单：自动匹配政策模板+计算价格+展示政策福利，不真正创建。建单前必须先调用让用户确认。"},
    {"name": "create-order", "path": "/mcp/create-order",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "创建销售订单。建单前应先调用 preview-order 让用户确认政策和价格。"},
    {"name": "register-payment", "path": "/mcp/register-payment",
     "roles": ["boss", "finance", "salesman"],
     "description": "登记订单收款（上传凭证等价动作）。建 Receipt+更新 payment_status。"},
    {"name": "create-customer", "path": "/mcp/create-customer",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "创建客户并绑定品牌-业务员关系。customer_type 只能是 channel（渠道）或 group_purchase（团购）。"},
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
    {"name": "update-customer", "path": "/mcp/update-customer",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "编辑客户信息（名称、联系人、联系电话、结算模式）。仅更新传入的非空字段。"},
    {"name": "create-purchase-order", "path": "/mcp/create-purchase-order",
     "roles": ["boss", "purchase", "warehouse"],
     "description": "创建采购单（含明细行）。状态 pending，需审批后执行。"},
    {"name": "create-expense", "path": "/mcp/create-expense",
     "roles": ["boss", "finance"],
     "description": "创建费用/报销记录。状态 pending，需审批。"},
    {"name": "create-inspection-case", "path": "/mcp/create-inspection-case",
     "roles": ["boss", "finance"],
     "description": "创建稽查案件。自动计算 profit_loss（窜出亏损/窜入盈利）。"},
    {"name": "create-sales-target", "path": "/mcp/create-sales-target",
     "roles": ["boss", "sales_manager"],
     "description": "创建销售目标（公司/品牌/员工级）。boss 建的直接 approved。"},
    {"name": "update-order-status", "path": "/mcp/update-order-status",
     "roles": ["boss", "warehouse", "salesman"],
     "description": "更新订单状态：ship（发货）/ confirm-delivery（确认送达）/ cancel（取消）。"},
    {"name": "create-financing-order", "path": "/mcp/create-financing-order",
     "roles": ["boss", "finance"],
     "description": "创建融资单。自动查找品牌融资账户，增加余额，记录流水。"},
    {"name": "create-product", "path": "/mcp/create-product",
     "roles": ["boss", "warehouse"],
     "description": "创建商品（编码、名称、品牌、每箱瓶数、售价、成本价）。"},
    {"name": "create-supplier", "path": "/mcp/create-supplier",
     "roles": ["boss", "purchase", "warehouse"],
     "description": "创建供应商（编码、名称、联系人、联系电话、地址）。"},
    {"name": "receive-purchase-order", "path": "/mcp/receive-purchase-order",
     "roles": ["boss", "warehouse", "purchase"],
     "description": "采购收货。将采购单状态更新为 received。"},
    {"name": "update-employee", "path": "/mcp/update-employee",
     "roles": ["boss", "hr"],
     "description": "编辑员工信息（姓名、电话、状态、社保）。仅更新传入的非空字段。"},
    {"name": "settle-commission", "path": "/mcp/settle-commission",
     "roles": ["boss", "hr", "finance"],
     "description": "结算提成。将提成状态设为 settled 并记录结算时间。"},
    {"name": "create-policy-template", "path": "/mcp/create-policy-template",
     "roles": ["boss", "finance"],
     "description": "创建政策模板（编码、名称、品牌、指导价、客户到手价、最低箱数、政策总价值）。建单时需要 policy_template_id。"},
    {"name": "pay-salary", "path": "/mcp/pay-salary",
     "roles": ["boss", "finance"],
     "description": "发放工资。支持单条（salary_record_id）或批量（batch_mode+period）发放所有已审批工资单。"},
    {"name": "batch-submit-salary", "path": "/mcp/batch-submit-salary",
     "roles": ["boss", "hr"],
     "description": "批量提交工资审批。将指定月份所有 draft 工资单提交为 pending_approval。"},
    {"name": "create-salary-scheme", "path": "/mcp/create-salary-scheme",
     "roles": ["boss", "hr"],
     "description": "创建/更新薪酬方案（品牌×岗位）。支持 upsert：brand_id+position_code 已存在则更新。"},
    {"name": "confirm-subsidy-arrival", "path": "/mcp/confirm-subsidy-arrival",
     "roles": ["boss", "finance"],
     "description": "确认厂家工资补贴到账。批量设置补贴状态为 reimbursed 并记录到账时间。"},
    # 政策兑付链路（Phase 3 薄壳化，替代旧的 fulfill-policy-materials / confirm-policy-fulfill）
    {"name": "fulfill-materials", "path": "/mcp/fulfill-materials",
     "roles": ["boss", "finance"],
     "description": "政策物料出库：从品鉴仓扣库存 + 更新 PolicyRequestItem.fulfilled_qty/fulfill_status。按瓶扣减，支持箱/瓶输入。"},
    {"name": "fulfill-item-status", "path": "/mcp/fulfill-item-status",
     "roles": ["boss", "finance"],
     "description": "更新政策明细项 fulfill_status（applied/fulfilled/settled），可带 actual_cost / scheme_no。"},
    {"name": "submit-policy-voucher", "path": "/mcp/submit-policy-voucher",
     "roles": ["boss", "finance", "salesman"],
     "description": "提交政策兑付凭证：arrived/settled → fulfilled。上传凭证 URL 到 item.voucher_urls。"},
    {"name": "confirm-fulfill", "path": "/mcp/confirm-fulfill",
     "roles": ["boss", "finance"],
     "description": "财务归档政策兑付：fulfilled → settled。进利润台账。幂等。"},
    {"name": "confirm-policy-arrival", "path": "/mcp/confirm-policy-arrival",
     "roles": ["boss", "finance"],
     "description": "批量确认政策到账（item 级）：item.fulfill_status=arrived + F 类账户加钱。幂等：已 arrived 跳过。"},
    {"name": "update-order", "path": "/mcp/update-order",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "编辑订单（仅 pending 状态）。可修改客户/业务员/备注/仓库。"},
    {"name": "submit-order-policy", "path": "/mcp/submit-order-policy",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "提交订单政策审批。pending → policy_pending_internal。"},
    {"name": "resubmit-order", "path": "/mcp/resubmit-order",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "重新提交被驳回的订单。policy_rejected → pending。"},
    {"name": "create-policy-request", "path": "/mcp/create-policy-request",
     "roles": ["boss", "finance", "salesman", "sales_manager"],
     "description": "创建政策申请（PolicyRequest + 明细行）。状态 draft。"},
    {"name": "bind-customer-brand-salesman", "path": "/mcp/bind-customer-brand-salesman",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "绑定/更新客户×品牌×业务员关系。已存在则更新，否则新建。"},
    {"name": "create-manufacturer-settlement", "path": "/mcp/create-manufacturer-settlement",
     "roles": ["boss", "finance"],
     "description": "创建厂家结算（到账）记录。状态 pending。"},
    {"name": "submit-financing-repayment", "path": "/mcp/submit-financing-repayment",
     "roles": ["boss", "finance"],
     "description": "提交融资还款申请。自动计算利息，创建 pending 状态还款单。"},
    {"name": "create-market-cleanup-case", "path": "/mcp/create-market-cleanup-case",
     "roles": ["boss", "finance"],
     "description": "创建市场清理案件。状态 pending。"},
    # Phase 3 新增写入类
    {"name": "cancel-purchase-order", "path": "/mcp/cancel-purchase-order",
     "roles": ["boss", "purchase"],
     "description": "撤销已付款采购单：反转账户变动（品牌 cash/F类/financing 恢复 + payment_to_mfr 反扣）。仅 paid 状态可撤销，已 received 走退货。"},
    {"name": "close-inspection-case", "path": "/mcp/close-inspection-case",
     "roles": ["boss", "finance"],
     "description": "归档稽查案件：executed → closed。进利润台账。"},
    {"name": "create-fund-transfer-request", "path": "/mcp/create-fund-transfer-request",
     "roles": ["boss", "finance"],
     "description": "发起资金调拨申请（不立即执行）。boss 批准时调 approve-fund-transfer。支持账户名/UUID。"},
    {"name": "upload-payment-voucher", "path": "/mcp/upload-payment-voucher",
     "roles": ["boss", "salesman", "sales_manager"],
     "description": "业务员上传收款凭证：建 pending_confirmation Receipt，不动账。等财务审批（confirm-order-payment）才入账 + 生成提成。与 register-payment（财务直录）路径不同。"},
]

# ─── 审批类（17）─────────────────────────────────────────────
APPROVAL_TOOLS: list[ToolEntry] = [
    {"name": "approve-order", "path": "/mcp/approve-order",
     "roles": ["boss"],
     "description": "审批订单（pending→approved 一步完成）。支持 approve/reject。boss 专属。"},
    {"name": "confirm-order-payment", "path": "/mcp/confirm-order-payment",
     "roles": ["boss", "finance"],
     "description": "财务确认订单收款（delivered+fully_paid → completed）。"},
    {"name": "approve-leave", "path": "/mcp/approve-leave",
     "roles": ["boss", "hr"],
     "description": "审批请假单。"},
    {"name": "approve-salary", "path": "/mcp/approve-salary",
     "roles": ["boss", "finance"],
     "description": "审批工资单。"},
    {"name": "approve-sales-target", "path": "/mcp/approve-sales-target",
     "roles": ["boss", "sales_manager"],
     "description": "审批销售目标。"},
    {"name": "approve-fund-transfer", "path": "/mcp/approve-fund-transfer",
     "roles": ["boss"],
     "description": "批准资金调拨。"},
    {"name": "approve-purchase-order", "path": "/mcp/approve-purchase-order",
     "roles": ["boss", "finance"],
     "description": "审批采购单。approve → approved；reject → cancelled。"},
    {"name": "approve-expense", "path": "/mcp/approve-expense",
     "roles": ["boss", "finance"],
     "description": "审批费用。approve（通过）/ reject（驳回）/ pay（标记已付）。"},
    {"name": "approve-inspection", "path": "/mcp/approve-inspection",
     "roles": ["boss", "finance"],
     "description": "执行稽查案件（pending → confirmed）。只有已执行案件才进利润台账。"},
    {"name": "reject-fund-transfer", "path": "/mcp/reject-fund-transfer",
     "roles": ["boss"],
     "description": "拒绝资金调拨申请。将待审批状态改为已驳回。"},
    {"name": "approve-financing-repayment", "path": "/mcp/approve-financing-repayment",
     "roles": ["boss", "finance"],
     "description": "审批融资还款。approve（通过并执行扣款）/ reject（驳回）。"},
    {"name": "approve-expense-claim", "path": "/mcp/approve-expense-claim",
     "roles": ["boss", "finance"],
     "description": "审批报销理赔。approve（通过）/ reject（驳回）/ pay（标记已付）。"},
    {"name": "complete-order", "path": "/mcp/complete-order",
     "roles": ["boss", "finance"],
     "description": "完成订单（delivered → completed）。不要求 fully_paid 前置条件。"},
    {"name": "approve-policy-claim", "path": "/mcp/approve-policy-claim",
     "roles": ["boss", "finance"],
     "description": "审批政策理赔单（PolicyClaim）。approve（通过）/ reject（驳回）。注意不同于 approve-expense-claim。"},
    {"name": "reject-order-policy", "path": "/mcp/reject-order-policy",
     "roles": ["boss"],
     "description": "驳回订单政策审批。policy_pending_internal/external → policy_rejected。boss 专属。"},
    {"name": "confirm-settlement-allocation", "path": "/mcp/confirm-settlement-allocation",
     "roles": ["boss", "finance"],
     "description": "确认厂家结算分配到政策理赔单。调用内部 confirm_settlement_allocation 逻辑。"},
    {"name": "create-policy-claim", "path": "/mcp/create-policy-claim",
     "roles": ["boss", "finance"],
     "description": "创建政策理赔单（PolicyClaim）。自动生成 claim_no，状态 draft。"},
    # Phase 3 新增审批类
    {"name": "reject-payment-receipts", "path": "/mcp/reject-payment-receipts",
     "roles": ["boss", "finance"],
     "description": "财务驳回订单所有 pending 收款凭证：Receipt.status=rejected + Order.payment_status 回退。需带驳回原因。对应前端 FinanceApproval 驳回按钮。"},
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

# 写入/审批类工具名 —— bridge 在 list_tools 时给这些工具的 description
# 加上 ⚠️ 前缀，明确告知 Agent 这些工具与前端业务可能不对齐。
# 查询类只读工具相对安全，不加前缀。
WRITE_TOOL_NAMES: set[str] = {t["name"] for t in ACTION_TOOLS + APPROVAL_TOOLS}


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
