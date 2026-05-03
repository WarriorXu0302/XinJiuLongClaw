# ERP 业务原子化与开发状态

本文件按**业务流**切分 ERP（管理台）的原子动作。配合 `business-atoms-mall.md` + `business-atoms-bridges.md` 构成完整业务网。

ERP 核心闭环 plan 明确"已稳定"（决策 #1，见 rustling-floating-treehouse.md），本文件粒度偏"主干动作 + 状态机"，不做 mall 那样逐端点穷举。

**图例同 mall**：🟢 done · 🟡 coded 未 E2E · 🔴 gap · ⚪ n/a

---

## 流 E1：B2B 订单建单 → 政策审批 → 出库 → 送达

### 状态机

```
pending ──submit-policy──→ policy_pending_internal
                                 ↓ approve-policy（boss）
                    ┌────────────┼────────────┐
                    ↓                         ↓
       (need_external=False)    (need_external=True)
                    ↓                         ↓
                approved         policy_pending_external
                                              ↓ confirm-external（厂家）
                                          approved
                    └────────────┬────────────┘
                                 ↓ ship（warehouse 扫码）
                              shipped
                                 ↓ upload-delivery + confirm-delivery
                              delivered
                                 ↓ （凭证 + 财务审批流见流 E2）
                              completed
```

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E1.1 | **预览订单**（匹配政策）| salesman/sm_mgr/boss | `POST /api/orders/preview` | 客户可见（RLS） · 政策模板匹配 | 返预算金额 | — | 🟢 |
| E1.2 | **建单** | salesman/sm_mgr/boss | `POST /api/orders` | — | Order(pending) + items · 按结算模式预填 customer_paid_amount | — | 🟢 |
| E1.3 | 删除 pending 订单 | salesman/boss | `DELETE /api/orders/{id}` | status=pending | — | — | 🟢 |
| E1.4 | **提交政策审批** | salesman/sm_mgr | `POST /api/orders/{id}/submit-policy` | status=pending | status=policy_pending_internal | 给 boss | 🟢 |
| E1.5 | **批准政策** | boss | `POST /api/orders/{id}/approve-policy` | status=policy_pending_internal · need_external 决定下一状态 | status=approved OR policy_pending_external | — | 🟢 |
| E1.6 | **驳回政策** | boss | `POST /api/orders/{id}/reject-policy` | status ∈ policy_pending_* | status=policy_rejected · reason | 给 salesman | 🟢 |
| E1.7 | **重提**（驳回后改单） | salesman/boss | `POST /api/orders/{id}/resubmit` | status=policy_rejected | status=policy_pending_internal | — | 🟢 |
| E1.8 | 厂家确认（外审） | manufacturer_staff | `POST /api/orders/{id}/confirm-external` | status=policy_pending_external | status=approved | 给 salesman | 🟢 |
| E1.9 | **出库**（扫码）| warehouse/boss | `POST /api/orders/{id}/ship` | status=approved · 扫满箱数 | 扣 inventory（按 LIFO/FIFO 批次）· StockFlow(order_out) · barcodes OUTBOUND · status=shipped | — | 🟢 |
| E1.10 | 上传**送货照片** | warehouse/boss | `POST /api/orders/{id}/upload-delivery` | status=shipped | Attachment | — | 🟢 |
| E1.11 | **确认送达** | warehouse/boss | `POST /api/orders/{id}/confirm-delivery` | status=shipped · 至少 1 张送货照 | status=delivered | 给 salesman | 🟢 |
| E1.12 | 查利润 | finance/boss | `GET /api/orders/{id}/profit` | status=completed | 聚合 ProfitLedger | — | 🟢 |

### E2E 测试状态：🟢 tested（ERP 历史核心闭环，生产使用中）

---

## 流 E2：收款凭证 → 审批 → completed + 提成

### 状态机

