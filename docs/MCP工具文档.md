# 新鑫久隆 ERP — MCP 工具文档

> 版本：v2.0 | 日期：2026-04-20

---

## 1. 概述

MCP（Model Context Protocol）是系统暴露给 AI Agent 的工具集，让 AI 能像人一样查询和操作 ERP 系统。

### 1.1 规模

| 指标 | 数量 |
|---|---|
| 总工具数 | 28 |
| 查询工具 | 10 |
| 操作工具 | 6 |
| 审批工具 | 5 |
| 飞书专用 | 7 |

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

## 3. 查询工具（10 个）

所有查询工具只读，不修改数据。

### 3.1 query-orders — 订单列表

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

```json
POST /mcp/query-order-detail
{
  "order_no": "SO-20260419165559-0f88aa"
}
```

返回：订单完整信息 + 所有收款记录（金额、来源、日期）。

### 3.3 query-customers — 客户列表

```json
POST /mcp/query-customers
{
  "brand_id": "可选",
  "keyword": "可选，按名称/联系人搜索",
  "limit": 20
}
```

### 3.4 query-inventory — 库存查询

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

```json
POST /mcp/query-profit-summary
{
  "brand_id": "可选",
  "date_from": "2026-04-01",
  "date_to": "2026-04-30"
}
```

返回 11 个利润科目汇总。建议直接调 `GET /api/dashboard/profit-summary` 获取完整数据。

### 3.6 query-account-balances — 账户余额

```json
POST /mcp/query-account-balances
{
  "brand_id": "可选"
}
```

返回：账户名、类型（现金/F类/融资/回款）、级别（master/project）、品牌、余额。

> 注意：非 admin/boss 用户看不到 master 账户（RLS 过滤）。

### 3.7 query-salary-records — 工资单

```json
POST /mcp/query-salary-records
{
  "period": "2026-04",
  "employee_name": "可选，模糊搜索"
}
```

返回：员工、周期、应发、实发、提成、状态。

> 需要 admin/boss/hr 权限才能看到他人工资。

### 3.8 query-sales-targets — 销售目标

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

```json
POST /mcp/query-manufacturer-subsidies
{
  "brand_id": "可选",
  "period": "可选，如 2026-04",
  "status": "可选，pending/advanced/reimbursed"
}
```

### 3.11 query-attendance-summary — 考勤汇总

```json
POST /mcp/query-attendance-summary
{
  "period": "2026-04"
}
```

返回：每位员工的出勤天数、迟到次数、请假天数、是否全勤。

---

## 4. 操作工具（6 个）

写入数据，受 RLS + 角色约束。

### 4.1 create-order — 创建订单

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

### 4.2 register-payment — 登记收款

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

```json
POST /mcp/create-customer
{
  "code": "C-AI-001",
  "name": "AI创建的客户",
  "brand_id": "品牌 ID",
  "salesman_id": "可选，绑定业务员",
  "contact_name": "联系人",
  "contact_phone": "手机号",
  "settlement_mode": "cash"
}
```

自动建 CustomerBrandSalesman 关联。

### 4.4 create-leave-request — 提交请假

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

创建后状态为 `pending`，需在审批中心处理。

### 4.5 generate-salary — 生成工资单

```json
POST /mcp/generate-salary
{
  "period": "2026-04",
  "overwrite": false
}
```

需要 admin/boss/hr 权限。返回提示调用 API 端点。

### 4.6 generate-subsidy-expected — 生成补贴应收

```json
POST /mcp/generate-subsidy-expected
{
  "period": "2026-04"
}
```

需要 admin/boss/hr 权限。

---

## 5. 审批工具（5 个）

仅 boss/admin 可操作（部分 hr 也可）。

### 5.1 confirm-order-payment — 确认收款

```json
POST /mcp/confirm-order-payment
{
  "order_no": "SO-20260419165559-0f88aa"
}
```

