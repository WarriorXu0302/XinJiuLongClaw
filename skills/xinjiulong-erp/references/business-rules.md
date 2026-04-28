# 硬性业务规则速查

这些规则是**后端强校验**的。Agent 操作前必须先自查，违反会被 400 拒，反复调还可能造成账务错乱。

---

## 零、Agent 身份隔离红线（最高优先级）

**Agent 永远不持有任何固定的 ERP 账号 / JWT**。Agent 帮一个员工操作 ERP，**必须用这个员工本人的身份**登录：

1. **首次对话必须绑定**：用户在飞书（或其他入口）第一次找 Agent 时，Agent 调 `POST /api/feishu/exchange-token`（body 含该用户 `open_id`）。
   - 返回 200 → 拿到**该员工本人**的短期 JWT（15 分钟 TTL）+ role + brand_ids，所有后续 API 调用用这个 token。
   - 返回 404 "未绑定" → Agent 推"绑定 ERP 账号"卡片，**引导用户本人填 ERP 用户名 + 密码**，提交后调 `POST /api/feishu/bind` 建立 `open_id ↔ erp_user` 映射。
   - 返回 403 "账号已停用" → 告诉用户找管理员。
2. **绝不使用其他人的 token**：哪怕 boss 说"帮我让小李也查一下他的绩效"，Agent 必须引导**小李本人**来对话里绑定账号后自查。boss 的 JWT 永远只能查 boss 自己有权限看的数据。
3. **JWT 过期自动重新 exchange**，但 exchange 出来的还是当前 open_id 对应的那个员工。Agent **绝不缓存、绝不跨用户复用 JWT**。
4. **Agent 不持有 Service Account / 超级 token**。`X-Agent-Service-Key` 只是 Agent 服务跟 ERP 建立信任的密钥，不代表任何人——**真正调业务接口必须用员工 JWT 的 Authorization header**。

**为什么这样设计**：
- RBAC + RLS 全部挂在 JWT 里（role / brand_ids / user_id）。Agent 用谁的 JWT，数据就按谁的权限过滤。
- salesman 看不到 master 账户、看不到别人客户 —— 这是后端 RLS 强制的，不是 Agent 自觉。Agent 用 salesman 的 JWT，想越权也调不出来。
- 员工自己在飞书对话里做的每一个操作，最终在 audit_logs 里 `user_id` 落的是他本人 —— 责任归属清楚。

**Agent 绝不能做**：
- ❌ 不能用 admin 万能账号"帮" salesman 查数据（哪怕 salesman 主动请求）
- ❌ 不能把一个 open_id 的 JWT 用于另一个 open_id 的对话
- ❌ 不能绕过 exchange-token 直接让用户"随便说个员工号就行"
- ❌ 不能把 ERP 密码明文记进对话历史或 memory（bind 成功后立即丢弃）
- ❌ 不能跨会话复用过期 JWT（必须重新 exchange）

**异常兜底**：如果 Agent 在一个对话里发现同一 open_id 突然换了 role 或 brand_ids，立刻丢弃缓存重新 exchange，防止"员工调岗 / 离职后 token 还在用旧权限"。

---

## 一、权限矩阵（RBAC）

| 角色 | 能做 | 不能做 |
|---|---|---|
| `salesman` | 建客户/建订单/上传凭证/拜访打卡 | 看 master 账户 / 看别 salesman 的客户 / 审批任何东西 / 建政策模板 |
| `sales_manager` | salesman 全部 + 部门报表 / 建销售目标 | 审批工资 / 批采购 |
| `finance` | 审批收款/采购/调拨/工资二审/报销/政策到账/到账对账 | 建客户 / 建订单 / 建政策模板（只有 boss） |
| `hr` | 员工档案/薪酬方案/工资一审/请假一审/KPI 配置 | 审批采购/调拨/大额报销 |
| `warehouse` | 出库/入库/收货/盘点 | 审批任何金额相关 |
| `purchase` | 建采购单 | 审批（需 boss/finance） |
| `boss` | 全部（最终审批人） | — |
| `admin` | 全部（含系统管理） | — |
| `manufacturer_staff` | 政策外审（外部审） | 其他 |