```
order.status=delivered + payment_status=unpaid
  ↓ upload-payment-voucher
payment_status=pending_confirmation
  Receipt(status=pending_confirmation)
  ├─ finance approve（/orders/{id}/confirm-payment）
  │   → Receipt→confirmed · 入 master 现金 · 累加 customer_paid_amount
  │   → (若累计 ≥ 应收) → order.status=completed · payment_status=fully_paid · 生成 Commission · F 类政策解锁兑付
  │   → (累计 < 应收) → payment_status=partially_paid 保持
  │
  └─ finance reject（/orders/{id}/reject-payment-receipts）
      → Receipt→rejected · 不动账 · salesman 收通知重传
```

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E2.1 | 业务员**上传凭证** | salesman/sm_mgr/boss | `POST /api/orders/{id}/upload-payment-voucher` | status=delivered/partially_paid | Receipt(pending) · MallAttachment-like · payment_status → pending_confirmation | — | 🟢 |
| E2.2 | finance 直接建 Receipt（无需业务员）| finance/boss | `POST /api/receipts` | — | Receipt(status=**confirmed**) 立即入账 | — | 🟢 |
| E2.3 | **批准凭证**（整单的 pending 批量）| finance/boss | `POST /api/orders/{id}/confirm-payment` | ≥1 pending Receipt | 所有 pending → confirmed · 入 master · 累加 customer_paid_amount · 若全款 → completed + Commission | — | 🟢 |
| E2.4 | **驳回凭证**（单张 / 批量）| finance/boss | `POST /api/orders/{id}/reject-payment-receipts` | receipt.status=pending | 全批 rejected · payment_status 回 unpaid/partially_paid | salesman 收通知 | 🟢 |
| E2.5 | 查订单的**所有 Receipt** | finance/boss/salesman | `GET /api/orders/{id}/receipts` | — | — | — | 🟢 |
| E2.6 | **删除凭证**（错传） | finance/boss | `DELETE /api/receipts/{id}` | status=pending（confirmed 不可删）| — | — | 🟢 |

### E2E 测试状态：🟢 tested

---

## 流 E3：政策模板 + F 类账户 + 兑付

### 状态机（Policy 单子）

```
draft ──submit──→ pending ──approve──→ active ──execute──→ executed
                              ↓
                          rejected
```

（订单里挂载的 policy_snapshot 不是独立状态机，跟随订单走）

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E3.1 | 政策模板 CRUD | boss/finance | `/api/policy-templates` | — | — | — | 🟢 |
| E3.2 | 政策**匹配** | 任何员工 | `GET /api/policy-templates/templates/match?brand_id=&cases=&unit_price=` | — | 返最优模板 | — | 🟢 |
| E3.3 | 政策**启用/禁用** | boss | `PUT /api/policy-templates/{id}/status` | — | — | — | 🟢 |
| E3.4 | **F 类政策应收**（厂家返利挂账）| system（订单 completed 自动）| 订单完成联动 | 已 confirm external | F 类 Receivable 挂到品牌 | finance | 🟢 |
| E3.5 | **F 类到账** | finance/boss | `POST /api/accounts/f-class-receive` | — | 入品牌 F 类账户 · Receivable.status=received | — | 🟢 |
| E3.6 | F 类**兑付**（salesman 自费订单的差额）| finance/boss | `POST /api/policies/{id}/execute` | F 类账户有足额 | 品牌 F 类减账 · 业务员拿补贴 · ProfitLedger record | salesman | 🟢 |

### E2E 测试状态：🟢 tested

---

## 流 E4：提成结算 + 工资单

### 状态机（SalaryRecord）

```
draft（系统生成月度草稿）
  ↓ submit_for_approval
pending_approval
  ├─ approve（boss）→ approved
  │                    ↓ pay_salary
  │                 paid（终态 · 对应 commission 标 settled）
  │
  └─ reject（boss）→ draft（重算）
```

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E4.1 | 订单 completed**自动生成 Commission** | system | `post_commission_for_order` in receipt/order service | order.status=completed · mall_order 用 commission_service.post_commission_for_order | Commission(status=pending, employee_id=linked or 直属) | — | 🟢 |
| E4.2 | **Commission 冲销**（mall 退货 approved）| system | `approve_return` in return_service | return.status=pending | pending commission → reversed | — | 🟢 |
| E4.3 | **partial_closed top-up**（欠款后补交全款）| system | `manual_record_payment` | 订单之前 partial_closed → 现在 received≥pay | 新补一笔 Commission 差额（避免 commission_posted 卡住）| — | 🟢 |
| E4.4 | 月末**生成工资单** | hr/boss | `POST /api/payroll/generate/{year}/{month}` | 本月无 draft | SalaryRecord(draft) · 汇总 pending Commission | — | 🟢 |
| E4.5 | 提交审批 | hr | `POST /api/payroll/{id}/submit` | status=draft | status=pending_approval | boss | 🟢 |
| E4.6 | **批准工资** | boss | `POST /api/payroll/{id}/approve` | status=pending_approval | status=approved | — | 🟢 |
| E4.7 | **发放工资** | finance/boss | `POST /api/payroll/{id}/pay-salary` | status=approved | status=paid · 关联 Commission.status=settled · settled_at | salesman | 🟢 |
| E4.8 | 驳回工资单 | boss | `POST /api/payroll/{id}/reject` | status=pending_approval | status=draft（重算） | hr | 🟢 |

