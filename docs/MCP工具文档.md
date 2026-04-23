# 新鑫久隆 ERP — MCP 工具文档

> 版本：v3.0 | 日期：2026-04-22

---

## 1. 概述

MCP（Model Context Protocol）是系统暴露给 AI Agent 的工具集，让 AI 能像人一样查询和操作 ERP 系统。

### 1.1 规模

| 指标 | 数量 |
|---|---|
| 总工具数 | 86 |
| 查询工具 | 24 |
| 操作工具 | 39 |
| 审批工具 | 17 |
| 飞书旧版（legacy） | 6 |

### 1.2 调用方

| 调用方 | 认证方式 | 安全机制 |
|---|---|---|
| Claude Code / 外部 Agent | JWT Bearer Token | PostgreSQL RLS 14 张表行级安全 |
| 飞书 AI 网关（openclaw） | X-External-Open-Id Header | manufacturer_external_identities 表 + brand_scope |

### 1.3 端点前缀

所有 MCP 工具挂在 `/mcp/` 下，统一用 `POST` 方法。

---

## 2. 认证

### 2.1 JWT 模式（内部 Agent）

```
POST /mcp/query-orders
Authorization: Bearer <access_token>
Content-Type: application/json
```

- Token 从 `POST /api/auth/login` 获取
- 载荷含 `roles` / `brand_ids` / `is_admin` / `employee_id`
- 请求走 `erp_app` 引擎，受 RLS 约束——Agent 只能看到该用户权限内的数据
- **即使 Agent 被 prompt 注入，也无法越权访问其他品牌数据**

### 2.2 飞书模式（厂家 AI 网关）

```
POST /mcp/external-approve-and-fill-scheme
X-External-Open-Id: ou_xxxxxxxxxxxxxxxxx
Content-Type: application/json
```

- 飞书用户的 `open_id` 必须在 `manufacturer_external_identities` 表中注册且 `status=active`
- 品牌范围由 `brand_scope` JSONB 字段控制
- 请求走 `admin` 引擎（绕过 RLS），但代码层强制 brand_scope 过滤

### 2.3 无认证 → 401

两种认证都没有的请求直接返回 `401 Unauthorized`。

---

## 3. 查询工具（24 个）

所有查询工具只读，不修改数据。

### 3.1 query-orders — 订单列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-orders
{
  "brand_id": "可选，品牌 ID",
  "status": "可选，pending/approved/shipped/delivered/completed",
  "payment_status": "可选，unpaid/partially_paid/fully_paid",
  "keyword": "可选，订单号模糊搜索",
  "limit": 20
}
```

返回：订单号、客户、业务员、金额、结算模式、状态、商品明细。

### 3.2 query-order-detail — 订单详情

角色：`*`（任何登录员工）

```json
POST /mcp/query-order-detail
{
  "order_no": "SO-20260419165559-0f88aa"
}
```

返回：订单完整信息 + 所有收款记录（金额、来源、日期）。

### 3.3 query-customers — 客户列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-customers
{
  "brand_id": "可选",
  "keyword": "可选，按名称/联系人搜索",
  "limit": 20
}
```

### 3.4 query-inventory — 库存查询

角色：`boss / warehouse / salesman / sales_manager / purchase / finance`

```json
POST /mcp/query-inventory
{
  "brand_id": "可选",
  "product_keyword": "可选",
  "low_stock_only": false
}
```

返回：商品、仓库、瓶数、箱数、成本单价、库存价值。`low_stock_only=true` 只看低库存（< 10 箱）。

### 3.5 query-profit-summary — 利润台账

角色：`boss / finance / sales_manager`

```json
POST /mcp/query-profit-summary
{
  "brand_id": "可选",
  "date_from": "2026-04-01",
  "date_to": "2026-04-30"
}
```

返回 11 个利润科目汇总。

### 3.6 query-account-balances — 账户余额

角色：`boss / finance`

```json
POST /mcp/query-account-balances
{
  "brand_id": "可选"
}
```

返回：账户名、类型（现金/F类/融资/回款）、级别（master/project）、品牌、余额。

> 注意：非 admin/boss 用户看不到 master 账户（RLS 过滤）。

### 3.7 query-salary-records — 工资单

角色：`boss / finance`

```json
POST /mcp/query-salary-records
{
  "period": "2026-04",
  "employee_name": "可选，模糊搜索"
}
```

返回：员工、周期、应发、实发、提成、状态。

### 3.8 query-sales-targets — 销售目标

角色：`boss / finance / sales_manager / salesman`

```json
POST /mcp/query-sales-targets
{
  "target_year": 2026,
  "target_level": "可选，company/brand/employee",
  "brand_id": "可选"
}
```

