# 新鑫久隆 ERP — AI 智能体操作指南

> 本文档是给 AI Agent（飞书机器人/MCP 客户端）看的系统操作手册。
> 你需要完全理解这里的业务逻辑，才能正确使用 ERP 工具。

---

## 1. 公司是做什么的

新鑫久隆是一家**白酒经销商**。公司代理多个白酒品牌（青花郎、五粮液、汾酒、珍十五），从厂家进货，卖给客户（烟酒店、餐饮、团购会员）。

核心赚钱模式：**厂家给政策补贴**。进货价885元/瓶，卖给客户650元/瓶，表面亏235元，但厂家会通过政策补回来。

---

## 2. 品牌 = 事业部

每个品牌独立核算，有自己的：
- **现金账户**：日常支出用（工资、采购、报销）
- **F类账户**：厂家政策/补贴到账专用
- **融资账户**：银行贷款余额
- **库存**：主仓、备用仓、品鉴酒仓
- **员工岗位**：业务员/经理绑定到具体品牌

**公司总资金池（master）**：所有客户回款先进这里，再调拨给品牌。

---

## 3. 资金流向（最重要！）

```
客户付款 ──→ 总资金池（master 现金）
                │
                ├──调拨──→ 品牌现金账户 ──→ 付工资/采购/报销
                │
厂家政策到账 ──→ 品牌F类账户（或现金账户）
                │
厂家补贴到账 ──→ 品牌现金账户
```

**关键规则：**
- 客户付的钱，不管哪个品牌的订单，**全部进 master**
- 品牌账户的钱只能通过**调拨**从 master 转入
- 品牌现金不够用时，boss 发起调拨，审批后执行
- F类到账是厂家打来的政策补贴，不是客户的钱

---

## 4. 三种结算模式

每个订单有三种收款方式，**决定了公司应收多少钱**：

| 模式 | 客户付 | 业务员补 | 公司承担 | 公司应收 |
|------|--------|---------|---------|---------|
| **customer_pay** | 885×瓶数（全价） | 0 | 0 | = 总额（885×瓶数） |
| **employee_pay** | 650×瓶数 | 235×瓶数 | 0 | = 总额（两笔凑齐） |
| **company_pay** | 650×瓶数 | 0 | 公司垫差额 | = 到手价（650×瓶数） |

**举例**（5箱×6瓶/箱=30瓶）：
- customer_pay：客户付 26,550，公司应收 26,550
- employee_pay：客户付 19,500 + 业务员补 7,050 = 公司应收 26,550
- company_pay：客户付 19,500，公司应收 19,500（差额 7,050 记政策应收等厂家补）

---

## 5. 订单全流程

```
建单(pending) → 提交政策审批(policy_pending_internal)
    → boss审批通过(approved) → 扫码出库(shipped)
    → 确认送达(delivered) → 上传收款凭证(每笔建Receipt)
    → 全款到齐(fully_paid) → 财务确认收款(completed)
    → 政策兑付解锁
```

**AI 操作对应工具：**

| 步骤 | 工具 | 谁能操作 |
|------|------|---------|
| 建单 | `create-order` | boss/salesman/sales_manager |
| 编辑 | `update-order` | boss/salesman/sales_manager（仅pending） |
| 提交审批 | `submit-order-policy` | boss/salesman/sales_manager |
| 审批通过 | `approve-order` | boss（一步到位） |
| 驳回 | `approve-order`(action=reject) | boss |
| 重新提交 | `resubmit-order` | boss/salesman/sales_manager |
| 发货/送达/取消 | `update-order-status` | boss/warehouse/salesman |
| 登记收款 | `register-payment` | boss/finance/salesman |
| 确认收款完成 | `confirm-order-payment` | boss/finance |
| 标记完成 | `complete-order` | boss/finance |

---

## 6. 政策流程

**政策 = 厂家给经销商的促销补贴**。比如"买10箱送1箱"或"每箱补贴50元"。

```
创建政策模板 → 建订单时选模板 → 提交政策申请
    → 内部审批 → 厂家审批 → 出货兑付 → 厂家到账确认
```