### E2E 测试状态：🟢 tested（mall 4d commission 汇总 commit 记录显示已验证）

### 🔴 已知 gap
- **E4.2 冲销**：mall 退货后 `reversed` commission 在**下月工资单生成时**是否被排除？plan 说"工资生成查 pending + settled 排除 reversed"，但**未端到端回归**。若 reversed 被错误计入，业务员工资虚高。

---

## 流 E5：稽查案件（A1 亏损扣款）

### 状态机

```
pending ──submit──→ (审批流由 boss/finance 驳回/批准)
  ├─ rejected → 终态
  └─ approved ──execute──→ executed（终态 · 品牌现金扣款 + 利润台账）
```

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E5.1 | 业务员**发现 + 创建**案件 | salesman/inspector | `POST /api/inspection-cases` | barcode/qrcode 至少一项 · quantity > 0 | InspectionCase(pending) | finance/boss | 🟢 |
| E5.2 | **批准**案件 | boss/finance | `POST /api/inspection-cases/{id}/approve` | status=pending | status=approved | — | 🟢 |
| E5.3 | **执行扣款** | finance/boss | `POST /api/inspection-cases/{id}/execute` | status=approved | brand cash -A1_loss · ProfitLedger(inspection_loss) · 扣 salesman 提成 | — | 🟢 |
| E5.4 | 驳回案件 | boss | `POST /api/inspection-cases/{id}/reject` | status=pending | status=rejected | — | 🟢 |

### E2E 测试状态：🟢 tested

### 🔴 已知 gap 无，但注意 mall 业务员通过 workspace 创建的 inspection 只能到 **pending**，执行权还在 ERP 原审批流。

---

## 流 E6：采购单（含跨仓入 mall）

### 状态机

```
pending ──approve-finance──→ paid（现金+F 类+融资合计=total）
           │                    ↓
           ├─ cancel → cancelled
           │
           └─ ship（厂家）→ shipped
                            ↓
                       receive（warehouse 扫码）
                            ↓
                         received（存货入 ERP/mall 仓）
                            ↓
                         completed（票据归档）
```

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 通知 | 状态 |
|---|---|---|---|---|---|---|---|
| E6.1 | 建采购单 | purchase/warehouse/boss | `POST /api/purchase-orders` | target_warehouse_type 合法 · 付款合计=total | PO + items | finance | 🟢 |
| E6.2 | **批准付款** | finance/boss | `POST /api/purchase-orders/{id}/approve` | status=pending · 账户足额 | 品牌现金/F 类/融资扣款 · status=paid | 供应商 | 🟢 |
| E6.3 | 驳回 | finance/boss | `POST /api/purchase-orders/{id}/reject` | status=pending | status=cancelled · 退款（未扣）| — | 🟢 |
| E6.4 | 撤销（已批准后）| boss/finance | `POST /api/purchase-orders/{id}/cancel` | status=paid/shipped · 未 receive | 退款回账户 | — | 🟢 |
| E6.5 | **收货**（ERP 仓）| warehouse/boss/purchase | `POST /api/purchase-orders/{id}/receive?batch_no=` · target=erp | status=paid/shipped · warehouse_id 合法 | Inventory +qty · StockFlow(inbound) · 批次入库 | — | 🟢 |
| E6.6 | **收货**（mall 仓，跨仓）| warehouse/boss/purchase | 同上 · target=mall_warehouse | mall_warehouse_id 合法 · 每 item 有 MallProduct 映射 | MallInventory +qty · 加权平均成本 · MallInventoryFlow(IN, ref_type=purchase) · **无条码** | — | 🟡 |
| E6.7 | 扫码批量导入条码（配合 6.5）| warehouse/boss | `POST /api/inventory/barcodes/batch-import` | 条码不存在 | Inventory barcode in_stock | — | 🟢 |

### E2E 测试状态：⏳ partial
- ✅ E6.1-6.5 ERP 仓路径 tested
- ❌ **E6.6 mall 仓路径没有端到端跑过**（mall 的 P0 阻塞项，详见 mall 文档流 8）

---

## 流 E7：客户 + 政策兑付

### 原子动作

| # | 动作 | 角色 | 端点 | 状态 |
|---|---|---|---|---|
| E7.1 | 客户 CRUD | salesman/sm_mgr/boss | `/api/customers` | 🟢 |
| E7.2 | 业务员**归属**绑定客户 | boss/sm_mgr | `PUT /api/customers/{id}/assign` | 🟢 |
| E7.3 | 客户 **信用额度** 管理 | boss/finance | `PUT /api/customers/{id}/credit-limit` | 🟢 |
| E7.4 | 客户订单历史 | salesman/boss/finance | `GET /api/customers/{id}/orders` | 🟢 |
| E7.5 | 客户应收挂账 | finance | `/api/customers/{id}/receivables` | 🟢 |