只返回 `status=approved` 的目标。

### 3.9 query-inspection-cases — 稽查案件

角色：`boss / finance`

```json
POST /mcp/query-inspection-cases
{
  "brand_id": "可选",
  "status": "可选，pending/approved/executed",
  "limit": 20
}
```

返回：案件号、类型、方向、数量、盈亏、状态。

### 3.10 query-manufacturer-subsidies — 厂家补贴

角色：`boss / finance`

```json
POST /mcp/query-manufacturer-subsidies
{
  "brand_id": "可选",
  "period": "可选，如 2026-04",
  "status": "可选，pending/advanced/reimbursed"
}
```

### 3.11 query-attendance-summary — 考勤汇总

角色：`boss / hr`

```json
POST /mcp/query-attendance-summary
{
  "period": "2026-04"
}
```

返回：每位员工的出勤天数、迟到次数、请假天数、是否全勤。

### 3.12 query-policy-templates — 政策模板列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-policy-templates
{
  "brand_id": "可选",
  "keyword": "可选，按名称搜索"
}
```

返回：模板 ID、编码、名称、品牌、指导价、客户到手价、最小箱数、政策总价值。建单时需要 `policy_template_id`。

### 3.13 query-brands — 品牌列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-brands
{}
```

返回：品牌 ID、编码（QHL/WLY/FJ/Z15）、名称。建单/建客户/绑岗位时需要 `brand_id`。

### 3.14 query-positions — 岗位字典

角色：`*`（任何登录员工）

```json
POST /mcp/query-positions
{}
```

返回：岗位代码（salesman/sales_manager/finance/warehouse...）和中文名。绑定员工品牌岗位时需要 `position_code`。

### 3.15 query-purchase-orders — 采购单列表

角色：`boss / purchase / warehouse / finance`

```json
POST /mcp/query-purchase-orders
{
  "brand_id": "可选",
  "status": "可选",
  "keyword": "可选，按采购单号搜索",
  "limit": 20
}
```

返回：采购单号、供应商、品牌、总金额、状态、明细行。

### 3.16 query-expenses — 费用/报销列表

角色：`boss / finance`

```json
POST /mcp/query-expenses
{
  "brand_id": "可选",
  "status": "可选",
  "limit": 20
}
```

返回：报销单号、类型、标题、金额、品牌、申请人、状态。

