# 政策模板 / 政策申请 / 政策兑付 / 政策到账

政策是白酒行业核心概念：厂家给经销商的优惠（赠品、回款补贴、政策物料等），经销商先承诺给客户、再向厂家申请兑付。

## 四个核心表

```
PolicyTemplate（政策模板）       厂家定义的政策规则（品牌/箱数区间/赠品/折扣）
  └─ PolicyTemplateBenefit       模板包含的权益条目

PolicyRequest（政策申请）        一个订单对应一个申请，包含"我要兑现这些权益"
  └─ PolicyRequestItem           具体权益条目（状态：pending → fulfilled → settled）

PolicyClaim（政策结算/理赔）     汇总多笔申请一起向厂家报账
  └─ PolicyClaimItem             理赔明细

ClaimSettlementLink              Claim 与厂家 ManufacturerSettlement 到账的关联
```

## PolicyRequestItem 的生命周期

```
pending     刚建，未兑付
  ↓ (POST /fulfill-materials 出库物料)
fulfilled   物料已给到客户，账目上待结算
  ↓ (POST /submit-voucher 提交兑付凭证)
fulfilled   等财务审
  ↓ (POST /confirm-fulfill 财务归档)
settled     归档
  ↓ (POST /confirm-arrival 厂家到账)
arrived     厂家钱到 F 类账户
```

**注意**：`fulfilled` 和 `arrived` 是两件事：
- `fulfilled` = 给客户了（物料出库 or 给他让利）
- `arrived` = 厂家把兑付款打给我们了（钱进 F 类账户）

## Agent 场景 1：查政策模板

用户："青花郎现在有什么政策？"

```
GET /api/policy-templates/templates?brand_id=<青花郎 id>&is_active=true
```

返回列表，Agent 展示每个模板的：名称、箱数区间、指导价、到手价、赠品。

**注意**：销售员看不到 `internal_valuation`（内部估值），API 已自动脱敏。

## Agent 场景 2：匹配政策（建单前）

用户建单时 Agent **自动调**：

```
GET /api/policy-templates/templates/match?brand_id=X&cases=5&unit_price=900
```

后端按品牌 + 箱数区间 + 价格匹配有效模板。可能返回 0 / 1 / 多条。

- **0 条** → Agent 告诉用户"没有匹配的政策，这单无法出库。请先联系老板申请政策模板"
- **1 条** → Agent 自动选用
- **多条** → Agent 推卡片让用户挑

## Agent 场景 3：建政策申请

建单时前端通常自动带出一个 PolicyRequest（见 `orders.md`）。单独建：

```
POST /api/policies/requests
{
  "order_id": "...",
  "policy_template_id": "...",
  "brand_id": "...",
  "request_source": "internal",      // internal / f_class
  "approval_mode": "internal",       // internal / external
  "items": [
    {
      "name": "赠送青花郎1箱",
      "benefit_type": "gift_goods",
      "standard_total": 50.00,
      "quantity": 1,
      "quantity_unit": "箱",
      "advance_payer_type": "employee",        // employee / customer / company_account
      "advance_payer_id": "<业务员 id>"        // 垫付人 id，类型对应
    }
  ]
}
```

**advance_payer**：谁垫付政策成本。业务员自己掏钱垫给客户的礼品 → `employee + employee_id`；公司账户支付 → `company_account + account_id`。

## Agent 场景 4：兑付物料（出库）

业务员/老板把政策物料发给客户。

```
POST /api/policies/requests/{request_id}/fulfill-materials
{
  "items": [
    {
      "request_item_id": "<PolicyRequestItem id>",
      "product_id": "<赠品 product id>",
      "quantity": 1,
      "quantity_unit": "箱",
      "warehouse_id": "<出库仓库>"
    }
  ]
}
```

后端：
- 扣库存（StockFlow 类型=`policy_out`）
- PolicyRequestItem.fulfilled_qty += bottles
- fulfilled_qty ≥ quantity 时 status → `fulfilled`

## Agent 场景 5：提交兑付凭证

物料出完，业务员提交照片凭证。Agent 引导用户发图 → 上传 → 调：

