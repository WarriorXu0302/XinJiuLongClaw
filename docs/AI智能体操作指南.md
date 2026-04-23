# 新鑫久隆 ERP — AI 智能体操作指南

> 版本：v3.0 | 更新：2026-04-23
> 本文档面向 AI Agent（飞书机器人 / MCP 客户端），是系统操作的权威参考。
> 你必须完全理解这里的业务逻辑，才能正确使用 86 个 MCP 工具。

---

## 1. 公司业务

新鑫久隆是一家**多品牌白酒经销商**。公司代理多个白酒品牌（青花郎、五粮液、汾酒、珍十五），从厂家进货，卖给两类客户：
- **渠道客户（channel）**：烟酒店、超市、餐饮店 — 长期合作，按箱数匹配政策
- **团购客户（group_purchase）**：个人/企业团购会员 — 按积分/会员等级匹配政策

**核心盈利模式 — 政策补贴**：

进货价（指导价）885 元/瓶，卖给客户 650 元/瓶。表面每瓶亏 235 元，但厂家通过**政策**补回来（比如每箱补贴、买赠、品鉴活动费等），补贴价值通常 > 差额，差值就是公司利润。

---

## 2. 品牌 = 独立事业部

**每个品牌完全独立核算**，拥有：

| 资源 | 说明 |
|------|------|
| 现金账户 | 品牌日常支出：工资、采购、报销 |
| F类账户 | 厂家政策补贴/报销到账专用 |
| 融资账户 | 银行贷款余额（负债） |
| 应付厂家账户 | 统计用虚拟账户（不可调拨） |
| 主仓库 | 主要出货仓 |
| 备用仓库 | 稽查回收/临时存放 |
| 品鉴酒仓 | 品鉴活动用酒 |
| 员工岗位 | 业务员/经理绑定到品牌（EmployeeBrandPosition） |
| 薪酬方案 | 品牌×岗位的底薪/提成率/全勤奖（BrandSalaryScheme） |

**公司总资金池（master 现金账户）**：全公司只有一个，所有客户回款先进这里。

---

## 3. 账户体系与资金流向

### 3.1 账户类型

| 类型 | 层级 | 说明 | 举例 |
|------|------|------|------|
| cash | master | 公司总资金池 | 唯一，所有客户回款入口 |
| cash | project | 品牌现金 | 青花郎-现金、五粮液-现金 |
| f_class | project | F类资金 | 青花郎-F类（厂家政策到账） |
| financing | project | 融资余额 | 青花郎-融资（银行贷款） |
| payment_to_mfr | project | 应付厂家 | 统计虚拟账户，不可调拨 |

### 3.2 资金流向图

```
┌─────────────────────────────────────────────────────┐
│                    资金入口                           │
│                                                      │
│  客户付款（任何品牌）──→ master 现金账户（总资金池）    │
│  厂家政策到账 ────────→ 品牌 F类账户                  │
│  厂家工资补贴到账 ───→ 品牌现金账户                   │
│  银行融资放款 ────────→ 品牌融资账户（负债增加）       │
│                                                      │
├─────────────────────────────────────────────────────┤
│                    资金出口                           │
│                                                      │
│  boss 审批调拨：master 现金 ──→ 品牌现金              │
│  发工资/付采购/报销：品牌现金 ──→ 外部                 │
│  融资还款：品牌现金 ──→ 银行（融资余额减少）           │
│  融资还款(F类部分)：品牌F类 ──→ 银行                  │
│                                                      │
├─────────────────────────────────────────────────────┤
│                    禁止操作                           │
│                                                      │
│  品牌A现金 ──✕──→ 品牌B现金（品牌间不能互转）         │
│  F类账户 ──✕──→ 接收调拨（F类只能收厂家打款）         │
│  应付厂家账户 ──✕──→ 任何转账（统计用，不可操作）      │
└─────────────────────────────────────────────────────┘
```

### 3.3 调拨流程

品牌现金不够时：
1. `create-fund-transfer` — 创建调拨申请（from: master → to: 品牌现金）
2. `approve-fund-transfer` — boss 审批（**只有 boss**，finance 不能批）
3. 系统自动：master 余额减少 → 品牌现金增加 → FundFlow 记账

### 3.4 资金流水（FundFlow）

每一笔余额变动都会产生一条不可修改的 FundFlow 记录：
- `flow_type`：credit（入账）/ debit（出账）/ transfer_pending / transfer_approved 等
- `related_type` + `related_id`：关联到具体的 Receipt / Payment / Order / FinancingOrder
- **用途**：审计追溯，任何一笔钱都能查到来源和去向

---