前提：订单 `status=delivered` + `payment_status=fully_paid`。确认后 → `completed`。

### 5.2 approve-leave — 审批请假

```json
POST /mcp/approve-leave
{
  "request_no": "LV-20260420-xxxxxx",
  "approved": true,
  "reject_reason": "可选，驳回时填"
}
```

boss/hr 可操作。

### 5.3 approve-salary — 审批工资

```json
POST /mcp/approve-salary
{
  "salary_record_id": "工资单 ID",
  "approved": true,
  "reject_reason": "可选"
}
```

仅 boss/admin。前提：`status=pending_approval`。

### 5.4 approve-sales-target — 审批销售目标

```json
POST /mcp/approve-sales-target
{
  "target_id": "目标 ID",
  "approved": true,
  "reject_reason": "可选"
}
```

仅 boss/admin。前提：`status=pending_approval`。

### 5.5 approve-fund-transfer — 审批资金调拨

```json
POST /mcp/approve-fund-transfer
{
  "transfer_id": "调拨流水 ID"
}
```

仅 boss/admin。返回提示调用 API 端点完成审批。

---

## 6. 飞书专用工具（7 个，保留旧版）

这些工具服务飞书群聊 AI 网关，用 `X-External-Open-Id` 认证。

### 6.1 allocate-settlement-to-claims — 结算分配预览

```json
POST /mcp/allocate-settlement-to-claims
{
  "settlement_id": "厂家结算单 ID"
}
```

AI 按比例生成分配建议（只预览不写入），需财务确认。

### 6.2 external-approve-and-fill-scheme — 厂家审批+填方案号

```json
POST /mcp/external-approve-and-fill-scheme
X-External-Open-Id: ou_xxxxx
{
  "policy_request_id": "政策申请 ID",
  "scheme_no": "方案号"
}
```

厂家人员审批政策并回填方案号。

### 6.3 query-barcode-tracing — 条码追溯

```json
POST /mcp/query-barcode-tracing
{
  "barcode": "6901234567890"
}
```

返回完整供应链：条码 → 批次 → 入库流水 → 出库订单 → 客户 → 业务员。

### 6.4 submit-policy-approval — 提交政策审批

```json
POST /mcp/submit-policy-approval
{
  "policy_request_id": "政策申请 ID"
}
```

### 6.5 create-policy-usage-record — 创建政策使用记录

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

### 6.6 push-manufacturer-update — 推送厂家通知

```json
POST /mcp/push-manufacturer-update
{
  "recipient_open_id": "ou_xxxxx",
  "title": "政策到账通知",
  "content": "..."
}
```

### 6.7 create-order-from-text — 自然语言建单

```json
POST /mcp/create-order-from-text
{
  "text": "王永 买 5 箱青花郎"
}
```

AI 解析自然语言，匹配客户/商品/政策，创建订单。

---

## 7. 错误码

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

## 8. 安全设计

| 层面 | 机制 |
|---|---|
| 认证 | JWT / Feishu Open ID 双模式 |
| 数据隔离 | JWT → RLS 14 张表强制过滤；飞书 → brand_scope 过滤 |
| 角色控制 | 审批工具强制 `require_role('boss')` |
| 审计 | 所有写入操作记 `audit_log` |
| Agent 防御 | erp_app 角色 NOBYPASSRLS，raw SQL 也无法越权 |

---

## 9. Agent 调用示例

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

## 10. 模块结构

```
backend/app/mcp/
├── __init__.py          # 路由汇总注册
├── auth.py              # 双认证（JWT / Feishu Open ID）
├── deps.py              # MCP 专用 DB 依赖（RLS 上下文注入）
├── tools_query.py       # 10 个查询工具
├── tools_action.py      # 6 个操作工具
├── tools_approval.py    # 5 个审批工具
└── tools.py             # 7 个飞书专用工具（旧版保留）
```

---

*本文档随 MCP 工具迭代持续更新。*