```
POST /api/policies/requests/{id}/submit-voucher
{
  "item_id": "...",
  "voucher_urls": ["..."],
  "actual_cost": 45.00      // 实际花费（可能低于 standard_total，差额是政策盈余）
}
```

后端算 `profit_loss = standard_total - total_value - actual_cost`。

## Agent 场景 6：财务确认归档（幂等）

```
POST /api/policies/requests/{request_id}/confirm-fulfill
{ "item_id": "..." }
```

**关键改动（P2c bug B 修复）**：
- 已 settled 的直接返回 `{"detail": "该项已归档，无需重复确认"}`（幂等）
- 不累加，直接赋值：`settled_amount = arrival_amount or total_value`

Agent 如果收到 200 + "已归档"的返回，告诉用户"该项早已归档"。

## Agent 场景 7：政策到账对账（F 类账户收款）

厂家打款到公司 F 类账户，财务登记到账。

### 手动登记

```
POST /api/policies/requests/confirm-arrival
{
  "items": [
    {
      "item_id": "<PolicyRequestItem id>",
      "arrived_amount": 45.00,
      "billcode": "银行单据号"
    }
  ],
  "salary_items": [...]    // 工资补贴到账（可选，见 payroll.md）
}
```

后端：
- PolicyRequestItem.fulfill_status = arrived（**幂等**：已 arrived 的跳过）
- 如果 request_source=f_class → F 类账户 += arrived_amount + 写 fund_flow

**Agent 关键提醒**：用户对同一条点"确认"多次是**安全的**（后端幂等跳过），不会重复加钱。

### Excel 对账（大批量）

厂家发来到账单（Excel），用户上传：

```
POST /api/policies/requests/match-arrival?brand_id=X
Body: multipart/form-data，file=Excel
```

后端两轮匹配（按 scheme_no + 金额），返回未匹配的行让用户手工处理。

Agent 引导用户先 `POST /api/uploads` 传 Excel 获取文件路径，然后 POST 对账接口……其实这个端点直接接 multipart，Agent 把文件直接转发即可（见 feishu-interaction.md 图片转发，Excel 同理）。

## Agent 场景 8：policy_claim（向厂家集中报账）

多个 PolicyRequestItem 汇总成一个 Claim 向厂家报账。

```
POST /api/policies/claims
{
  "brand_id": "...",
  "manufacturer_id": "...",      // 厂家 supplier id
  "claim_batch_period": "2026-04",
  "items": [
    { "request_item_id": "...", "declared_amount": 45.00 },
    ...
  ]
}
```

这个一般**财务/老板**在前端操作，Agent 较少主动做。

## 垫付返还（关键业务）

如果 PolicyRequestItem 的 `advance_payer_type=employee`，政策兑现后公司要**返还业务员垫付的钱**。

后端自动触发 `_trigger_advance_refund_if_fulfilled`（条件：`fulfill_status in ('fulfilled','settled')` + 有 advance_payer），生成 `FinancePaymentRequest`（垫付返还申请）到审批中心。

Agent 告诉业务员："垫付返还申请已生成，财务批准后打款给你。" 返还的钱从 `payment_to_mfr` 账户 / 品牌现金账户扣。

## 常见错误

| detail | 解释 |
|---|---|
| "政策明细项不存在" | item_id 错或不在 RLS 可见范围 |
| "状态为 'pending'，需要先提交兑付凭证" | 要先 submit-voucher 才能 confirm-fulfill |
| "该项已归档，无需重复确认" | 幂等返回，正常 |
| "品牌未配置 F类账户" | 财务要先到账户管理建 F 类项目账户 |
| "未配置公司总资金池" | 建 master 现金账户 |

## 时间字段

- `created_at` / `updated_at` / `arrived_at` / `confirmed_at` / `fulfilled_at`：都是 UTC，展示按东八区格式化

## 特殊模板：brand_id=NULL 通用模板

`policy_templates.brand_id IS NULL` 表示**全品牌通用模板**（RLS 对所有员工可见）。Agent 查询时要注意把这种模板也纳入匹配结果。