## 4. 订单定价与三种结算模式

### 4.1 三级价格体系

每个订单涉及三个价格（全部来自政策模板 PolicyTemplate）：

| 价格 | 字段 | 说明 | 举例 |
|------|------|------|------|
| 指导价 | `required_unit_price` | 厂家定的标准价，内部核算基准 | 885 元/瓶 |
| 客户到手价 | `customer_unit_price` | 客户实际支付的单价 | 650 元/瓶 |
| 政策总价值 | `total_policy_value` | 模板包含的全部补贴价值 | 8,500 元 |

**建单时系统自动计算**（你不要自己算）：
```
total_amount     = 指导价 × 总瓶数           = 885 × 30 = 26,550
deal_amount      = 到手价 × 总瓶数           = 650 × 30 = 19,500
policy_gap       = total_amount - deal_amount = 26,550 - 19,500 = 7,050
policy_surplus   = 政策总价值 - policy_gap    = 8,500 - 7,050 = 1,450（公司利润）
```

### 4.2 三种结算模式详解

**决定了 `customer_paid_amount`（公司期望收到的钱）**：

#### customer_pay（客户全额付）
- 客户按指导价 885 付全款
- `customer_paid_amount = total_amount = 26,550`
- 政策应收 = 0（没有差额需要补）
- 提成基数 = 26,550

#### employee_pay（业务员垫付）
- 客户付到手价 19,500 + 业务员补差额 7,050 = 两笔凑齐 26,550
- `customer_paid_amount = total_amount = 26,550`（公司总共要收到这么多）
- 政策应收 = 7,050（等厂家兑付后返还给业务员）
- 提成基数 = 26,550
- 系统自动记录 `advance_payer_id`（垫付人 = 业务员）

#### company_pay（公司垫付）
- 客户只付到手价 19,500
- `customer_paid_amount = deal_amount = 19,500`（公司只向客户收这么多）
- 差额 7,050 由公司承担，记为政策应收等厂家补
- 政策应收 = 7,050
- 提成基数 = 19,500（按公司实际收到的算）

### 4.3 收款与 payment_status

| 状态 | 条件 | 说明 |
|------|------|------|
| unpaid | 没有任何 Receipt | 未收款 |
| partially_paid | Receipt 总额 > 0 但 < customer_paid_amount | 部分收款 |
| fully_paid | Receipt 总额 >= customer_paid_amount | 全额到齐 |

**fully_paid 触发两件事**：
1. 自动生成 Commission（提成）记录
2. 解锁"财务确认收款"操作 → 订单可完成

### 4.4 信用客户的应收账款

如果客户 `settlement_mode = credit`（赊销）：
- 订单送达时自动生成 Receivable（应收账款）
- 金额 = `customer_paid_amount`
- 到期日 = 送达日 + `customer.credit_days`
- 收到 Receipt 后 `paid_amount` 逐步增加

---

## 5. 订单全生命周期

### 5.1 状态流转

```
pending ──→ policy_pending_internal ──→ approved ──→ shipped ──→ delivered ──→ completed
  │              │                         │                        │
  │              ├──→ policy_pending_external ──→ approved           │
  │              │                                                   │
  └──────────────┴──→ policy_rejected ──→ pending（重新提交）        │
                                                                     │
                                      上传凭证(每笔建Receipt) ──→ fully_paid
                                                                     │
                                                        财务确认 ──→ completed
```

### 5.2 每步操作工具

| 阶段 | 动作 | MCP 工具 | 角色 | 说明 |
|------|------|---------|------|------|
| 建单 | 创建 | `create-order` | boss/salesman/sales_manager | 必须选 policy_template_id |
| 建单 | 编辑 | `update-order` | 同上 | 仅 pending 状态可改 |
| 审批 | 提交政策审批 | `submit-order-policy` | 同上 | pending → policy_pending_internal |
| 审批 | 一步审批 | `approve-order` | boss | pending → approved（自动走提交+审批） |
| 审批 | 驳回 | `approve-order`(action=reject) | boss | → policy_rejected |
| 审批 | 重新提交 | `resubmit-order` | boss/salesman/sales_manager | rejected → pending |
| 出库 | 发货 | `update-order-status`(action=ship) | boss/warehouse | approved → shipped |
| 物流 | 确认送达 | `update-order-status`(action=confirm-delivery) | boss/warehouse/salesman | shipped → delivered |
| 收款 | 登记收款 | `register-payment` | boss/finance/salesman | 每笔建 Receipt → master |
| 收款 | 确认收款 | `confirm-order-payment` | boss/finance | delivered + fully_paid → completed |
| 完成 | 标记完成 | `complete-order` | boss/finance | delivered → completed（无需 fully_paid） |
| 取消 | 取消订单 | `update-order-status`(action=cancel) | boss/warehouse/salesman | |