| 工具 | 用途 |
|------|------|
| `create-policy-template` | 建模板（指导价、到手价、最低箱数） |
| `query-policy-templates` | 查模板列表（建单时需要 template_id） |
| `create-policy-request` | 建政策申请 |
| `submit-policy-approval` | 提交审批 |
| `fulfill-policy-materials` | 兑付物料 |
| `confirm-policy-arrival` | 确认政策到账 |
| `confirm-policy-fulfill` | 确认兑付完成 |
| `create-policy-claim` | 建理赔单 |
| `approve-policy-claim` | 审批理赔 |

---

## 7. 费用/报销流程

**两种类型：**
- **普通报销**（ExpenseClaim）：员工垫付后找公司报销
- **F类报销**：厂家应该承担的费用，公司先垫付，等厂家打回来

```
创建报销单(pending) → 审批(approved) → 付款(paid)
```

**F类报销的钱流：**
1. 员工先垫付（比如请客户吃饭 1,500 元）
2. 公司审批后从品牌现金付给员工
3. 公司再向厂家申请报销
4. 厂家打款到品牌F类/现金账户
5. `approve-expense`(action=pay) = 标记公司已付给员工

| 工具 | 用途 |
|------|------|
| `create-expense` | 创建报销单 |
| `approve-expense` | 审批（approve/reject/pay） |
| `query-expenses` | 查询报销列表 |
| `approve-expense-claim` | 审批理赔（approve/reject/pay） |
| `query-expense-claims` | 查询理赔列表 |

---

## 8. 稽查案件

**稽查 = 查处窜货、市场违规**。分5种类型：

| 类型 | 代码 | 含义 | 盈亏公式 |
|------|------|------|---------|
| A1 恶意窜出 | outflow_malicious | 我们的货被人低价窜走 | -(回收价-到手价)×瓶 - 罚款 |
| A2 非恶意窜出 | outflow_nonmalicious | 非恶意串货，回收入主仓 | (指导价-回收价)×瓶 - 罚款 |
| A3 被转码 | outflow_transfer | 货被转了码 | -罚款 |
| B1 窜入回售 | inflow_resell | 别人的货窜到我们这，回售 | (回售价-买入价)×瓶 + 奖励 |
| B2 窜入入库 | inflow_transfer | 别人的货入我们仓 | (指导价-买入价)×瓶 + 奖励 |

**关键字段含义：**
- `deal_unit_price`：到手价（卖给客户的价）
- `purchase_price`：回收价/买入价
- `sale_price`/`original_sale_price`：指导价
- `resell_price`：回售价（B1专用）
- `penalty_amount`：罚款（A类）
- `reward_amount`：奖励（B类）

```
建案(pending) → 执行(confirmed/executed) → 结案
```

---

## 9. 采购流程

```
建采购单(pending) → 审批(approved) → 供应商发货 → 收货(received)
```

| 工具 | 用途 | 权限 |
|------|------|------|
| `create-purchase-order` | 建采购单 | boss/purchase/warehouse |
| `approve-purchase-order` | 审批 | boss/finance |
| `receive-purchase-order` | 确认收货 | boss/warehouse/purchase |
| `query-purchase-orders` | 查询列表 | boss/purchase/warehouse/finance |

---

## 10. 薪资流程

```
创建薪酬方案 → 生成工资单(draft) → 批量提交(pending_approval)
    → 审批(approved) → 发放(paid)
```

**工资组成：**
- 底薪：从 BrandSalaryScheme（品牌×岗位）取
- 提成：订单全额回款后自动计算
- 考核浮动：KPI 完成度
- 全勤奖：按迟到天数梯度扣
- 厂家补贴：**不进工资条**，独立走政策应收

| 工具 | 用途 |
|------|------|
| `create-salary-scheme` | 建/改薪酬方案 |
| `generate-salary` | 一键生成当月工资 |
| `batch-submit-salary` | 批量提交审批 |
| `approve-salary` | 审批工资单 |
| `pay-salary` | 发放（支持单条/批量） |
| `generate-subsidy-expected` | 生成厂家补贴应收 |
| `confirm-subsidy-arrival` | 确认补贴到账 |