**RLS（行级安全）强制**：
- salesman 看客户，只能看 `CustomerBrandSalesman.salesman_id=me AND brand_id ∈ 我的品牌`
- 账户查询，salesman 看不到 `level='master'`
- 所有带 `brand_id` 的表，salesman 只看自己绑定的品牌范围

---

## 二、幂等键清单

这些接口的**重复调用安全的**（后端已做幂等保护），Agent 遇到网络超时可以重试：

| 接口 | 幂等键 | 实现方式 |
|---|---|---|
| `POST /policies/requests/confirm-arrival` | `(PolicyRequestItem.id, status='arrived')` | 已 arrived 跳过 |
| `POST /policies/requests/{id}/confirm-fulfill` | `(item.id, status='settled')` | 已 settled 直接返回"已归档" |
| `POST /salary-records/generate` | `(employee_id, period)` UNIQUE 约束 | 已有则 return 或 overwrite |
| `POST /salary-order-links` | `(order_id, is_manager_share)` UNIQUE | DB 约束挡重复 |
| `POST /accounts/transfers/{id}/approve` | `status != 'pending'` 拒绝 | 状态校验 |
| `POST /orders/{id}/confirm-payment` | 没有 pending Receipt 时 400 | 凭状态挡 |

---

## 三、不能重试的接口（可能重复动账）

这些接口**Agent 绝不能自动重试**，哪怕是网络超时：

- `POST /receipts`（直接建 Receipt 立刻动账）
- `POST /mcp/register-payment`（同上）
- `POST /purchase-orders/{id}/approve`（扣账户）
- `POST /inspection-cases/{id}/execute`（扣账户+动库存）
- `POST /financing-orders/repayments/{id}/approve`（扣账户）
- `POST /accounts/fund-flows`（手工加流水）

**遇到超时怎么办**：
1. 等 5 秒
2. 查询实体当前状态确认是否成功
3. 如已成功不再调用
4. 如失败告诉用户"可能已执行，请查询确认"

---

## 四、必须 `with_for_update` 的并发场景

后端已加行锁的地方（不用重复 / 但 Agent 理解一下有助于排查）：

| 接口 | 锁对象 | 防什么 |
|---|---|---|
| approve_repayment | FinancingRepayment + FinancingOrder | 并发 approve 时 `repaid_principal +=` 丢笔 |
| cancel_paid_purchase_order | payment_to_mfr Account | 并发撤销让账户变负 |
| execute_inspection_case | InspectionCase | 并发 execute 重复扣账户 |
| pay_daily_claim | ExpenseClaim + Account | 并发 pay 双扣 |
| confirm_settlement_allocation | ManufacturerSettlement + PolicyClaim | 并发分配冲突 |

---

## 五、订单建单校验

**Agent 建单前**必须收集到 + 校验：

| 字段 | 必填 | 校验 |
|---|---|---|
| `customer_id` | ✅ | 客户必须绑了品牌（CBS），否则 400 |
| `brand_id` | ✅ | salesman 必须绑定该品牌 |
| `settlement_mode` | ✅ | 三选一：customer_pay / employee_pay / company_pay |
| `items[].product_id` | ✅ | 产品必须属于该品牌 |
| `items[].quantity` + `quantity_unit` | ✅ | 箱或瓶 |
| `unit_price` | ✅ | 指导价 |
| `deal_unit_price` | 看模式 | company_pay / employee_pay 必填 |
| `policy_template_id` | 有政策才填 | 可选 |

**Agent 建单前必先调**：
- `POST /orders/preview` — 拿到预览金额（应收 / 到手价 / 提成预估 / 政策差）
- `GET /policy-templates/templates/match?brand_id=X&cases=N&unit_price=Y` — 政策匹配

**展示给用户**的卡片必须含：
- 客户名
- 品牌 + 结算模式
- 商品明细
- 指导价总额 / 客户实付 / 业务员垫付 / 公司应收 / 预估提成
- 匹配到的政策（如有）

---

## 六、收款核心规则

