# 工资 / 提成 / 厂家补贴

## 数据模型

```
Position                       岗位（salesman / sales_manager / admin / finance / hr / ...）
BrandSalaryScheme              品牌 × 岗位的薪酬方案（底薪/提成率/全勤奖/绩效工资）
EmployeeBrandPosition (EBP)    员工 × 品牌 × 岗位（一员工可在多品牌兼职，主属品牌决定底薪）
  - is_primary: bool           主属品牌 → 底薪从这里取
  - commission_rate            员工个性化提成率（覆盖方案默认）
  - manufacturer_subsidy       厂家补贴月额

SalaryRecord                   月度工资单（draft → pending_approval → approved → paid）
  └─ SalaryOrderLink           该月关联的订单（提成明细）
      唯一约束：(order_id, is_manager_share)
ManufacturerSalarySubsidy      厂家工资补贴（pending → advanced → reimbursed）

Commission                     单笔提成（订单 fully_paid 后生成，status=pending）
                               结算到 SalaryRecord 时 status=settled
AssessmentItem                 KPI 考核项（kpi_revenue / kpi_customers 等）
```

## 工资生成流程（月底）

```
1. 生成本月所有员工工资单
   POST /api/payroll/salary-records/generate
   → 每员工一条 SalaryRecord (status=draft)
   → 底薪按主属品牌 EBP 的 BrandSalaryScheme 取
   → 关联已 fully_paid 的订单 Commission（挂 SalaryOrderLink）
   → 算迟到扣款、全勤奖、绩效工资
   → 算 actual_pay

2. 人事逐条审查
   PUT /api/payroll/salary-records/{id}  # 调整明细（罚款/奖金）

3. 提交审批
   POST /api/payroll/salary-records/{id}/submit (status → pending_approval)
   或批量：POST /api/payroll/salary-records/batch-submit

4. 老板/财务审批
   POST /api/payroll/salary-records/{id}/approve (status → approved)

5. 财务发放
   POST /api/payroll/salary-records/{id}/pay      # 品牌现金账户扣款
   或批量：POST /api/payroll/salary-records/batch-pay
```

## Agent 场景 1：生成本月工资单

用户："生成 2026-04 工资单"

Agent:
1. 确认卡片："即将为 N 个员工生成 2026-04 工资单，按主属品牌算底薪，关联本月已全款订单的提成。确认？"
2. 调 `POST /api/payroll/salary-records/generate { "period": "2026-04" }`
3. 返回：
   ```json
   {
     "created": 15,       // 新建的
     "skipped": [{"employee_id": "...", "reason": "未设主属品牌"}]
   }
   ```
4. Agent 告诉用户"已生成 15 份，3 人跳过（详见 skipped 列表）"

## Agent 场景 2：看某员工工资单详情

```
GET /api/payroll/salary-records/{id}/detail
```

返回：底薪、全勤奖、罚款、各品牌提成明细、应发、实发。

Agent 给员工本人（用 `/me` 查自己），或 HR/boss 查任意员工。

## Agent 场景 3：改工资单（调整明细）

```
PUT /api/payroll/salary-records/{id}
{
  "fine_deduction": 200,        // 罚款
  "bonus_other": 500,           // 其他奖金
  "actual_pay": 8500             // 留空=系统算；填了=手动覆盖
}
```

HR 能改 draft / rejected 状态的。已 approved/paid 的拒绝改。

## Agent 场景 4：审批发放工资

**审批**（老板视角）：

```
POST /api/payroll/salary-records/{id}/approve
```

Agent 收到推送后展示摘要 + "批准 / 驳回"按钮。

**发放**（财务视角）：

```
POST /api/payroll/salary-records/{id}/pay
Body: { "account_id": "<品牌现金账户>" }
```

后端扣该品牌现金账户余额（如果不够会 400 提示要调拨）。

Agent 关键提醒："发放是钱从品牌现金账户出的，发放后不可逆；余额不足先做调拨。"

## Agent 场景 5：厂家工资补贴

厂家给员工的月度补贴（独立走政策应收，不进工资条）。

### 生成本月应收

```
POST /api/payroll/manufacturer-subsidies/generate-expected
{ "period": "2026-04", "brand_id": "..." }
```

按 EBP.manufacturer_subsidy × 在岗天数 / 月天数。

### 确认到账（厂家打款了）

```
POST /api/payroll/manufacturer-subsidies/confirm-arrival
{
  "brand_id": "...",
  "period": "2026-04",
  "arrived_total": 5000.00       // 厂家实际打款金额
}
```

**关键校验**：`arrived_total` 必须严格等于该品牌该期应收总额，否则 400。Agent 告诉用户"金额不符，需手工调整"。

后端：
- 找到所有 (brand, period, status=pending+advanced) 的补贴 → status=reimbursed
- 品牌现金账户 += arrived_total + 写 fund_flow
- 如果之前是 advanced（公司已垫付），返还公司

### 手工标记到账（金额不严格匹配时）

```
POST /api/payroll/manufacturer-subsidies/manual-mark-arrived
{ "subsidy_id": "...", "arrived_amount": 480 }
```

单条处理，有审计日志。Agent 仅在批量确认 400 后的兜底场景用，并且**明确强调**"手工标记不经过完整校验，请确认金额无误"。

## Agent 场景 6：提成结算

Order fully_paid 后自动生成 Commission（`status=pending`）。

**手动结算**（挂到某工资单）：

```
POST /api/hr/commissions/{id}/settle
{ "salary_record_id": "..." }
```

一般 `/salary-records/generate` 会自动做，Agent 很少手动操作。

**关键约束（Bug #3 修复）**：`SalaryOrderLink` 有 `(order_id, is_manager_share)` 唯一约束。并发生成工资单时第二个请求会 IntegrityError——Agent 遇到这个错误时**不要自动重试**，告诉用户"该订单提成已被其他工资单领取"。

## Agent 场景 7：KPI 考核项

```
GET /api/payroll/assessment-items?employee_id=X&period=2026-04
```

返回员工本月 KPI 进度（回款额、客户数等）。Agent 用来回答"我本月业绩到哪了"。

### 刷新实际值

```
POST /api/performance/refresh-assessment-actual
{ "employee_id": "...", "period": "2026-04" }
```

按最新收款/订单重算 `actual_value`，同时**推销售目标里程碑通知**（50%/80%/100%/120%，已修复 bug #C）。

## 常见错误

| detail | 解释 |
|---|---|
| "未设置主属品牌，无法生成底薪" | EBP 没 is_primary=true 的 |
| "账户余额不足 ¥X，请先调拨" | 发工资时品牌现金不够 |
| "补贴金额不符：应收 ¥A，实际 ¥B" | confirm-arrival 金额严格校验 |
| "该订单提成已被其他工资单领取" | UniqueConstraint 冲突 |

## 工资单状态中文

| status | 中文 |
|---|---|
| draft | 草稿 |
| pending_approval | 待审批 |
| approved | 已审批 |
| paid | 已发放 |
| rejected | 已驳回 |