### 5.3 建单必要步骤

```
1. query-brands                → 拿到 brand_id
2. query-policy-templates      → 选模板，拿到 policy_template_id
3. query-customers             → 拿到 customer_id
4. query-products              → 拿到 product_id
5. query-employees             → 拿到 salesman_id（如果是 boss 代建）
6. create-order                → 传入以上 ID + settlement_mode + items
```

**items 格式**：`[{"product_id": "xxx", "quantity": 5, "quantity_unit": "箱"}]`

单位默认"箱"，系统自动 × bottles_per_case 换算成瓶数。指导价从模板强制读取，你传的 unit_price 会被忽略。

---

## 6. 政策全流程

### 6.1 政策模板（PolicyTemplate）

政策模板定义了一套补贴方案，建单时必须选择：

| 字段 | 含义 | 举例 |
|------|------|------|
| code | 编码 | QHL-2026-A1 |
| name | 名称 | 青花郎53度渠道政策 |
| template_type | 类型 | channel（按箱数匹配）/ group_purchase（按积分匹配） |
| brand_id | 品牌 | 青花郎 |
| required_unit_price | 指导价 | 885 |
| customer_unit_price | 客户到手价 | 650 |
| min_cases / max_cases | 最低/最高箱数 | 10 / 100 |
| total_policy_value | 政策总价值 | 8,500 |
| valid_from / valid_to | 有效期 | 2026-01-01 ~ 2026-12-31 |
| benefit_rules | 福利明细(JSON) | 回款返利、品鉴活动、实物赠品等 |

### 6.2 政策申请（PolicyRequest）

订单审批通过后，可提交政策申请：

```
draft → pending_internal → pending_external → approved → 兑付中 → fulfilled
```

**申请来源**（request_source）：
- ORDER — 订单关联
- F_CLASS — F类费用报销
- HOSPITALITY — 宴请/品鉴
- MARKET_ACTIVITY — 市场活动
- MANUAL — 手动

### 6.3 政策兑付项（PolicyRequestItem）

每个政策申请包含多个兑付项，每项独立跟踪：

| 字段 | 含义 |
|------|------|
| benefit_type | discount(折扣)/tasting(品鉴)/material(实物)等 |
| fulfill_mode | claim(需理赔)/direct(直接兑付)/material(实物出库) |
| advance_payer_type | employee/company/customer（谁先垫付） |
| standard_unit_value | 实际价值（成本价） |
| unit_value | 折算价值（客户承诺额） |
| fulfilled_qty | 已兑付数量 |
| fulfill_status | pending → applied → arrived → fulfilled → settled |
| arrival_amount | 厂家到账金额 |
| settled_amount | 最终结算金额 |

**兑付完成后**：如果有垫付人（advance_payer），系统自动生成付款申请（FinancePaymentRequest）请求退还垫付款。

### 6.4 政策理赔（PolicyClaim）

当需要向厂家申请报销时：

```
draft → submitted → (partially_settled) → settled
```

理赔打包多个 PolicyClaimItem，每项关联到 PolicyRequestItem 或 PolicyUsageRecord。厂家打款后通过 ManufacturerSettlement 分配到各理赔单。

### 6.5 政策操作工具

| 工具 | 用途 | 角色 |
|------|------|------|
| `create-policy-template` | 建模板 | boss/finance |
| `query-policy-templates` | 查模板 | 所有人 |
| `create-policy-request` | 建申请 | boss/finance/salesman/sales_manager |
| `submit-policy-approval` | 提交审批 | 同上 |
| `fulfill-policy-materials` | 兑付物料（更新 fulfilled_qty） | boss/finance |
| `confirm-policy-arrival` | 确认到账 | boss/finance |
| `confirm-policy-fulfill` | 确认兑付完成 | boss/finance |
| `create-policy-claim` | 建理赔单 | boss/finance |
| `approve-policy-claim` | 审批理赔 | boss/finance |
| `create-policy-usage-record` | 手工建使用记录（品鉴等） | boss/finance/salesman |
| `allocate-settlement-to-claims` | 预览厂家到账分配 | boss/finance |
| `confirm-settlement-allocation` | 确认分配 | boss/finance |

---

## 7. 费用与报销

### 7.1 两种报销模型

| 模型 | 表 | 适用场景 | 典型流程 |
|------|---|---------|---------|
| Expense | finance.Expense | 日常费用审批 | 建→审批→付款 |
| ExpenseClaim | expense_claim.ExpenseClaim | F类费用理赔 | 建→审批→申请→到账→兑付→结算 |

