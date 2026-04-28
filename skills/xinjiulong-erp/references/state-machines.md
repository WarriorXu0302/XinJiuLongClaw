# 状态机完全手册

所有业务实体的状态流转。Agent 操作前必须核对**当前状态 → 允许的下一状态**，调用允许不通过的 transition 会被后端 400 拒。

---

## 1. Order（订单）— `OrderStatus`

```
pending → policy_pending_internal ──┬──→ approved → shipped → delivered → completed
                                    │                                    ↑
                                    └──→ policy_pending_external → approved
                                                                         │
                                    (任何 pending 阶段可驳回)            │
                                          ↓                              │
                                     policy_rejected ←─────────────────┐ │
                                          ↓                            │ │
                                     (修改后重提)                       │ │
                                          → policy_pending_internal ──┘ │
                                                                         │
                                              partial_closed ←───────────┤
                                               (delivered >60d 未全款)   │
```

| 状态 | 中文 | 能进的下一状态 | 前置校验 | 触发动作 |
|---|---|---|---|---|
| `pending` | 待提交 | `policy_pending_internal` / `policy_rejected`（删） | salesman/sales_manager/boss 创建 | `POST /orders/{id}/submit-policy` |
| `policy_pending_internal` | 内部待审 | `policy_pending_external` / `approved` / `policy_rejected` | boss 审批 | `POST /orders/{id}/approve-policy`（`need_external` 决定走哪条） |
| `policy_pending_external` | 厂家外审 | `approved` | 厂家账户确认 | `POST /orders/{id}/confirm-external` |
| `approved` | 已审批 | `shipped` | warehouse 扫码出库 | `POST /orders/{id}/ship` |
| `shipped` | 已出库 | `delivered` | 送达确认（上传送货照片） | `POST /orders/{id}/upload-delivery` + `/confirm-delivery` |
| `delivered` | 已送达 | `completed`（走 confirm_payment 自动） / `partial_closed` | payment_status=fully_paid 时自动 → completed | 自动（见下） |
| `completed` | 已完成 | （终态） | Receipt 全部 confirmed 且合计 ≥ 应收 | 由 `confirm_payment` 触发 |
| `policy_rejected` | 已驳回 | `policy_pending_internal`（重提） | salesman 修改订单后 | `POST /orders/{id}/resubmit` |

**禁止的转换**（调用会 400）：
- 跳过 `policy_pending_internal` 直接到 `approved`（MCP 以前有 bug，已修）
- `completed` 状态改回其他（一旦完成不可逆）
- `shipped` → `pending`（状态只能向前）

**钱的副作用**（哪些状态转换会动账）：
- `approved → shipped`：扣库存（StockFlow 类型 `order_out`），不动账户
- `delivered → completed`（由 confirm_payment 触发）：Receipt status 转 confirmed → 入 master 现金池，生成 Commission

---

## 2. Receipt（收款凭证）— `PaymentStatus` 里的 receipt.status 字段

```
pending_confirmation ──(财务批准)──→ confirmed ──(终态)
         │
         └─(财务驳回)──→ rejected ──(终态)
```

| 状态 | 中文 | 什么时候生成 | 动账吗？ |
|---|---|---|---|
| `pending_confirmation` | 待确认 | 业务员 `upload-payment-voucher` | ❌ 不动账 |
| `confirmed` | 已确认 | 财务 `/orders/{id}/confirm-payment` 批准 | ✅ 此时才入 master 现金 + 生成 Commission |
| `rejected` | 已驳回 | 财务 `/orders/{id}/reject-payment-receipts` | ❌ 不动账，存根备查 |

**特殊路径**：finance/boss 直接调 `POST /api/receipts` 建 Receipt，**status 立即=`confirmed`**（跳过 pending，因为是财务自己建）。

**聚合过滤铁律**：所有 `SUM(Receipt.amount)` 必须加 `WHERE Receipt.status='confirmed'`，否则把 pending/rejected 也算进去（历史有 5 处 bug 已修）。

---

## 3. Order 的 PaymentStatus

```
unpaid ──(业务员上传凭证)──→ pending_confirmation ──(财务审批通过)──→ partially_paid
                                                                         │
                                                                (再多笔 Receipt 审批累加到 ≥ 应收)
                                                                         ↓
                                                                    fully_paid
                                                                         │
                                                                    (此时 Order.status = completed)
```

| 状态 | 中文 | 说明 |
|---|---|---|
| `unpaid` | 未付款 | Order 创建默认；没有任何 Receipt 或全 rejected |
| `pending_confirmation` | 待确认 | 有 pending Receipt 但还没 confirmed（订单锁定，不能改） |
| `partially_paid` | 部分已付 | 有 confirmed Receipt 但合计 < 应收 |
| `fully_paid` | 全款到账 | confirmed Receipt 合计 ≥ `customer_paid_amount` |

**达到 `fully_paid` 时**一次性触发：
1. 生成 Commission（pending 状态，按员工品牌提成率 × 应收基数）
2. 刷新 KPI `actual_value`
3. 推销售目标里程碑通知（50% / 80% / 100% / 120%）