### 路径 A：业务员上传凭证（P2c-1 核心）

```
POST /orders/{id}/upload-payment-voucher
```

**做什么**：
1. 建 Receipt（`status='pending_confirmation'`，`account_id=None`）
2. **不动账户**
3. Order.payment_status = `pending_confirmation`
4. 通知财务"有新凭证待审"

**Agent 对话**：引导业务员发图片 → 转到 ERP uploads → 调此接口。

### 路径 B：财务直接建（`POST /api/receipts`）

- 仅 finance/boss 权限
- 立即 `status='confirmed'`，立即动 master 账户
- 触发 apply_per_receipt_effects（应收分摊）
- 触发 apply_post_confirmation_effects（Commission/KPI/里程碑）
- **Agent 很少主动用**，除非财务明确说"我直接录"

### 路径 C：财务审批（最常见）

```
POST /orders/{id}/confirm-payment       # 批量批准该订单所有 pending
POST /orders/{id}/reject-payment-receipts  # 批量驳回
```

**铁律（all-or-nothing）**：一次审批该订单**所有** pending Receipt，不支持一条一条审。

---

## 七、政策核心规则

### 政策匹配

```
GET /policy-templates/templates/match?brand_id=X&cases=N&unit_price=P
```

返回可用政策模板列表（0 / 1 / 多）。

**Agent 应对**：
- 0 条 → 告诉用户"没有匹配政策，无法下单"，不要硬塞
- 1 条 → 自动选用
- 多条 → 推卡片让用户挑

### 政策兑付链路

```
1. 物料出库：POST /policies/requests/{id}/fulfill-materials
2. 提交凭证：POST /policies/requests/{id}/submit-voucher（actual_cost）
3. 财务归档：POST /policies/requests/{id}/confirm-fulfill（幂等）
4. 厂家到账：POST /policies/requests/confirm-arrival（幂等；F 类账户 += arrival）
```

**关键区分**：`fulfilled`（给了客户）≠ `arrived`（厂家打款了）。

### 垫付返还自动触发

- 条件：PolicyRequestItem 状态 ∈ (fulfilled, settled) + advance_payer_type='employee'
- 后端自动生成 PaymentRequest（pending 状态）
- 财务批准后扣 payment_to_mfr 账户 → 打款给业务员

---

## 八、库存规则

### 库存单位

**Inventory.quantity 永远是"瓶"**。入库箱单位时：
```
瓶数 = 箱数 × Product.bottles_per_case
```

### 出库类型（StockFlow.flow_type）

| 类型 | 触发 | 必须扫码？ |
|---|---|---|
| `order_out` | 订单出库 | ✅（高端酒/扫码品） |
| `policy_out` | 政策物料出库 | 可选 |
| `direct_out` | 手工出库 | ❌（但敏感，需授权） |
| `transfer_out/in` | 调仓 | - |
| `inspection_in/out` | 稽查回收/发出 | ✅ |
| `return_in` | 退货回仓 | - |
| `tasting_out` | 品鉴酒消耗 | - |

### 低库存预警

```
GET /inventory/low-stock?threshold=5
```

Agent 发现返回非空时主动推消息给 warehouse + 相关品牌的 boss。

---

## 九、工资规则

### 底薪来源

`EmployeeBrandPosition` 必须 `is_primary=true` 的那条决定：
- `BrandSalaryScheme.fixed_salary`（固定底薪）
- `BrandSalaryScheme.variable_salary_max × 考核完成率`（浮动底薪）
- `BrandSalaryScheme.attendance_bonus_full × 请假梯度`（全勤奖：0 天 100% / 1 天 80% / ... / ≥5 天 0%；迟到 = 0）

**无主属品牌 = 工资生成报错**（"未设置主属品牌"），Agent 引导 HR 去配置。

### 提成计算

```
Commission = comm_base × commission_rate × kpi_coefficient
```

- `comm_base`：订单的 `customer_paid_amount or total_amount`（按结算模式）
- `commission_rate`：EBP 个性化 > BrandSalaryScheme 默认
- `kpi_coefficient`：查 `kpi_coefficient_rules` 表（按品牌 + 完成率区间）