### E2E 测试状态：🟢 tested

---

## 流 E8：考勤 / 请假 / 报销 / 绩效 / KPI

### 原子动作

| # | 动作 | 角色 | 端点 | 状态 |
|---|---|---|---|---|
| E8.1 | 打卡（含地理围栏） | 员工 | `POST /api/attendance/checkin` | 🟢 |
| E8.2 | 拜访客户（进店/出店） | salesman | `POST /api/attendance/visits/enter\|leave` | 🟢 |
| E8.3 | 月度考勤 | 员工/hr | `GET /api/attendance/monthly-summary` | 🟢 |
| E8.4 | 请假申请 + 审批 | 员工/hr | `GET/POST /api/attendance/leave-requests` + `/approve\|reject` | 🟢 |
| E8.5 | 报销申请 + 审批 + 支付 | 员工/finance | `/api/expense-claims` | 🟢 |
| E8.6 | 销售目标 + 奖金档位（admin 配） | boss/hr | `/api/sales-targets` | 🟢 |
| E8.7 | 业务员看自己的 KPI | salesman | `GET /api/sales-targets/my-dashboard` | 🟢 |
| E8.8 | 考勤规则（地理围栏 + 时间段） | admin/hr | `/api/attendance/rules` | 🟢 |

### E2E 测试状态：🟢 tested

---

## 流 E9：账户 / 资金池 / 调拨

### 原子动作

| # | 动作 | 角色 | 端点 | 状态 |
|---|---|---|---|---|
| E9.1 | 账户 CRUD（master / 品牌现金 / F 类 / 融资）| boss/finance | `/api/accounts` | 🟢 |
| E9.2 | 账户余额查询 | finance/boss | `GET /api/accounts/summary` | 🟢 |
| E9.3 | 账户流水 | finance/boss | `GET /api/accounts/{id}/flows` | 🟢 |
| E9.4 | 资金调拨（master → 品牌）| boss/finance | `POST /api/accounts/transfer-internal` | 🟢 |
| E9.5 | 资金批准（transfer 要走审批）| boss | `POST /api/accounts/transfers/{id}/approve` | 🟢 |
| E9.6 | 融资到账 + 还款 | finance/boss | `/api/financing/*` | 🟢 |
| E9.7 | 支付单（付供应商 / F 类兑付等） | finance/boss | `/api/finance/payment-requests` | 🟢 |
| E9.8 | 财务审批中心 | finance/boss | `/api/approvals/finance` | 🟢（已加 mall 退货 tab） |

### E2E 测试状态：🟢 tested

---

## 流 E10：审批中心 / 通知 / 审计 / 品鉴仓

### 原子动作

| # | 动作 | 角色 | 端点 | 状态 |
|---|---|---|---|---|
| E10.1 | 审批中心聚合（政策 + 凭证 + 付款 + F 到账 + transfer + **商城待确认** + **商城退货**）| finance/boss | `GET /api/approvals/finance` | 🟢 |
| E10.2 | 通知列表 + 未读数 + 标已读 | 员工 | `/api/notifications` | 🟢 |
| E10.3 | 审计日志查询 + 导出 | boss/finance | `/api/audit-logs` | 🟢 |
| E10.4 | 登录日志（C 端）| admin/boss | `/api/mall/admin/login-logs` | 🟢 |
| E10.5 | 品鉴物料仓入库/出库/兑付 | manufacturer_staff/warehouse | `/api/tasting/*` | 🟢 |
| E10.6 | 绩效系数/奖金规则 | boss/hr | `/api/performance/*` | 🟢 |
| E10.7 | Dashboard（ERP）| 任何 | `/api/dashboard/*` | 🟢 |

### E2E 测试状态：🟢 tested

---

## ERP 整体评估

- ERP 核心闭环（E1 + E2 + E4 + E5 + E6 + E9）**已生产级稳定**
- 与 mall 强关联的 3 处：
  - **E4.1 Commission 生成**（mall 订单 completed → 走 commission_service.post_commission_for_order）→ 已对接
  - **E4.2 退货冲销**（mall approve_return → pending commission 标 reversed）→ 已对接但未回归
  - **E6.6 采购入 mall 仓**（P0 未端到端跑）→ **上线阻塞**

ERP 单独的 🔴 gap 极少；所有"进行中"的问题都在 **ERP ⇄ mall 连接点**，详见 `business-atoms-bridges.md`。