---

## 4. InspectionCase（稽查案件）— `InspectionCaseStatus`（实际字符串，不完全匹配 enum）

```
pending ──(boss 审批)──→ approved ──(execute)──→ executed ──(归档)──→ closed
```

| 状态 | 中文 | 能做什么 | 动账吗？ |
|---|---|---|---|
| `pending` | 待审批 | boss 改/审/删 | ❌ |
| `approved` | 已审批 | 可 execute / 可删 / 可驳回 | ❌ |
| `executed` | 已执行 | 归档 / 利润台账读它 / **不可删**（库存账户已变） | ✅ 扣/加品牌现金 + 入库/出库 + A3/B2 动 payment_to_mfr |
| `closed` | 已关闭 | （终态） | ❌ |
| `rejected` | 已驳回 | 可删 | ❌ |

**删除规则**：只允许 `pending / approved / rejected` 状态删；`executed / closed` **绝对拒绝**（历史 bug：拒绝列表漏 `executed`，导致已执行案件被删库存账户错乱，已修）。

**execute 动作**：后端用 `SELECT FOR UPDATE` 锁 case 防并发双扣。

---

## 5. PurchaseOrder（采购单）— `PurchaseStatus`

```
pending ──(boss/finance 审批)──→ approved ──(付款)──→ paid ──(warehouse 收货)──→ received ──→ completed
   │                                                           │
   └──(驳回)──→ cancelled                                      │
                                                               │
    paid ──(finance 撤销)──→ cancelled（FOR UPDATE + 余额校验）│
```

| 状态 | 中文 | 能做什么 |
|---|---|---|
| `pending` | 待审批 | boss/finance 审批 / 驳回 / 删 |
| `approved` | 已审批 | 付款（`approve` 内已做，直接进 paid） |
| `paid` | 已付款 | warehouse 收货；财务可撤销 |
| `shipped` | 已发货 | warehouse 收货 |
| `received` | 已收货 | （自动→ completed 或归档） |
| `completed` | 已完成 | （终态） |
| `cancelled` | 已取消 | （终态；从 pending 或 paid 撤销来） |

**接收（receive）的前置状态铁律**：
- 必须 `paid / shipped`（品鉴仓例外——品鉴仓任何状态都能入库，因为不走付款审批）
- 已 `received / completed` 的必须 **400 拒绝重复入库**（历史 bug：MCP 没挡，已修）

**付款撤销（cancel_paid_purchase_order）**：
- `SELECT FOR UPDATE` 锁 `payment_to_mfr` 账户 + 校验余额足够反扣
- 已 `received` 的不能撤销（库存已变），走退货流程

---

## 6. FinancingOrder（融资单）— `FinancingOrderStatus`

```
active ──(每次还款)──→ partially_repaid ──(全部还清)──→ fully_repaid
   │
   └──(退仓，厂家代还本金)──→ returned（非 enum 标准值，实际字符串）
   │
   └──(违约)──→ defaulted
```

FinancingRepayment 子状态：
```
pending ──(boss 审批)──→ approved ──(扣款成功)──→ （终态）
   │
   ├──(boss 驳回)──→ rejected
   │
   └──(现金余额不足自动驳回)──→ rejected
```

**并发控制**：`approve_repayment` 必须 `SELECT FOR UPDATE` 锁 repayment + order（否则并发 approve 时 `repaid_principal +=` 会丢一笔还款，历史 bug 已修）。

**余额校验**：F 类金额 > 0 时 **预校验 F 类账户余额足够**，否则整体 400（历史 bug：静默跳过导致现金已扣但 F 类没扣，账务失衡，已修）。

**跨品牌**：`submit_repayment` 必须校验 `pay_acc.brand_id == order.brand_id`（历史 bug：无校验可跨品牌串账，已修）。

---

## 7. SalaryRecord（工资单）— 字符串字段，非 enum

```
draft ──(submit)──→ pending_approval ──(boss 批准)──→ approved ──(finance 发放)──→ paid
   │                                        │
   │                                        └──(boss 驳回)──→ rejected
   │                                                               │
   │                                                               └──(HR 修改后重提)──→ pending_approval
   │
   └──(boss/admin recompute)──→ draft（重算 KPI 提成）
```

| 状态 | 中文 | 允许的操作 |
|---|---|---|
| `draft` | 草稿 | HR 改明细 / 提交审批 / 删 / recompute |
| `pending_approval` | 待审批 | boss 批/驳 |
| `approved` | 已审批 | finance 发放（扣品牌现金） |
| `rejected` | 已驳回 | HR 修改后重新提交 / recompute |
| `paid` | 已发放 | （终态） |

**`recompute` 铁律**：仅允许 `draft / rejected` 状态。已 `approved / paid` 的必须走反向凭证冲正（历史需求）。

**并发**：`pay_salary` 需要 `SELECT FOR UPDATE` 锁 SalaryRecord（否则两个财务同时发放会双扣）。

