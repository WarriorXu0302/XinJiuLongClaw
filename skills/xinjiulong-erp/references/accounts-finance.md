# 账户资金 / 资金流水 / 调拨 / 融资

## 账户模型

```
Account（账户）
├─ account_type: cash / f_class / financing / payment_to_mfr / master_cash
├─ level: master / project
├─ brand_id: 品牌归属（master 为 NULL）
├─ balance: 当前余额
└─ is_active
```

### 账户类型含义

| account_type | 作用 | 谁进谁出 |
|---|---|---|
| `cash` | 品牌现金账户 | 客户回款从 master 调拨过来 / 发工资出去 / 付政策垫付出去 |
| `f_class` | F 类账户 | 政策到账（厂家打款）进这里 |
| `financing` | 融资账户 | 融资款进，每期利息出 |
| `master_cash` | 总资金池 | 所有客户回款进这里，按需调拨到品牌 |
| `payment_to_mfr` | 应付给厂家 | 采购付款进（代表已付给厂家），撤销采购时返还 |

**关键**：salesman 角色看不到 master 账户（RLS 屏蔽 `level='master'`），只有 boss/finance/admin 能。

## Agent 场景 1：查账户余额

### 单个查
```
GET /api/accounts?brand_id=<青花郎>&account_type=cash
```

返回青花郎的现金账户列表。Agent 给 boss / finance 展示：`青花郎现金账户：¥123,456`。

### 总览（按品牌聚合）
```
GET /api/accounts/summary
```

返回：
```json
{
  "brands": [
    {"brand_name": "青花郎", "cash": 123456, "f_class": 45000, "financing": 0},
    {"brand_name": "五粮液", ...}
  ],
  "master_cash": 500000,
  "payment_to_mfr": 200000
}
```

Agent 用来回答"公司总资产多少""各品牌现金多少"。

### 单个账户流水
```
GET /api/accounts/fund-flows?account_id=<acc-id>&date_from=2026-04-01&date_to=2026-04-30&skip=0&limit=50
```

每条 FundFlow 有：`amount / flow_type(credit/debit) / balance_after / related_type / related_id / created_at`。

Agent 用于对账、追溯"这 ¥1000 是哪来的"。

## Agent 场景 2：品牌间调拨

老板说"从 master 调 10 万给青花郎现金"。

### 2.1 申请调拨

```
POST /api/accounts/transfer
{
  "from_account_id": "<master cash id>",
  "to_account_id": "<青花郎 cash id>",
  "amount": 100000,
  "reason": "4 月发工资"
}
```

返回 TransferRequest `status=pending`。

### 2.2 审批调拨

```
POST /api/accounts/transfers/{id}/approve       # 或 reject
```

只有 boss 能批。批准后：
- `from_account.balance -= amount` + FundFlow
- `to_account.balance += amount` + FundFlow
- status → `approved`

### Agent 引导

1. 用户"调 10 万到青花郎现金"
2. Agent 查一下 from/to 账户 → 确认 master 余额够
3. 卡片确认："从 Master 现金 ¥500K → 青花郎现金（当前 ¥23K），金额 ¥100K。确认？"
4. 确认后调 `POST /api/accounts/transfer`
5. 告诉用户"已申请调拨，等老板批准"
6. 如果当前用户就是老板，Agent 再推一张审批卡片让他直接点批准

### 2.3 待审批列表

```
GET /api/accounts/pending-transfers
```

Agent 推送给老板 / 财务："有 N 笔调拨待审"。

## Agent 场景 3：手工加流水（反向凭证）

财务/boss 发现账目有误，手工调整：

```
POST /api/accounts/fund-flows
{
  "account_id": "...",
  "flow_type": "credit",       // credit=加 / debit=扣
  "amount": 500,
  "notes": "补记 4 月忘记登记的小额回款",
  "related_type": "manual_adjustment",
  "related_id": null
}
```

**Agent 关键提醒**："手工加流水会直接改账户余额，**不可逆**。请确认必要（走正规业务流程更安全）。只有 boss/finance 可操作。"