### 7.2 Expense（日常费用）

```
pending → approved → paid / rejected
```

- `category`：费用类型（办公、差旅、招待等）
- `brand_id`：从哪个品牌的现金账户出
- `amount`：金额
- `approve-expense`(action=approve) → 审批通过
- `approve-expense`(action=pay) → 标记已付款，从品牌现金扣减

### 7.3 ExpenseClaim（F类费用理赔）

**典型场景：员工先垫付请客户吃饭，公司审批后从品牌现金补给员工，然后向厂家申请报销。**

```
pending → approved → applied → arrived → fulfilled → settled
```

**完整资金链路**：
```
1. 员工垫付 1,500 → 餐厅（已发生）
2. 创建 ExpenseClaim(amount=1500, brand_id=青花郎)
3. boss/finance 审批通过(approved)
4. 公司从品牌现金付给员工 1,500 → status=applied
5. 公司向厂家提交报销申请
6. 厂家打款 1,500 到品牌F类账户 → status=arrived
7. 核实到账 → status=fulfilled
8. 完成 → status=settled
```

**关键理解**：`approve-expense`(action=pay) 是公司付给员工的动作，不是厂家付钱。

### 7.4 厂家结算（ManufacturerSettlement）

厂家一次性打来一笔钱（比如 50,000），需要分配给多个理赔单：

1. `create-manufacturer-settlement` — 记录厂家打款
2. `allocate-settlement-to-claims` — 预览分配方案
3. `confirm-settlement-allocation` — 确认执行分配

---

## 8. 稽查案件

### 8.1 稽查是什么

稽查 = 市场上发现窜货、价格违规等问题后的处理。分**窜出**（我们的货被别人卖了）和**窜入**（别人的货流入我们市场）两大类。

### 8.2 五种案件类型与盈亏公式

| 代码 | 类型 | 方向 | 场景 | 盈亏公式 |
|------|------|------|------|---------|
| outflow_malicious | A1恶意窜出 | outflow | 经销商恶意低价窜货，公司花高价回收 | **-(purchase_price - deal_unit_price) × 瓶数 - penalty** |
| outflow_nonmalicious | A2非恶意窜出 | outflow | 非恶意串货，回收后按指导价入库 | **(original_sale_price - purchase_price) × 瓶数 - penalty** |
| outflow_transfer | A3被转码 | outflow | 货物被转码，无法回收 | **-penalty** |
| inflow_resell | B1窜入回售 | inflow | 买入别人窜来的货，高价回售 | **(resell_price - purchase_price) × 瓶数 + reward** |
| inflow_transfer | B2窜入入库 | inflow | 买入窜货按指导价入自己仓 | **(original_sale_price - purchase_price) × 瓶数 + reward** |

### 8.3 字段含义

| 字段 | 含义 | A类用 | B类用 |
|------|------|-------|-------|
| deal_unit_price | 到手价（原来卖给客户的价） | A1 | - |
| purchase_price | 回收价 / 买入价 | A1/A2 | B1/B2 |
| original_sale_price | 指导价 | A2 | B2 |
| resell_price | 回售价 | - | B1 |
| penalty_amount | 罚款 | A1/A2/A3 | - |
| reward_amount | 奖励 | - | B1/B2 |

### 8.4 举例

**A1 恶意窜出**：我们 650 卖给客户的货被人低价倒卖，花 800 元/瓶回收了 50 瓶，罚款 5,000：
```
profit_loss = -(800 - 650) × 50 - 5000 = -7500 - 5000 = -12,500（亏损）
```

**B1 窜入回售**：买入别人窜来的货 500 元/瓶 × 20 瓶，750 元/瓶回售，奖励 1,000：
```
profit_loss = (750 - 500) × 20 + 1000 = 5000 + 1000 = 6,000（盈利）
```

### 8.5 箱↔瓶换算

如果 `quantity_unit = "箱"`，系统自动查 `product.bottles_per_case` 换算。比如 quantity=5, 每箱6瓶 → 实际30瓶参与计算。

### 8.6 稽查工具

| 工具 | 用途 | 角色 |
|------|------|------|
| `create-inspection-case` | 建稽查案件（自动算盈亏） | boss/finance |
| `approve-inspection` | 执行案件（pending→confirmed） | boss/finance |
| `create-market-cleanup-case` | 建市场清理案件 | boss/finance |
| `query-inspection-cases` | 查询列表 | boss/finance |
| `query-barcode-tracing` | 条码追溯 | boss/warehouse/salesman/sales_manager/finance |

---