---

## 8. ExpenseClaim（报销）— 字符串字段

```
pending ──(boss/finance 审批)──→ approved ──┬──(F 类流程)──→ applied → arrived → fulfilled → settled
                                             │
                                             └──(日常流程)──→ paid → settled
            │
            └──(boss/finance 驳回)──→ rejected
```

| 状态 | 中文 | 允许操作 | 动账吗？ |
|---|---|---|---|
| `pending` | 待审批 | 批 / 驳 / 删 | ❌ |
| `approved` | 已审批 | F 类走 apply / 日常走 pay | ⚠️ share_out 类型此时动账（master + ptm） |
| `applied` | 已申请厂家 | 对账（厂家到账） | ❌ |
| `arrived` | 已到账 | 兑付 | ❌（到的是 F 类，由 confirm_arrival 处理） |
| `fulfilled` | 已兑付 | 归档 | ❌ |
| `paid` | 已付款（日常） | 归档 | ✅ 扣指定账户 |
| `settled` | 已归档 | （终态） | ❌ |
| `rejected` | 已驳回 | 删 | ❌ |

**删除规则**：只允许 `pending / rejected` 状态删（历史 bug：无状态校验，删已 approved 的 share_out 账户不回滚，已修）。

**驳回规则**：只允许 `pending` 驳回（已 approved 的 share_out 驳回不反转账户，需走反向凭证）。

---

## 9. PolicyRequestItem（政策申请明细）— 字符串 `fulfill_status`

```
pending ──(fulfill-materials 出库物料)──→ fulfilled ──(confirm-fulfill 财务归档)──→ settled
   │
   └──(submit-voucher 提交凭证)──→ fulfilled
                                    │
                                    └──(confirm-arrival 厂家到账)──→ arrived（实际跟 settled 并行存在）
```

| 状态 | 中文 | 含义 |
|---|---|---|
| `pending` | 待兑付 | 刚创建，未出物料 |
| `fulfilled` | 已兑付 | 物料已给到客户 / 已提交凭证 |
| `settled` | 已归档 | 财务确认归档 |
| `arrived` | 已到账 | 厂家钱已打进 F 类账户 |

**关键区分**：
- `fulfilled` = 给客户了（物料出库 or 让利）
- `arrived` = 厂家把钱打给我们了

两者独立推进：一个 item 可以是 `fulfilled` 但不 `arrived`（物料给了客户但厂家没打款）。

**幂等铁律**：
- `confirm-fulfill` 对已 `settled` 的 item 直接返回"已归档"（历史 bug：`settled_amount += ...` 重复累加，已修为 `= arrival_amount or total_value`）
- `confirm-arrival` 对已 `arrived` 的跳过（历史 bug：重复确认让 F 类账户加两次，已修）

---

## 10. PolicyClaim（政策兑付 Claim）— `ClaimRecordStatus`

```
pending ──(allocation-confirm 分配到 settlement)──→ partially_settled ──(分配完)──→ settled
```

**跨品牌校验**：`confirm_settlement_allocation` 必须校验 `settlement.brand_id == claim.brand_id`（历史 bug：无校验走 company_pay 路径动别品牌账户，已修）。

---

## 11. PaymentRequest（垫付返还申请）— `PaymentRequestStatus`

```
pending ──(确认已付)──→ paid（扣品牌现金 + 打款给业务员）
   │
   └──(取消)──→ cancelled
```

自动生成时机：`PolicyRequestItem.fulfill_status in ('fulfilled', 'settled')` + 有 `advance_payer_type='employee'` → 自动创建 pending 状态的 PaymentRequest。

---

## 12. LeaveRequest（请假）— 字符串字段

```
pending ──(HR/boss 审批)──→ approved
                                │
                                └──(驳回)──→ rejected
```

**审批权限**：一般假 HR 审，超 5 天或特殊假种（婚假/产假/丧假）boss 审。

---

## 13. TransferRequest（品牌间调拨）

```
pending ──(boss 批准)──→ approved（执行扣 from + 加 to + 双 fund_flow）
   │
   └──(boss 驳回)──→ rejected
```

**权限**：只有 boss 能批调拨。

---

## 通用：所有"撤销"操作的边界

| 实体 | 可撤销的状态 | 不可撤销的状态（需走反向凭证） |
|---|---|---|
| Order | pending（删） | approved 之后（整个流程下沉到财务冲正） |
| Receipt | pending_confirmation（拒绝） | confirmed（建红冲 Receipt） |
| Payment | pending（admin 可删） | paid（建反向 Payment） |
| Expense | pending（删） | paid（建反向费用） |
| ExpenseClaim | pending / rejected | approved 之后的状态 |
| PurchaseOrder | pending（驳回） / paid（cancel） | received 之后（走退货） |
| InspectionCase | pending / approved / rejected | executed / closed（手工调账） |
| SalaryRecord | draft / rejected（删） | approved / paid（冲正） |
| TransferRequest | pending（驳回） | approved（走反向调拨） |