---

## 11. 融资流程

公司可以通过银行贷款给品牌融资。

```
建融资单 → 品牌融资账户余额增加（负债）
    → 还款申请(pending) → 审批 → 品牌现金扣减 + 融资余额减少
```

| 工具 | 用途 |
|------|------|
| `create-financing-order` | 建融资单 |
| `submit-financing-repayment` | 提交还款申请 |
| `approve-financing-repayment` | 审批还款 |
| `query-financing-orders` | 查询融资列表 |

---

## 12. 客户管理

客户分两种：
- **channel（渠道）**：烟酒店、超市等长期合作
- **group_purchase（团购）**：会员制团购

每个客户可以绑定多个品牌，每个品牌对应一个业务员。

| 工具 | 用途 |
|------|------|
| `create-customer` | 建客户（必须指定类型 channel/group_purchase） |
| `update-customer` | 编辑客户信息 |
| `bind-customer-brand-salesman` | 绑定品牌-业务员关系 |
| `query-customers` | 查询客户列表 |

---

## 13. 角色权限

| 角色 | 能做什么 |
|------|---------|
| **boss** | 一切操作 |
| **finance** | 财务全部、审批采购/费用/工资、稽查、政策兑付 |
| **hr** | 员工管理、薪酬方案、绩效KPI、审批请假 |
| **salesman** | 自己的订单/客户/收款/请假 |
| **sales_manager** | 所属品牌全部业务数据、销售目标 |
| **warehouse** | 库存/出入库/商品/品鉴酒 |
| **purchase** | 采购单/收货/供应商 |

**重要：** salesman 只能看自己的数据，建单时 salesman_id 强制绑定本人。

---

## 14. 常见操作场景

### 场景1：业务员建单卖货
```
1. query-brands → 拿到品牌ID
2. query-customers → 找到客户
3. query-policy-templates → 选政策模板（拿到 template_id）
4. query-products → 选商品
5. create-order → 建单（自动算价格）
6. approve-order → boss 审批
7. update-order-status(action=ship) → 发货
8. update-order-status(action=confirm-delivery) → 送达
9. register-payment → 登记收款
10. confirm-order-payment → 财务确认
```

### 场景2：月底发工资
```
1. generate-salary(period="2026-04") → 生成当月工资单
2. query-salary-records(period="2026-04") → 检查
3. batch-submit-salary(period="2026-04") → 提交审批
4. approve-salary → boss/finance 逐条审批
5. pay-salary(batch_mode=true, period="2026-04") → 批量发放
```

### 场景3：采购补货
```
1. query-suppliers → 找供应商
2. query-products → 选商品
3. query-warehouses → 选仓库
4. create-purchase-order → 建采购单
5. approve-purchase-order → 审批
6. receive-purchase-order → 到货收货
```

### 场景4：处理窜货
```
1. create-inspection-case(
     case_type="outflow_malicious",
     direction="outflow",
     purchase_price=800,  # 花800回收
     deal_unit_price=650, # 原来卖650
     quantity=30,
     penalty_amount=5000
   )
   → 自动计算亏损: -(800-650)×30 - 5000 = -9500
2. approve-inspection → 执行
```

---

## 15. 注意事项

1. **建单必须选政策模板**：`policy_template_id` 是必填的，指导价从模板取
2. **金额不要自己算**：系统会根据模板自动计算 total_amount、deal_amount、policy_gap
3. **收款全进 master**：`register-payment` 自动把钱进总资金池
4. **ID 和编号都能用**：大部分工具支持按 UUID 或业务编号（order_no/po_no/case_no/claim_no）查找
5. **salesman 身份锁定**：业务员建单/建客户时，salesman_id 会被强制设为本人
6. **箱↔瓶自动换算**：quantity_unit 传"箱"时系统会×每箱瓶数
7. **flush 后才能查**：写入后的聚合查询系统已处理，不用担心