## 9. 采购流程

```
建采购单(pending) → 审批(approved) → 供应商发货(shipped) → 收货(received)
```

### 9.1 建采购单

```python
create-purchase-order(
    supplier_id="xxx",      # query-suppliers 获取
    brand_id="xxx",         # query-brands 获取
    warehouse_id="xxx",     # query-warehouses 获取
    items=[
        {"product_id": "xxx", "quantity": 100, "unit_price": 500, "quantity_unit": "箱"}
    ]
)
```

系统自动求和 `total_amount`，状态初始为 pending。

### 9.2 采购工具

| 工具 | 角色 | 说明 |
|------|------|------|
| `create-purchase-order` | boss/purchase/warehouse | 建单 |
| `approve-purchase-order` | boss/finance | 审批（approve/reject，支持 po_no 查找） |
| `receive-purchase-order` | boss/warehouse/purchase | 确认收货（支持 po_no 查找） |
| `query-purchase-orders` | boss/purchase/warehouse/finance | 查询列表 |
| `query-suppliers` | boss/purchase/warehouse | 查供应商 |
| `query-warehouses` | 所有人 | 查仓库 |

---

## 10. 薪资与提成

### 10.1 薪酬方案（BrandSalaryScheme）

每个品牌×岗位有一套薪酬参数：

| 字段 | 含义 | 举例 |
|------|------|------|
| fixed_salary | 底薪 | 3,000 |
| variable_salary_max | 绩效奖金上限 | 1,500 |
| attendance_bonus_full | 全勤奖 | 200 |
| commission_rate | 提成比例 | 0.01（1%） |
| manager_share_rate | 经理分成比例 | 0.003（0.3%） |

### 10.2 工资组成

```
total_pay = 底薪 + 绩效奖金 + 提成 + 经理分成 + 全勤奖 + 其他
            - 迟到扣款 - 缺勤扣款 - 罚款 - 社保
actual_pay = total_pay - 社保个人部分
```

### 10.3 提成计算规则

**触发时机**：订单收款达到 `fully_paid` 时自动生成 Commission 记录。

```
提成基数 = order.customer_paid_amount（公司实际收到的钱）
提成金额 = 提成基数 × commission_rate
```

| 结算模式 | 提成基数 | 举例（30瓶） |
|---------|---------|-------------|
| customer_pay | 26,550（全价） | 26,550 × 1% = 265.50 |
| employee_pay | 26,550（两笔凑齐） | 26,550 × 1% = 265.50 |
| company_pay | 19,500（到手价） | 19,500 × 1% = 195.00 |

**经理分成**：如果业务员有上级经理，经理额外获得 `下属提成 × manager_share_rate`。

**提成率优先级**：
1. EmployeeBrandPosition.commission_rate（个人设定）
2. BrandSalaryScheme.commission_rate（品牌×岗位默认）

### 10.4 绩效考核（KPI）

AssessmentItem 记录每月考核项：
- `kpi_revenue`：回款金额（权重 ¥1,000，目标取销售目标表）
- `kpi_customers`：活跃客户数（权重 ¥500，默认目标 30 家）

`variable_salary = sum(earned_amount)`，上限 `variable_salary_max`

### 10.5 全勤奖梯度

按迟到天数扣减（不是0/1，而是梯度）：

| 迟到天数 | 全勤奖比例 | 200元全勤奖实发 |
|---------|----------|---------------|
| 0 | 100% | 200 |
| 1 | 80% | 160 |
| 2 | 60% | 120 |
| 3 | 40% | 80 |
| 4 | 20% | 40 |
| ≥5 | 0% | 0 |

### 10.6 厂家工资补贴

**不进工资条**。独立跟踪：

```
generate-subsidy-expected → 生成应收记录(pending)
公司先发工资(advanced) → 厂家打款到品牌现金(reimbursed)
```

补贴金额来自 `EmployeeBrandPosition.manufacturer_subsidy`。

### 10.7 薪资工具

| 工具 | 角色 | 说明 |
|------|------|------|
| `create-salary-scheme` | boss/hr | 建/改薪酬方案（Upsert，同品牌+岗位覆盖） |
| `generate-salary` | boss/finance | 一键生成当月全员工资 |
| `batch-submit-salary` | boss/hr | 批量提交审批（draft→pending_approval） |
| `approve-salary` | boss/finance | 审批（approved/rejected） |
| `pay-salary` | boss/finance | 发放（支持单条 or 按月批量） |
| `generate-subsidy-expected` | boss/finance | 生成当月补贴应收 |
| `confirm-subsidy-arrival` | boss/finance | 确认补贴到账 |
| `settle-commission` | boss/hr/finance | 提成结算 |
| `query-salary-records` | boss/finance | 查工资列表 |
| `query-commissions` | boss/hr/finance | 查提成列表 |