## 资金流向（所有路径）

```
客户回款 ──→ Master 现金池 ──(调拨)──→ 品牌现金账户
                                       ├──→ 发工资
                                       ├──→ 付政策垫付
                                       ├──→ 付稽查回收成本
                                       └──→ 采购（部分） 

厂家政策兑付 ──→ 品牌 F 类账户 ──(调拨)──→ 品牌现金 / Master

厂家工资补贴 ──→ 品牌现金账户（直接加）

采购付款 ──→ payment_to_mfr 账户（记账用，表示"已付给厂家"）
          ←── 采购撤销退回

融资款 ──→ 品牌融资账户 ──(归还本息)──→ 出去
```

## 融资单（financing_orders）

公司从融资平台借钱。

### 建融资单
```
POST /api/financing-orders
{
  "brand_id": "...",
  "financing_account_id": "<该品牌融资账户>",
  "principal": 1000000,
  "interest_rate": 0.006,          // 月利率
  "period_months": 6,
  "start_date": "2026-04-01"
}
```

后端：
- 融资账户 `balance += principal` + fund_flow
- 生成每月还款计划（FinancingRepayment）

### 查利息
```
GET /api/financing-orders/{id}/calc-interest
```

返回本息总计、已还、剩余。

### 提交还款
```
POST /api/financing-orders/{id}/submit-repayment
{
  "repayment_id": "...",
  "amount": 170000,
  "from_account_id": "<品牌现金 id>"
}
```

status=pending。

### 审批还款
```
POST /api/financing-orders/repayments/{id}/approve
```

批准后：
- 品牌现金账户扣 amount
- 融资账户扣 amount（本金部分） + 记利息支出（进利润台账"融资利息"科目）
- 如果全部还清 → FinancingOrder.status=cleared

### 退仓还款
采购退货后，厂家退款 → 抵扣融资本金：

```
POST /api/financing-orders/{id}/submit-return
{ "return_amount": 30000 }
```

Agent 一般不主动用。

## 报销申请（expense_claims）

员工向公司报销，不走工资条。

### 流程

```
建单 (pending) → 审批 (approved) → 申请厂家 (applied)
→ 厂家到账 (arrived) → 兑付给员工 (fulfilled) → 付款 (paid) → 结算 (settled)
```

### 建报销
```
POST /api/expense-claims
{
  "applicant_id": "<员工 id>",
  "brand_id": "...",
  "amount": 500,
  "category": "business_trip",
  "reason": "去西安拜访客户出差",
  "voucher_urls": ["..."]
}
```

### 审批 / 付款

```
POST /api/expense-claims/{id}/approve
POST /api/expense-claims/{id}/pay
{ "account_id": "<品牌现金 id>" }
```

付款后该员工收款。

Agent 引导普通员工走报销 = 推 Form 卡片收集参数 → 建单 → 告诉用户"已提交，等审批"。

## 应收账款

```
GET /api/receivables?customer_id=X&status=overdue
GET /api/receivables/aging
```

Aging 按账龄分组（0-30天/30-60/60-90/>90）。Agent 给 finance 展示"客户 X 有 ¥Y 逾期"。

## 常见错误

| detail | 解释 |
|---|---|
| "账户余额不足 ¥X" | 付钱时余额不够 |
| "两账户属于不同品牌，不能直接调拨" | 要经 master 中转 |
| "该调拨单已审批，不能重复" | 幂等保护 |
| "你没有查看该账户的权限" | RLS 挡（salesman 看 master） |

## Agent 关键提醒

- **所有动账的操作推卡片确认**，不要自动执行
- **手工加流水**要二次确认（"你确定要手工调整账户 X 的余额吗？这不可逆"）
- 涉及**大额（> ¥10 万）** 调拨，Agent 提示"该金额较大，建议告知 boss 当面复核"
- RLS 屏蔽的账户，Agent 不要说"该账户不存在"——说"你的角色没有查看权限"