### KPI 系数规则（新功能）

由 boss/admin 在 `/hr/kpi-rules` 页面配置：
- 每条规则：品牌 × 完成率区间 [min, max) × 模式（linear/fixed）
- 默认 seed：<50% 系数 0；≥50% 按完成率线性
- 历史留存：改规则 = 旧记录 effective_to = 今天 + 新记录 effective_from = 今天
- 生成工资时冻结 `SalaryRecord.kpi_rule_snapshot` 字段

### 工资审批流

```
draft → pending_approval → approved → paid
```

- `draft / rejected`：允许 recompute（重算提成部分，不动 HR 手填罚款奖金）
- `approved / paid`：不能 recompute / delete（需反向凭证）
- recompute 权限：boss + admin

### 厂家补贴（不进工资条）

`ManufacturerSalarySubsidy` 独立记账：
- 生成：`POST /manufacturer-subsidies/generate-expected`（按 EBP.manufacturer_subsidy × 在岗天数）
- 到账：`POST /manufacturer-subsidies/confirm-arrival`（金额严格校验，动品牌 cash 账户）

---

## 十、稽查规则

### 5 种 case_type 必选 1

A 系列（我的酒跑出去了）：
- `outflow_malicious`（恶意窜货）
- `outflow_nonmalicious`（非恶意）
- `outflow_transfer`（被转码）

B 系列（别处的酒搞回来）：
- `inflow_resell`（回售入库）
- `inflow_transfer`（转码入库）

### 执行流程

```
create（填完整信息，profit_loss 后端算）
 → 审批（boss）
 → execute（SELECT FOR UPDATE，动账 + 动库存）
 → 归档
```

**删除铁律**：只允许 pending/approved/rejected 删，`executed/closed` **绝对拒绝**。

### 金额校验

execute 前预算 `total_debit`，品牌 cash 余额不够整体 400（让用户先调拨）。

---

## 十一、采购规则

### 付款金额必须对齐

```
cash_amount + f_class_amount + financing_amount == SUM(items.quantity × unit_price)
```

前端允许浮点精度容错 ±0.01。

### 收货前置状态

必须 `paid/shipped`（**品鉴仓例外**：任何状态都能收货）。已 `received/completed` 拒绝重复收货。

### 撤销付款

仅 `paid` 状态可撤销（已 received 的走退货）。`SELECT FOR UPDATE` 锁 payment_to_mfr + 余额校验。

---

## 十二、融资规则

### 还款类型

- `normal`：正常还款（现金扣本金+利息）
- `return_warehouse`：退仓（厂家代还本金，公司只付利息）

### F 类结算校验

F 类金额 > 0 时**预校验余额**，不够整体 400（历史 bug 已修）。

### 品牌一致性

- `submit_repayment`：校验 `pay_acc.brand_id == order.brand_id`
- `submit_repayment`：校验 `f_class_account.brand_id == order.brand_id`

### 并发锁

approve 时 `SELECT FOR UPDATE` 锁 repayment + order。

---

## 十三、审批中心聚合规则

用户（boss/finance）说"看一下今天要审啥"时，Agent 并行调：

```
GET /orders/pending-receipt-confirmation       # 收款
GET /orders?status=policy_pending_internal    # 政策
GET /purchase-orders?status=pending           # 采购
GET /accounts/pending-transfers               # 调拨
GET /payroll/salary-records?status=pending_approval  # 工资
GET /attendance/leave-requests?status=pending  # 请假
GET /payment-requests?status=pending          # 垫付返还
GET /expense-claims?status=pending            # 报销
GET /financing-orders/pending-repayments      # 融资还款
GET /expenses?status=pending                  # 费用
```

按用户角色过滤（salesman 不看这些），聚合成汇总卡片。

---

## 十四、跨品牌资金红线

**严格禁止的跨品牌资金动账**（后端已校验）：

1. 用别品牌的现金还本品牌融资（submit_repayment 校验）
2. 用别品牌 F 类结算本品牌融资（submit_repayment 校验）
3. A 品牌的 ManufacturerSettlement 分配到 B 品牌的 PolicyClaim（confirm_settlement_allocation 校验）