---

## 11. 融资管理

### 11.1 融资是什么

公司通过银行贷款给品牌注入资金。贷款余额记在品牌融资账户（负债）。

### 11.2 融资流程

```
建融资单 → 融资账户余额增加（代表负债）
    → 还款申请(pending) → boss 审批
    → 品牌现金扣减 + 融资余额减少 + 利息计算
```

### 11.3 利息计算

```
interest = principal × (annual_rate / 100) × days / 365
```

还款可以拆分：一部分从品牌现金还，一部分从品牌F类还。

### 11.4 融资工具

| 工具 | 角色 | 说明 |
|------|------|------|
| `create-financing-order` | boss/finance | 建融资单（自动查品牌融资账户） |
| `submit-financing-repayment` | boss/finance | 提交还款申请（自动算利息） |
| `approve-financing-repayment` | boss/finance | 审批还款（approve/reject） |
| `query-financing-orders` | boss/finance | 查询列表 |

---

## 12. 客户管理

### 12.1 客户类型

| 类型 | 代码 | 说明 | 政策匹配方式 |
|------|------|------|-------------|
| 渠道客户 | channel | 烟酒店、超市 | 按箱数（min_cases/max_cases） |
| 团购客户 | group_purchase | 个人/企业会员 | 按积分/会员等级 |

### 12.2 结算方式

| 方式 | 代码 | 说明 |
|------|------|------|
| 现结 | cash | 订单当场结清 |
| 赊销 | credit | 允许延期付款，送达时自动生成应收 |

赊销客户有 `credit_days`（账期天数）和 `credit_limit`（信用额度）。

### 12.3 品牌-业务员绑定

一个客户可以绑定多个品牌，每个品牌对应一个业务员（CustomerBrandSalesman）。

### 12.4 客户工具

| 工具 | 角色 |
|------|------|
| `create-customer` | boss/salesman/sales_manager |
| `update-customer` | 同上 |
| `bind-customer-brand-salesman` | 同上 |
| `query-customers` | 所有人 |

---

## 13. 员工与考勤

### 13.1 员工品牌岗位（EmployeeBrandPosition）

一个员工可以绑多个品牌，每个品牌指定岗位和提成率：
- `position_code`：salesman / sales_manager / warehouse 等
- `commission_rate`：个人提成率（覆盖方案默认值）
- `manufacturer_subsidy`：每月厂家补贴金额
- `is_primary`：是否主品牌（工资从主品牌方案取底薪）

### 13.2 考勤

- **打卡**：CheckinRecord（work_in/work_out，带GPS和自拍）
- **迟到判定**：checkin_time > work_start_time + late_tolerance_minutes
- **拜访**：CustomerVisit（enter/leave GPS，duration_minutes，is_valid）
- **请假**：LeaveRequest（personal/sick/annual/overtime_off）

### 13.3 员工工具

| 工具 | 角色 |
|------|------|
| `create-employee` | boss/hr |
| `update-employee` | boss/hr |
| `bind-employee-brand` | boss/hr |
| `create-leave-request` | 所有人 |
| `approve-leave` | boss/hr |
| `create-user` | boss |
| `query-employees` | boss/hr/finance/sales_manager |
| `query-attendance-summary` | boss/hr |
| `query-leave-requests` | boss/hr/finance |

---

## 14. 利润台账（11 个科目）

Dashboard 利润汇总按品牌计算，11 个科目：

| # | 科目 | 类型 | 计算方式 |
|---|------|------|---------|
| 1 | 订单销售利润 | 收入 | Σ(售价-成本)×瓶数，售价=company_pay用到手价/其他用指导价 |
| 2 | 政策兑付盈利 | 收入 | Σ(政策项.profit_loss > 0) |
| 3 | 稽查清理盈利 | 收入 | Σ(稽查案件.profit_loss > 0)，只算 executed/closed |
| 4 | F类到账差额 | 收入 | Σ(到账金额 - 实际成本)，来源=f_class |
| 5 | 回款返利 | 收入 | 手动录入（保留项） |
| 6 | 报销费用 | 支出 | Σ(Expense.amount)，status=paid |
| 7 | 政策兑付亏损 | 支出 | Σ\|政策项.profit_loss < 0\| |
| 8 | 稽查外流亏损 | 支出 | Σ\|稽查案件.profit_loss < 0\|，只算 executed/closed |
| 9 | 融资利息 | 支出 | Σ(还款记录.interest_amount)，status=approved |
| 10 | 分货差价 | 支出 | 手动录入（保留项） |
| 11 | 人力成本净额 | 支出 | (工资实发 + 公司社保) - 厂家补贴已报销 |