### 3.17 query-products — 商品列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-products
{
  "brand_id": "可选",
  "keyword": "可选，按名称/编码搜索",
  "limit": 50
}
```

返回：商品 ID、编码、名称、品牌、每箱瓶数、售价、成本价。

### 3.18 query-suppliers — 供应商列表

角色：`boss / purchase / warehouse`

```json
POST /mcp/query-suppliers
{
  "keyword": "可选，按名称/编码搜索",
  "limit": 50
}
```

返回：供应商 ID、编码、名称、类型、联系人。创建采购单时需要 `supplier_id`。

### 3.19 query-fund-flows — 资金流水

角色：`boss / finance`

```json
POST /mcp/query-fund-flows
{
  "account_id": "可选",
  "brand_id": "可选",
  "flow_type": "可选，credit/debit/transfer_pending/transfer_in/transfer_out",
  "limit": 50
}
```

返回：流水号、类型、金额、操作后余额、账户名、关联类型。

### 3.20 query-financing-orders — 融资单列表

角色：`boss / finance`

```json
POST /mcp/query-financing-orders
{
  "brand_id": "可选",
  "status": "可选，active/settled/overdue",
  "limit": 20
}
```

返回：融资单号、品牌、本金、未还余额、利率、起止日期、银行、状态。

### 3.21 query-expense-claims — 报销理赔单列表

角色：`boss / finance`

```json
POST /mcp/query-expense-claims
{
  "brand_id": "可选",
  "status": "可选",
  "limit": 20
}
```

返回：理赔单号、品牌、类别、金额、状态。

### 3.22 query-commissions — 提成列表

角色：`boss / hr / finance`

```json
POST /mcp/query-commissions
{
  "employee_id": "可选",
  "brand_id": "可选",
  "status": "可选",
  "limit": 50
}
```

返回：员工、品牌、订单关联、提成金额、状态。

### 3.23 query-leave-requests — 请假记录

角色：`boss / hr / finance`

```json
POST /mcp/query-leave-requests
{
  "employee_id": "可选",
  "status": "可选，pending/approved/rejected",
  "period": "可选，YYYY-MM",
  "limit": 20
}
```

返回：员工、假别、起止日期、天数、状态。

### 3.24 query-warehouses — 仓库列表

角色：`*`（任何登录员工）

```json
POST /mcp/query-warehouses
{
  "brand_id": "可选"
}
```

返回：仓库 ID、编码、名称、类型、品牌。创建采购单/订单时需要 `warehouse_id`。

---

## 4. 操作工具（39 个）

写入数据，受 RLS + 角色约束。

> **ID 回退查找**：所有操作工具的 ID 参数（customer_id / brand_id / product_id / salesman_id 等）支持三种查找方式：UUID、业务编码、名称。系统按 UUID → code → name 顺序自动匹配。

### 4.1 create-order — 创建订单

角色：`boss / salesman / sales_manager`

```json
POST /mcp/create-order
{
  "customer_id": "客户 ID",
  "salesman_id": "业务员 ID",
  "policy_template_id": "政策模板 ID（必填，指导价从此读取）",
  "settlement_mode": "customer_pay / employee_pay / company_pay",
  "items": [
    {"product_id": "商品 ID", "quantity": 5, "quantity_unit": "箱"}
  ],
  "deal_unit_price": "可选，覆盖模板客户到手价",
  "advance_payer_id": "可选，employee_pay 时的垫付人",
  "warehouse_id": "可选，出库仓",
  "notes": "可选"
}
```

- 单价强制从政策模板 `required_unit_price` 取，前端/Agent 无法手填
- `customer_paid_amount` 按结算模式自动计算
- salesman 调用时 `salesman_id` 强制=本人

### 4.2 register-payment — 登记收款

角色：`boss / finance / salesman`

```json
POST /mcp/register-payment
{
  "order_no": "SO-20260419165559-0f88aa",
  "amount": 19500,
  "source_type": "customer"
}
```

- `source_type`：`customer`（客户付款）/ `employee_advance`（业务员垫付）
- 自动建 Receipt + 进 master 现金池 + 更新 payment_status
- 全款跃升时通知财务

### 4.3 create-customer — 创建客户

角色：`boss / salesman / sales_manager`

```json
POST /mcp/create-customer
{
  "code": "C-AI-001",
  "name": "AI创建的客户",
  "brand_id": "品牌 ID",
  "customer_type": "channel 或 group_purchase，默认 channel",
  "salesman_id": "可选，绑定业务员",
  "contact_name": "联系人",
  "contact_phone": "手机号",
  "settlement_mode": "cash"
}
```

- `customer_type`: `Literal["channel", "group_purchase"]`，默认 `"channel"`。渠道客户 vs 团购客户。
- 自动建 CustomerBrandSalesman 关联。

### 4.4 create-leave-request — 提交请假

角色：`*`（任何登录员工）

```json
POST /mcp/create-leave-request
{
  "employee_id": "员工 ID",
  "leave_type": "sick / personal / annual / overtime_off",
  "start_date": "2026-04-20",
  "end_date": "2026-04-21",
  "total_days": 1.5,
  "reason": "身体不适"
}
```

创建后状态为 `pending`，需在审批中心处理。`employee_id` 自动=当前用户（admin/boss 除外可代提）。

### 4.5 create-employee — 创建员工

角色：`boss / hr`

```json
POST /mcp/create-employee
{
  "employee_no": "E-001",
  "name": "张三",
  "position": "可选，职务描述",
  "phone": "可选",
  "hire_date": "可选，YYYY-MM-DD",
  "social_security": 0,
  "company_social_security": 0,
  "expected_manufacturer_subsidy": 0
}
```

工号全局唯一。

### 4.6 query-employees — 查询员工列表

角色：`boss / hr / finance / sales_manager`

```json
POST /mcp/query-employees
{
  "keyword": "可选，按姓名/工号搜索",
  "status": "可选，active/on_leave/left",
  "brand_id": "可选，按品牌过滤",
  "limit": 50
}
```

### 4.7 bind-employee-brand — 绑定员工品牌岗位

角色：`boss / hr`

```json
POST /mcp/bind-employee-brand
{
  "employee_id": "员工 ID",
  "brand_id": "品牌 ID",
  "position_code": "岗位代码（如 salesman）",
  "commission_rate": "可选，个性化提成率",
  "manufacturer_subsidy": 0,
  "is_primary": false
}
```

`is_primary=true` 时自动取消该员工其他品牌的主属标记。

### 4.8 create-user — 创建登录账号

角色：`boss`

```json
POST /mcp/create-user
{
  "username": "zhangsan",
  "password": "初始密码",
  "employee_id": "可选，关联员工 ID",
  "role_codes": ["salesman"]
}
```

用户名全局唯一。

### 4.9 generate-salary — 生成工资单

角色：`boss / finance`

```json
POST /mcp/generate-salary
{
  "period": "2026-04",
  "overwrite": false
}
```

一键生成本期工资单。

### 4.10 generate-subsidy-expected — 生成补贴应收

角色：`boss / finance`

```json
POST /mcp/generate-subsidy-expected
{
  "period": "2026-04"
}
```

生成本月厂家工资补贴应收。

### 4.11 create-fund-transfer — 创建资金调拨申请

角色：`boss / finance`

```json
POST /mcp/create-fund-transfer
{
  "to_brand_name": "可选，品牌名（自动查 brand cash 账户）",
  "to_account_id": "可选，或直接指定账户 ID",
  "amount": 50000,
  "notes": "可选"
}
```

从 master 现金池调拨到品牌项目账户（现金或融资）。创建后状态为"待审批"，需老板审批后执行。

### 4.12 update-customer — 编辑客户信息

角色：`boss / salesman / sales_manager`

```json
POST /mcp/update-customer
{
  "customer_id": "客户 ID",
  "name": "可选",
  "contact_name": "可选",
  "contact_phone": "可选",
  "settlement_mode": "可选"
}
```

仅更新传入的非空字段。

### 4.13 create-purchase-order — 创建采购单

角色：`boss / purchase / warehouse`

```json
POST /mcp/create-purchase-order
{
  "supplier_id": "供应商 ID",
  "brand_id": "品牌 ID",
  "warehouse_id": "仓库 ID",
  "items": [
    {"product_id": "商品 ID", "quantity": 10, "unit_price": 150.00}
  ],
  "notes": "可选"
}
```

状态为 `pending`，需审批后执行。

### 4.14 create-expense — 创建费用/报销

角色：`boss / finance`

```json
POST /mcp/create-expense
{
  "brand_id": "品牌 ID",
  "category": "f_class / daily",
  "amount": 5000,
  "description": "描述",
  "expense_date": "可选，YYYY-MM-DD"
}
```

状态为 `pending`，需审批。

### 4.15 create-inspection-case — 创建稽查案件

角色：`boss / finance`

```json
POST /mcp/create-inspection-case
{
  "brand_id": "品牌 ID",
  "case_type": "inspection_violation / market_cleanup / ...",
  "direction": "outflow / inflow",
  "product_id": "可选",
  "quantity": "可选，瓶数",
  "deal_unit_price": "可选，到手价",
  "purchase_price": "可选，回收价/买入价",
  "sale_price": "可选，转卖价",
  "penalty_amount": "可选，罚款",
  "notes": "可选"
}
```

自动计算 `profit_loss`。A1 亏损公式：`-(回收价 - 到手价) * 瓶数 - 罚款`。

### 4.16 create-sales-target — 创建销售目标

角色：`boss / sales_manager`

```json
POST /mcp/create-sales-target
{
  "target_level": "company / brand / employee",
  "target_year": 2026,
  "target_month": "可选",
  "brand_id": "可选（品牌级必填）",
  "employee_id": "可选（员工级必填）",
  "sales_target": 1000000,
  "receipt_target": 800000
}
```

boss 建的目标直接 `approved`；sales_manager 建的走 `pending_approval`。

### 4.17 update-order-status — 更新订单状态

角色：`boss / warehouse / salesman`

```json
POST /mcp/update-order-status
{
  "order_id": "订单 ID",
  "action": "ship / confirm-delivery / cancel"
}
```

- `ship`：approved → shipped（发货）
- `confirm-delivery`：shipped → delivered（确认送达）
- `cancel`：pending/approved → rejected（取消）

### 4.18 create-financing-order — 创建融资单

角色：`boss / finance`

```json
POST /mcp/create-financing-order
{
  "brand_id": "品牌 ID",
  "amount": 100000,
  "interest_rate": "可选，日利率",
  "start_date": "YYYY-MM-DD",
  "maturity_date": "可选，YYYY-MM-DD",
  "bank_name": "可选",
  "notes": "可选"
}
```

自动查找品牌融资账户，增加余额，记录流水。

### 4.19 create-product — 创建商品

角色：`boss / warehouse`

```json
POST /mcp/create-product
{
  "code": "SKU-001",
  "name": "商品名",
  "brand_id": "品牌 ID",
  "bottles_per_case": 6,
  "sale_price": "可选，售价",
  "cost_price": "可选，成本价"
}
```

编码全局唯一。

### 4.20 create-supplier — 创建供应商

角色：`boss / purchase / warehouse`

```json
POST /mcp/create-supplier
{
  "code": "SUP-001",
  "name": "供应商名",
  "contact_name": "可选",
  "contact_phone": "可选",
  "address": "可选"
}
```

编码全局唯一。

### 4.21 receive-purchase-order — 采购收货

角色：`boss / warehouse / purchase`

```json
POST /mcp/receive-purchase-order
{
  "po_id": "采购单 ID",
  "received_items": [
    {"product_id": "商品 ID", "received_quantity": 10}
  ]
}
```

将采购单状态从 approved/shipped 更新为 received。

### 4.22 update-employee — 编辑员工信息

角色：`boss / hr`

```json
POST /mcp/update-employee
{
  "employee_id": "员工 ID",
  "name": "可选",
  "phone": "可选",
  "status": "可选，active/on_leave/left",
  "social_security": "可选",
  "company_social_security": "可选"
}
```

仅更新传入的非空字段。

### 4.23 settle-commission — 结算提成

角色：`boss / hr / finance`

```json
POST /mcp/settle-commission
{
  "commission_id": "提成记录 ID"
}
```

将提成状态设为 `settled`，记录结算时间。

### 4.24 create-policy-template — 创建政策模板

角色：`boss / finance`

```json
POST /mcp/create-policy-template
{
  "code": "QHL-2026-A1",
  "name": "青花郎53度渠道政策",
  "brand_id": "品牌 ID",
  "required_unit_price": 885,
  "customer_unit_price": 650,
  "min_cases": 10,
  "total_policy_value": 8500
}
```

编码全局唯一。建单时需要 `policy_template_id`。

### 4.25 pay-salary — 发放工资

角色：`boss / finance`

```json
POST /mcp/pay-salary
{
  "salary_record_id": "可选，单条发放",
  "batch_mode": false,
  "period": "可选，批量发放月份（如 2026-04）"
}
```

支持单条（`salary_record_id`）或按月批量（`batch_mode=true` + `period`）发放所有已审批工资单。从品牌现金账户扣款。

### 4.26 batch-submit-salary — 批量提交工资审批

角色：`boss / hr`

```json
POST /mcp/batch-submit-salary
{
  "period": "2026-04"
}
```

将指定月份所有 `draft` 工资单批量提交为 `pending_approval`。

### 4.27 create-salary-scheme — 创建/更新薪酬方案

角色：`boss / hr`

```json
POST /mcp/create-salary-scheme
{
  "brand_id": "品牌 ID",
  "position_code": "salesman",
  "fixed_salary": 3000,
  "variable_salary_max": 1500,
  "attendance_bonus_full": 200,
  "commission_rate": 0.01,
  "manager_share_rate": 0.003
}
```

Upsert 模式：同品牌+岗位已存在则更新，否则新建。

### 4.28 confirm-subsidy-arrival — 确认厂家工资补贴到账

角色：`boss / finance`

```json
POST /mcp/confirm-subsidy-arrival
{
  "subsidy_ids": ["补贴记录ID1", "补贴记录ID2"]
}
```

批量设置补贴状态为 `reimbursed` 并记录到账时间。

### 4.29 fulfill-policy-materials — 更新政策物料兑付

角色：`boss / finance`

```json
POST /mcp/fulfill-policy-materials
{
  "items": [
    {"item_id": "政策明细项 ID", "fulfilled_qty": 10}
  ]
}
```

逐条更新 PolicyRequestItem 的 `fulfilled_qty`。

### 4.30 confirm-policy-arrival — 确认政策到账

角色：`boss / finance`

```json
POST /mcp/confirm-policy-arrival
{
  "policy_request_id": "政策申请 ID"
}
```

将政策申请状态设为 approved。

### 4.31 confirm-policy-fulfill — 确认政策兑付完成

角色：`boss / finance`

```json
POST /mcp/confirm-policy-fulfill
{
  "policy_request_id": "政策申请 ID"
}
```

标记政策申请及所有未兑付项为 fulfilled。

### 4.32 update-order — 编辑订单

角色：`boss / salesman / sales_manager`

```json
POST /mcp/update-order
{
  "order_no": "SO-20260419-xxxxxx",
  "customer_id": "可选",
  "salesman_id": "可选",
  "notes": "可选",
  "warehouse_id": "可选"
}
```

仅 `pending` 状态可编辑。只更新传入的非空字段。

### 4.33 submit-order-policy — 提交订单政策审批

角色：`boss / salesman / sales_manager`

```json
POST /mcp/submit-order-policy
{
  "order_no": "SO-20260419-xxxxxx"
}
```

`pending` → `policy_pending_internal`。

### 4.34 resubmit-order — 重新提交被驳回的订单

角色：`boss / salesman / sales_manager`

```json
POST /mcp/resubmit-order
{
  "order_no": "SO-20260419-xxxxxx"
}
```

`policy_rejected` → `pending`。

### 4.35 create-policy-request — 创建政策申请

角色：`boss / finance / salesman / sales_manager`

```json
POST /mcp/create-policy-request
{
  "brand_id": "品牌 ID",
  "order_id": "可选，关联订单",
  "policy_template_id": "可选，关联政策模板",
  "scheme_no": "可选，方案编号",
  "items": [
    {"product_id": "商品 ID", "quantity": 5, "quantity_unit": "箱"}
  ]
}
```

创建 PolicyRequest + PolicyRequestItem，状态 `draft`。

### 4.36 bind-customer-brand-salesman — 绑定客户品牌业务员

角色：`boss / salesman / sales_manager`

```json
POST /mcp/bind-customer-brand-salesman
{
  "customer_id": "客户 ID/编码/名称",
  "brand_id": "品牌 ID/编码/名称",
  "salesman_id": "业务员 ID/工号/姓名"
}
```

已存在（同客户+品牌）则更新业务员，否则新建。支持 ID 回退查找。

### 4.37 create-manufacturer-settlement — 创建厂家结算记录

角色：`boss / finance`

```json
POST /mcp/create-manufacturer-settlement
{
  "brand_id": "品牌 ID",
  "settlement_date": "2026-04-20",
  "amount": 50000,
  "notes": "可选"
}
```

记录厂家打款，状态 `pending`。后续通过 `confirm-settlement-allocation` 分配到理赔单。

### 4.38 submit-financing-repayment — 提交融资还款申请

角色：`boss / finance`

```json
POST /mcp/submit-financing-repayment
{
  "financing_order_id": "融资单 ID",
  "principal_amount": 100000,
  "payment_account_id": "品牌现金账户 ID",
  "f_class_amount": 0,
  "notes": "可选"
}
```

自动计算利息（`principal × rate / 100 × days / 365`），创建 `pending` 状态还款单。

### 4.39 create-market-cleanup-case — 创建市场清理案件

角色：`boss / finance`

```json
POST /mcp/create-market-cleanup-case
{
  "brand_id": "品牌 ID",
  "case_type": "market_cleanup",
  "product_id": "可选",
  "quantity": "可选，瓶数",
  "quantity_unit": "瓶",
  "notes": "可选"
}
```

状态 `pending`，需审批后执行。

---

## 5. 审批工具（17 个）

审批类工具，按各自角色要求控制访问。

### 5.1 confirm-order-payment — 确认收款

角色：`boss / finance`

```json
POST /mcp/confirm-order-payment
{
  "order_no": "SO-20260419165559-0f88aa"
}
```

前提：订单 `status=delivered` + `payment_status=fully_paid`。确认后 → `completed`。

### 5.2 approve-leave — 审批请假

角色：`boss / hr`

```json
POST /mcp/approve-leave
{
  "request_no": "LV-20260420-xxxxxx",
  "approved": true,
  "reject_reason": "可选，驳回时填"
}
```

### 5.3 approve-salary — 审批工资

角色：`boss / finance`

```json
POST /mcp/approve-salary
{
  "salary_record_id": "工资单 ID",
  "approved": true,
  "reject_reason": "可选"
}
```

前提：`status=pending_approval`。

### 5.4 approve-sales-target — 审批销售目标

角色：`boss / sales_manager`

```json
POST /mcp/approve-sales-target
{
  "target_id": "目标 ID",
  "approved": true,
  "reject_reason": "可选"
}
```

前提：`status=pending_approval`。

### 5.5 approve-fund-transfer — 审批资金调拨

角色：`boss`

```json
POST /mcp/approve-fund-transfer
{
  "transfer_id": "调拨流水 ID"
}
```

批准后直接执行转账（master → 品牌账户）。

### 5.6 approve-purchase-order — 审批采购单

角色：`boss / finance`

```json
POST /mcp/approve-purchase-order
{
  "po_id": "采购单 ID",
  "action": "approve / reject",
  "reject_reason": "可选，驳回时填"
}
```

approve → approved；reject → cancelled。

### 5.7 approve-expense — 审批费用

角色：`boss / finance`

```json
POST /mcp/approve-expense
{
  "expense_id": "费用 ID",
  "action": "approve / reject / pay",
  "reject_reason": "可选，驳回时填"
}
```

approve（通过）/ reject（驳回）/ pay（标记已付）。

### 5.8 approve-inspection — 执行稽查案件

角色：`boss / finance`

```json
POST /mcp/approve-inspection
{
  "case_id": "稽查案件 ID",
  "action": "execute"
}
```

pending → confirmed。只有已执行案件才进利润台账。

### 5.9 reject-fund-transfer — 拒绝资金调拨

角色：`boss`

```json
POST /mcp/reject-fund-transfer
{
  "transfer_id": "调拨流水 ID",
  "reject_reason": "可选"
}
```

将待审批状态改为已驳回。

### 5.10 approve-financing-repayment — 审批融资还款

角色：`boss / finance`

```json
POST /mcp/approve-financing-repayment
{
  "repayment_id": "还款申请 ID",
  "action": "approve / reject",
  "reject_reason": "可选，驳回时填"
}
```

approve（通过并执行扣款）/ reject（驳回）。

### 5.11 approve-expense-claim — 审批报销理赔

角色：`boss / finance`

```json
POST /mcp/approve-expense-claim
{
  "claim_id": "理赔单 ID",
  "action": "approve / reject / pay",
  "reject_reason": "可选，驳回时填"
}
```

approve（通过）/ reject（驳回）/ pay（标记已付）。

### 5.12 approve-order — 审批订单

角色：`boss`

```json
POST /mcp/approve-order
{
  "order_no": "SO-20260419-xxxxxx",
  "action": "approve",
  "need_external": false,
  "reject_reason": "可选，驳回时填"
}
```

- `action=approve`：pending 自动先提交再审批（一步到位 → approved）
- `action=reject`：驳回 → policy_rejected
- `need_external=true`：经内部审批后还需厂家审批（→ policy_pending_external）

### 5.13 reject-order-policy — 驳回订单政策

角色：`boss`

```json
POST /mcp/reject-order-policy
{
  "order_no": "SO-20260419-xxxxxx",
  "reject_reason": "可选"
}
```

`policy_pending_internal` / `policy_pending_external` → `policy_rejected`。boss 专属。

### 5.14 confirm-settlement-allocation — 确认厂家结算分配

角色：`boss / finance`

```json
POST /mcp/confirm-settlement-allocation
{
  "settlement_id": "厂家结算单 ID",
  "claim_id": "政策理赔单 ID",
  "allocated_amount": 15000
}
```

将厂家到账金额分配到指定政策理赔单。

### 5.15 create-policy-claim — 创建政策理赔单

角色：`boss / finance`

```json
POST /mcp/create-policy-claim
{
  "policy_request_id": "政策申请 ID",
  "claim_type": "standard",
  "notes": "可选"
}
```

自动生成 `claim_no`，从关联的政策申请明细创建理赔行项目。状态 `draft`。

### 5.16 approve-policy-claim — 审批政策理赔

角色：`boss / finance`

```json
POST /mcp/approve-policy-claim
{
  "claim_id": "理赔单 ID 或 claim_no",
  "action": "approve / reject",
  "reject_reason": "可选，驳回时填"
}
```

审批政策理赔单（PolicyClaim）。注意与 approve-expense-claim（费用报销）不同。

### 5.17 complete-order — 完成订单

角色：`boss / finance`

```json
POST /mcp/complete-order
{
  "order_no": "SO-20260419-xxxxxx"
}
```

`delivered` → `completed`。与 `confirm-order-payment` 的区别：**不要求 fully_paid 前置条件**。

---

## 6. 飞书专用工具（6 个，legacy 保留）

这些工具服务飞书群聊 AI 网关，用 `X-External-Open-Id` 认证。通过 MCP Streamable-HTTP bridge 暴露给 openclaw 等外部 Agent。

JWT 模式下的角色如下（从 catalog.py 取）：

### 6.1 allocate-settlement-to-claims — 结算分配预览

角色：`boss / finance`

```json
POST /mcp/allocate-settlement-to-claims
{
  "settlement_id": "厂家结算单 ID"
}
```

AI 按比例生成分配建议（只预览不写入），需财务确认。

### 6.2 query-barcode-tracing — 条码追溯

角色：`boss / warehouse / salesman / sales_manager / finance`

```json
POST /mcp/query-barcode-tracing
{
  "barcode": "6901234567890"
}
```

返回完整供应链：条码 → 批次 → 入库流水 → 出库订单 → 客户 → 业务员。

### 6.3 submit-policy-approval — 提交政策审批

角色：`boss / finance / sales_manager / salesman`

```json
POST /mcp/submit-policy-approval
{
  "policy_request_id": "政策申请 ID"
}
```

### 6.4 create-policy-usage-record — 创建政策使用记录

角色：`boss / finance / salesman`

```json
POST /mcp/create-policy-usage-record
{
  "policy_request_id": "...",
  "benefit_item_type": "品鉴会",
  "usage_description": "...",
  "planned_amount": 5000
}
```

非发货场景（品鉴会、旅游等）手工创建使用记录。

### 6.5 push-manufacturer-update — 推送厂家通知

角色：`boss / finance / sales_manager`

```json
POST /mcp/push-manufacturer-update
{
  "recipient_open_id": "ou_xxxxx",
  "title": "政策到账通知",
  "content": "..."
}
```

### 6.6 create-order-from-text — 自然语言建单

角色：`boss / salesman / sales_manager`

```json
POST /mcp/create-order-from-text
{
  "text": "王永 买 5 箱青花郎"
}
```

AI 解析自然语言，匹配客户/商品/政策，创建订单。

> `external-approve-and-fill-scheme` 走飞书 `X-External-Open-Id` 认证，不走 JWT，不在 catalog 中。

---

## 7. ID 回退查找（Fallback Lookup）

所有操作工具的 ID 参数（customer_id / brand_id / product_id / salesman_id 等）支持三种查找方式：

| 查找顺序 | 方式 | 示例 |
|---|---|---|
| 1 | UUID 精确匹配 | `"a1b2c3d4-..."` |
| 2 | 业务编码匹配 | `"C-001"`（客户编码）、`"QHL"`（品牌编码）、`"E-001"`（工号） |
| 3 | 名称匹配 | `"张三烟酒"`（客户名）、`"青花郎"`（品牌名）、`"李四"`（员工名） |

涉及 13 个工具、22 个参数。Agent 无需先查 UUID 再操作，可直接传名称或编码。

---

## 8. 错误码

| HTTP 状态 | 说明 |
|---|---|
| 200 | 成功 |
| 400 | 参数错误 / 业务校验不通过（如余额不足、状态不对） |
| 401 | 未认证（无 JWT 也无 Feishu Open ID） |
| 403 | 权限不足（如 salesman 调审批工具） |
| 404 | 资源不存在 |
| 500 | 服务端异常 |

错误响应格式：
```json
{"detail": "中文错误描述"}
```

---

## 9. Bridge 超时与错误处理

MCP Streamable-HTTP bridge（`/mcp/stream`）通过 loopback HTTP 调用转发到内部 REST 端点。`call_tool` 执行时用 `httpx.AsyncClient(timeout=30.0)` 发起请求，外层 try-except 捕获两种异常：

| 异常 | 返回信息 |
|---|---|
| `httpx.TimeoutException` | `[超时] 调用 {tool_name} 超过 30 秒未响应，请稍后重试` |
| `httpx.HTTPError` | `[网络错误] {异常类型}: {详情}` |

Agent 收到上述友好错误文本后可自行决定是否重试。

---

## 10. 安全设计

| 层面 | 机制 |
|---|---|
| 认证 | JWT / Feishu Open ID 双模式 |
| 数据隔离 | JWT → RLS 14 张表强制过滤；飞书 → brand_scope 过滤 |
| 角色控制 | 每个工具在 handler 层强制 `require_mcp_role(...)` 校验 |
| 审计 | 所有写入操作记 `audit_log` |
| Agent 防御 | erp_app 角色 NOBYPASSRLS，raw SQL 也无法越权 |

---

## 11. Agent 调用示例

### Claude Code 查库存

```bash
curl -X POST http://localhost:8001/mcp/query-inventory \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"brand_id": "青花郎ID", "low_stock_only": true}'
```

### Claude Code 创建订单

```bash
curl -X POST http://localhost:8001/mcp/create-order \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "客户ID",
    "salesman_id": "业务员ID",
    "policy_template_id": "模板ID",
    "settlement_mode": "employee_pay",
    "items": [{"product_id": "商品ID", "quantity": 5, "quantity_unit": "箱"}]
  }'
```

### 飞书 AI 条码追溯

```bash
curl -X POST http://localhost:8001/mcp/query-barcode-tracing \
  -H "X-External-Open-Id: ou_xxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"barcode": "6901234567890"}'
```

---

## 12. 模块结构

```
backend/app/mcp/
├── __init__.py          # 路由汇总注册
├── auth.py              # 双认证（JWT / Feishu Open ID）
├── deps.py              # MCP 专用 DB 依赖（RLS 上下文注入）
├── bridge.py            # Streamable-HTTP bridge（loopback 转发 + 超时处理）
├── catalog.py           # 工具目录（86 个工具，供 bridge 列出 + 路由）
├── tools_query.py       # 24 个查询工具
├── tools_action.py      # 39 个操作工具
├── tools_approval.py    # 17 个审批工具
└── tools.py             # 6 个飞书专用工具（legacy 保留）
```

---

*本文档随 MCP 工具迭代持续更新。*