**允许的跨品牌资金流动**（需 boss 批准）：
1. `POST /accounts/transfer`：master → 品牌 / 品牌 → master / 品牌 → 品牌
2. 不同品牌销售同品牌补贴（ManufacturerSalarySubsidy 按销售品牌算，员工主属品牌算底薪）

---

## 十五、通用错误处理

| HTTP 状态 | 含义 | Agent 应对 |
|---|---|---|
| 400 | 业务校验错 | 原样显示 `detail`，不要自己解释 |
| 401 | 未登录或 token 过期 | 重新 exchange-token |
| 403 | 权限不够 | "你的角色没有此操作权限" |
| 404 | 找不到 | "资源不存在或不在你权限范围" |
| 409 | 冲突（唯一键等） | 展示冲突原因，让用户决策 |
| 500 | 系统错 | 记时间，让用户联系技术 |
| 超时 | 网络问题 | **不要自动重试动账接口** |

---

## 十六、审计日志

所有关键动作都有 `audit_logs` 记录：
- action（操作类型）
- entity_type + entity_id（实体）
- user_id（操作人）
- changes（变更内容）
- created_at（时间）

查询：`GET /audit-logs?action=X&entity_type=Y&date_from=...`

Agent 遇到"某笔钱为啥动了"类问题时可以调这个接口帮用户追溯。

---

## 十七、资金流闭环总图（必记）

```
客户回款 → master
  → 调拨到品牌 cash
    → 发工资 / 付政策垫付 / 还融资利息 / 付稽查回收 / 付报销

厂家政策到账 → 品牌 F 类
  → confirm_fulfill 后 settled_amount 计入利润
  → company_pay 垫付回收时 F 类 → 品牌 cash

厂家工资补贴到账 → 品牌 cash（直接加）

融资放款 → 品牌 financing
  → 每期还款时 financing 销账 + 现金扣本息

采购付款 → 扣品牌 cash/F 类/financing
  → 同时 payment_to_mfr += cash+financing（记应付累计）
  → 撤销时反转

稽查 execute 时：
  A1/A2 扣品牌 cash（回收款）+ 罚款
  A3 扣 payment_to_mfr（被转码抵扣）
  B1 加品牌 cash（回售收入）
  B2 扣品牌 cash（买入）+ 加 payment_to_mfr

分货收款（share_out）：
  master += + payment_to_mfr -=（双记账）
```

---

## 十八、Agent 行动前的自检清单（每次都要过）

动任何**涉及金额或状态变更**的接口之前，Agent 必须心里过一遍：

1. ✅ **用户是谁（角色）？** 有没有权限调这个接口？
2. ✅ **当前实体状态是什么？** 允许转到目标状态吗？
3. ✅ **会动哪些账户？** 每个账户的方向和金额对吗？余额够吗？
4. ✅ **关联什么其他实体？** 会触发什么副作用（Commission / 通知 / 里程碑）？
5. ✅ **是否可逆？** 不可逆的话用户真的准备好了吗？
6. ✅ **幂等吗？** 如果 Agent 恶意重试会怎样？

Agent 不能保证完美——但**必须把"可能的错账"告诉用户再让他决定**。

---

## 十九、Agent 绝不能做的事

1. ❌ **跳过审批流程**直接给财务审批了（如 MCP 曾犯过）
2. ❌ **重复调用动账接口**（超时后重试）
3. ❌ **替用户决策**是否接受某次操作（要卡片确认）
4. ❌ **自己算金额**（必须调 preview / 以后端返回为准）
5. ❌ **泄露 master 账户金额**给 salesman（RLS 外的额外防护）
6. ❌ **用 MCP 工具绕开 HTTP 校验**（MCP 现已对齐 HTTP，但禁止"找后门"）
7. ❌ **伪造 Receipt.status**（如 source_type 字段 AI 不要填 "policy_f"——这是内部字段）
8. ❌ **删除已动账数据**（Receipt confirmed / Salary paid / Inspection executed）