**总利润 = 收入项合计 - 支出项合计**

---

## 15. 角色权限矩阵

### 15.1 9种角色

| 角色 | 定位 | 关键权限 |
|------|------|---------|
| **admin** | 超级管理员 | 一切操作 + 审计日志 |
| **boss** | 老板 | 一切操作，是所有审批的最终权限 |
| **finance** | 财务 | 收付款、费用审批、工资审批/发放、政策兑付、稽查、采购审批 |
| **hr** | 人事 | 员工管理、薪酬方案、绩效KPI、请假审批 |
| **salesman** | 业务员 | 自己的订单/客户/收款/请假。**只能看自己数据** |
| **sales_manager** | 业务经理 | 所属品牌全部业务、销售目标、查库存 |
| **warehouse** | 仓库 | 库存出入库、采购建单/收货、商品管理 |
| **purchase** | 采购 | 采购单、收货、供应商 |
| **manufacturer_staff** | 厂家对接 | 受限外部视图 |

### 15.2 salesman 特殊限制

- 建单时 `salesman_id` 强制 = 本人（传什么都会被覆盖）
- 建客户时 `salesman_id` 强制 = 本人
- 查询数据只返回自己关联的记录（RLS 行级安全）

### 15.3 审批权限速查

| 审批事项 | 谁能批 |
|---------|--------|
| 订单政策审批 | boss |
| 资金调拨 | boss（finance 不能批调拨） |
| 采购单 | boss / finance |
| 费用报销 | boss / finance |
| 工资 | boss / finance |
| 请假 | boss / hr（finance 不能批请假） |
| 销售目标 | boss / sales_manager |
| 融资还款 | boss / finance |
| 稽查执行 | boss / finance |

---

## 16. 常见业务场景

### 场景1：完整的订单到回款流程

```
# 1. 准备数据
品牌列表 = query-brands()
客户 = query-customers(keyword="张三烟酒")
模板 = query-policy-templates(brand_id=品牌ID)
商品 = query-products(brand_id=品牌ID)
业务员 = query-employees(keyword="李四")

# 2. 建单
订单 = create-order(
    customer_id=客户ID,
    salesman_id=业务员ID,
    policy_template_id=模板ID,
    settlement_mode="customer_pay",
    items=[{"product_id": 商品ID, "quantity": 5, "quantity_unit": "箱"}]
)
# 系统自动算: total_amount=26550, deal_amount=19500, customer_paid_amount=26550

# 3. 审批
approve-order(order_no=订单.order_no)  # boss 一步到位

# 4. 出库发货
update-order-status(order_no=订单.order_no, action="ship")

# 5. 确认送达
update-order-status(order_no=订单.order_no, action="confirm-delivery")

# 6. 客户付款（可能分多笔）
register-payment(order_no=订单.order_no, amount=15000)  # 第一笔
register-payment(order_no=订单.order_no, amount=11550)  # 第二笔 → fully_paid

# 7. 财务确认
confirm-order-payment(order_no=订单.order_no)  # → completed
```

### 场景2：F类费用报销全流程

```
# 1. 员工垫付请客户吃饭 1500 元，创建报销单
报销 = create-expense(
    brand_id=青花郎ID,
    category="f_class_hospitality",
    amount=1500,
    description="招待高总晚宴"
)

# 2. boss 审批通过
approve-expense(expense_id=报销.claim_no, action="approve")

# 3. 公司从品牌现金付给员工
approve-expense(expense_id=报销.claim_no, action="pay")

# 4. 向厂家提交报销（线下操作）
# 5. 厂家打款到品牌F类账户 → 品牌F类余额增加（线下确认后录入系统）
```

### 场景3：月度薪资发放

```
# 1. 生成工资单
generate-salary(period="2026-04")

# 2. 检查工资明细
records = query-salary-records(period="2026-04")

# 3. 批量提交审批
batch-submit-salary(period="2026-04")

# 4. 逐条审批（或让 boss 批量处理）
for r in records:
    approve-salary(salary_record_id=r.id, approved=true)

# 5. 批量发放
pay-salary(batch_mode=true, period="2026-04")

# 6. 生成厂家补贴应收
generate-subsidy-expected(period="2026-04")

# 7. 厂家打补贴后确认到账
confirm-subsidy-arrival(subsidy_ids=[id1, id2, ...])
```

### 场景4：采购补货

```
# 1. 查供应商和商品
suppliers = query-suppliers()
products = query-products(brand_id=青花郎ID)
warehouses = query-warehouses(brand_id=青花郎ID)

# 2. 建采购单
po = create-purchase-order(
    supplier_id=供应商ID,
    brand_id=青花郎ID,
    warehouse_id=主仓ID,
    items=[
        {"product_id": 商品ID, "quantity": 100, "unit_price": 500, "quantity_unit": "箱"}
    ]
)

# 3. 审批
approve-purchase-order(po_id=po.po_no, action="approve")

# 4. 到货收货
receive-purchase-order(po_id=po.po_no)
```

### 场景5：处理窜货稽查

```
# A1 恶意窜出案件
case = create-inspection-case(
    brand_id=青花郎ID,
    case_type="outflow_malicious",
    direction="outflow",
    product_id=商品ID,
    quantity=50,
    quantity_unit="瓶",
    purchase_price=800,       # 花 800 元/瓶回收
    deal_unit_price=650,      # 原来卖给客户 650
    penalty_amount=5000       # 罚款 5000
)
# 系统自动算: profit_loss = -(800-650)×50 - 5000 = -12500

# 执行
approve-inspection(case_id=case.case_no, action="execute")
```

### 场景6：资金调拨

```
# 品牌现金不够发工资，从 master 调拨
transfer = create-fund-transfer(
    to_brand_name="青花郎",
    amount=50000,
    notes="4月工资调拨"
)

# boss 审批（finance 不能批调拨）
approve-fund-transfer(transfer_id=transfer.transfer_id)
# master 余额 -50000，青花郎现金 +50000
```

### 场景7：融资与还款

```
# 建融资单（银行放款）
fo = create-financing-order(
    brand_id=青花郎ID,
    amount=500000,
    interest_rate=6.5,
    start_date="2026-01-01",
    maturity_date="2026-12-31",
    bank_name="工商银行"
)
# 青花郎融资账户余额 +500000（负债）

# 还款
submit-financing-repayment(
    financing_order_id=fo.id,
    principal_amount=100000,
    payment_account_id=青花郎现金账户ID
)
# boss 审批后：青花郎现金 -100000 - 利息，融资余额 -100000
```

---

## 17. ID 查找规则

大部分写入/审批工具支持两种查找方式：

| 实体 | UUID 查找 | 业务编号查找 |
|------|----------|-------------|
| 订单 | ✓ | order_no（如 SO-20260422-xxx） |
| 采购单 | ✓ | po_no（如 PO-20260422-xxx） |
| 稽查案件 | ✓ | case_no（如 IC-20260422-xxx） |
| 报销单 | ✓ | claim_no（如 EX-20260422-xxx） |
| 请假单 | ✓ | request_no |
| 其他 | ✓ | 仅 UUID |

**建议**：优先用业务编号（更可读），系统会自动 fallback 到 UUID 查找。

---

## 18. 重要注意事项

1. **政策模板自动匹配**：`policy_template_id` 可以不传，系统根据品牌+箱数自动匹配。5箱的订单自动匹配 min_cases=5 的模板。没有匹配模板则拒绝建单
2. **金额系统自动算**：total_amount、deal_amount、policy_gap、customer_paid_amount 全部自动计算
3. **收款全进 master**：register-payment 自动把钱存入总资金池，不会进品牌账户
4. **salesman 身份锁定**：业务员建单/建客户时 salesman_id 被强制设为本人
5. **箱↔瓶自动换算**：quantity_unit="箱" 时系统自动 × bottles_per_case
6. **调拨审批只有 boss**：finance 可以创建调拨申请但不能审批
7. **请假审批是 hr**：不是 finance
8. **F类报销的 pay = 公司付给员工**：不是厂家付钱
9. **提成基数 = customer_paid_amount**：不是 total_amount（company_pay 时有区别）
10. **稽查只算已执行的**：pending 状态的案件不进利润台账
11. **信用客户送达时自动生成应收**：不需要手动创建 Receivable
12. **工资里没有厂家补贴**：补贴单独走 ManufacturerSalarySubsidy
13. **融资是负债**：融资账户余额增加代表欠银行更多钱
14. **政策兑付完成后自动生成退款申请**：如果有垫付人
15. **每个操作都有审计日志**：所有写入操作自动记录 who/when/what
16. **政策模板按箱数精确匹配**：`min_cases=5` 的模板只能用于 5 箱订单。10 箱订单会自动匹配 min_cases=10 的模板，没有就拒绝建单
17. **所有 ID 参数支持名称查找**：customer_id、salesman_id、product_id、brand_id 等都支持传 UUID、业务编码或名称，系统自动匹配
