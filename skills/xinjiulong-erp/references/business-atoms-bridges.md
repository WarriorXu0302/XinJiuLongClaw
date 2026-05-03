# ERP ⇄ Mall 业务连接点

本文件专注于**跨系统 / 跨域的连接原子**。这是"业务网"最脆弱的地方 — bug 主要藏在跨表/跨路径联动上。

每个桥有三层：
1. **数据绑定**（FK / 冗余字段）
2. **动作触发**（A 域动作 → B 域副作用）
3. **状态同步**（A 域字段改 → B 域是否也要变）

**图例**：🟢 done · 🟡 coded 未 E2E · 🔴 gap · ⚠ 设计待定

---

## 桥 1：身份 — ERP employee ↔ mall_user（业务员双身份）

### 绑定
- `mall_users.linked_employee_id` → `employees.id` FK（NOT NULL 当 user_type='salesman'）
- **CHECK 约束** + **触发器 T1 T2**（plan 决策 #8 的深度防御）

### 动作表

| # | 动作 | 方向 | 源端点 | 目标副作用 | 状态 |
|---|---|---|---|---|---|
| B1.1 | admin 建业务员账号（绑 employee）| ERP→mall | `POST /api/mall/admin/salesmen` | MallUser(linked_employee_id=X) · employee 必须 active | 🟢 |
| B1.2 | 业务员**登录** | mall→ERP 验证 | `wechat-login / login-password` | `assert_salesman_linked_employee_active` 查 employees.status | 🟢 |
| B1.3 | mall 业务员调 **ERP 端点**（打卡/报销等）| mall→ERP | `/api/mall/workspace/*` | workspace 薄转发用 linked_employee_id 构造 ERP 风格 user payload，直接调 ERP service | 🟢 |
| B1.4 | ERP **停用 employee**（离职）| ERP→mall 自动生效 | `PUT /api/employees/{id}/status` | 下次 mall 登录 / refresh / token 解码时失败 403 · mall http.js 识别 detail 弹模态 + 清 token | 🟢 |
| B1.5 | ERP 删除 employee | ERP→mall | 不允许 | linked_employee_id=FK，无级联 delete 设计 | ⚠ 不允许删，只能停用 |
| B1.6 | 重新绑定 employee（换人）| ERP | `PUT /api/mall/admin/salesmen/{id}/rebind-employee` | 校验新 emp active + 未被占用 + 无在途订单 · token_version+1 · 审计 + 通知 | 🟢 |

### 🔴 已知 gap
- ~~**B1.6**：业务员账号建错（绑错 employee）没有"换绑 employee"端点~~ → ✅ **已修**（`PUT /api/mall/admin/salesmen/{id}/rebind-employee`，校验在途订单 + 唯一性 + token 失效 + 审计）
- ~~**B1.4** E2E：停用 employee 后业务员在小程序还**没有任何提示**就被登出~~ → ✅ **已修**（http.js 识别 detail 前缀"您绑定的 ERP 员工已停用"弹模态 + 清 token + reLaunch 登录页）

### 状态机一致性
- employees.status='active' ↔ MallUser 能登录
- 关闭 `is_accepting_orders` 只在 mall 侧（ERP 不感知）

---

## 桥 2：商品 — ERP Product ↔ MallProduct

### 绑定
- `mall_products.source_product_id` → `products.id` FK（nullable — 允许纯商城 SKU）
- mall_product_skus 只是商城的，不回绑 ERP

### 动作表

| # | 动作 | 方向 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B2.1 | admin **从 ERP 导入商品** 建 MallProduct | ERP→mall | `POST /api/mall/admin/products` with source_product_id | MallProduct(source_product_id=X) + MallProductSku | 🟢 |
| B2.2 | admin **建纯商城商品**（source_product_id=null） | mall only | 同上 | 必填 SKU.cost_price | 🟢 |
| B2.3 | admin **改 ERP 商品价格** | ERP | `PUT /api/products/{id}` | **mall 侧独立定价，不联动** | 🟢（设计如此） |
| B2.4 | admin **改 MallProduct 价格** | mall | `PUT /api/mall/admin/products/{id}` | 审计 + 前端价格立刻变 | 🟢 |
| B2.5 | admin **下架 ERP 商品** | ERP | `PUT /api/products/{id}?cascade_mall=true` | 预查 `mall-cascade-impact` 有挂靠在售 → 前端弹确认框可选同步下架所有 MallProduct | 🟢 |
| B2.6 | admin **下架 MallProduct** | mall | `POST /{id}/status` status=off_sale | C 端购物车/收藏/搜索/下单全做 is_available 校验 | 🟢 |

### 🔴 已知 gap
- ~~**B2.5**：ERP 主商品下架后，挂靠 MallProduct 仍 on_sale~~ → ✅ **已修**（加 `mall-cascade-impact` 预查端点 + PUT `cascade_mall=true` 参数 + ERP 前端 ProductList 弹确认框）

---

## 桥 3：订单 — B2B Order ↔ MallOrder（两套系统）

### 绑定
**互斥**：`orders` 是 B2B，`mall_orders` 是商城。两边 **没有 FK 连接**，但：
- `commissions.order_id` vs `commissions.mall_order_id` — 一条 commission 只挂一边（互斥，service 层强约束）
- ProfitLedger 按 brand 汇总：两套订单产生的 profit 都进同一张 ProfitLedger，区分科目（`product_sales` vs `mall_sales_profit`）

### 动作表

| # | 动作 | 方向 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B3.1 | B2B 订单 completed 生成 Commission | ERP→commissions | `confirm-payment` 触发 | Commission(order_id=X, mall_order_id=null) | 🟢 |
| B3.2 | Mall 订单 completed 生成 Commission | mall→commissions | `confirm-payment` 触发 | Commission(mall_order_id=X, order_id=null, employee_id=salesman.linked_employee_id) | 🟢 |
| B3.3 | B2B 订单 completed 入 ProfitLedger | ERP | `apply_post_confirmation_effects` | ProfitLedger(score='product_sales', brand_id=X) | 🟢 |
| B3.4 | Mall 订单 completed 入 ProfitLedger | mall | `profit_service` 实时聚合（无实表） | 查询时按 brand 过滤 mall_orders.status in (completed, partial_closed) | 🟢 |
| B3.5 | Mall partial_closed 坏账 → ProfitLedger | mall | `profit_service` | 科目=mall_bad_debt，金额=pay - received | 🟡（coded 未 E2E）|
| B3.6 | Mall 退货 → ProfitLedger 剔除 | mall | `profit_service` 自动 | status=refunded 被过滤 in_([completed, partial_closed])）| 🟢 |

### E2E 测试状态

- ✅ B3.1/3.2 已测
- ❌ **B3.5 坏账利润 + B3.4 mall 利润聚合在真实数据上**从未验证 — 见 mall 流 5 说明
- ❌ Commission **employee_id 取自 linked_employee_id 而非 salesman.id** — 保证 ERP 工资单能读到。若 linked_employee_id 为 null（理论上不该发生但边缘）**会写 Commission 失败**。有没有兜底？待验证。

### 🔴 已知 gap
- **B3.4 的实时聚合**没有性能缓存。订单量大后 profit-summary 端点慢。P2（当前体量 OK）。

---

## 桥 4：库存 — ERP Inventory ↔ mall_inventory（独立两套）

### 绑定
- **完全独立**，不做跨库存调拨（plan 决策，mall 仓独立运营）
- 唯一连接：**采购单的 `target_warehouse_type` 决定入哪边**（桥 6）

### 动作表

| # | 动作 | 方向 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B4.1 | ERP 订单 ship 扣 inventory | ERP | `POST /orders/{id}/ship` | Inventory -qty + StockFlow | 🟢 |
| B4.2 | Mall 订单下单扣 mall_inventory | mall | `create_order` | mall_inventory -qty + MallInventoryFlow(OUT) | 🟢 |
| B4.3 | Mall 订单 cancel 退 mall_inventory | mall | `cancel_order / admin_cancel` | +qty + IN flow | 🟢 |
| B4.4 | Mall 退货 approve 退 mall_inventory + 条码 | mall | `approve_return` | +qty + IN flow + barcode OUTBOUND→in_stock | 🟡（条码回退刚加） |
| B4.5 | ERP 调拨到 mall 仓 | — | — | **不做** | ⚪ |

### E2E 测试状态
- ❌ **B4.4 刚修的条码回退未验证**（outbound_order_id 的数据是否都有值？）

---

## 桥 5：收款 — B2B Receipt ↔ MallPayment（两套独立）

### 绑定
- B2B `receipts` 表 和 Mall `mall_payments` 表**完全不同**
- 审批中心 UI 上聚合到一起展示（finance 同一角色审批两边）

### 动作表

| # | 动作 | 方向 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B5.1 | B2B 业务员上传凭证 | ERP | `/orders/{id}/upload-payment-voucher` | Receipt(pending) | 🟢 |
| B5.2 | Mall 业务员上传凭证 | mall | `/api/mall/salesman/orders/{id}/upload-payment-voucher` | MallPayment(pending) + MallAttachment | 🟢 |
| B5.3 | finance 审批**两种凭证** | ERP 审批中心 | `/api/approvals/finance` 一个页面两个 tab | 分别调 `/orders/{id}/confirm-payment` 和 `/mall/admin/orders/{id}/confirm-payment` | 🟢 |

### E2E 测试状态：🟢 tested

### ⚠ 设计决策
- 为什么不合并？因为 B2B 订单走 RLS（brand 隔离），mall 订单不走 RLS（C 端无 brand 概念）。强行合并会破 RLS。

---

## 桥 6：采购入 mall 仓（最新实现）

### 绑定
- `purchase_orders.target_warehouse_type` ∈ {erp_warehouse, mall_warehouse}
- `purchase_orders.mall_warehouse_id` → `mall_warehouses.id`（nullable）

### 动作表

| # | 动作 | 方向 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B6.1 | 建 mall 仓 PO | ERP→ | `POST /api/purchase-orders` with target=mall_warehouse | PO.target_warehouse_type='mall_warehouse' + mall_warehouse_id | 🟡 |
| B6.2 | mall 仓**收货入库（必扫码）**| ERP→mall | `POST /api/purchase-orders/{id}/receive` body `barcodes_by_item` | 每 PO item 按应收瓶数扫码 · 全局 UNIQUE + 本次内去重 · MallInventory + 加权平均成本 + Flow(IN) + MallInventoryBarcode × N 行（每瓶 status=in_stock）· 任一校验失败整笔回滚 | 🟡 |
| B6.3 | 无 MallProduct 映射时拒收 | ERP | `receive` 内校验 | 404 提示"请先建商城商品" | 🟢 |

### E2E 测试状态：❌ untested（需在有扫码枪的真实环境走一遍）

### 🟢 P0 已解（正确修法）

白酒业务硬规矩：**每瓶必须扫厂家防伪码入库+出库**。所以采购入 mall 仓和 ERP 仓一样都必扫码，
不存在"散装"路径。

- 收货端：`receive_purchase_order` mall 分支严格要求 `barcodes_by_item`，每 PO item 条码数
  必须等于应入瓶数；全局 UNIQUE 查重（同一厂家码不能重复入库）+ 本次内去重
- 出库端：`ship_order` 恢复"必须扫码"，缺 `scanned_barcodes` 直接 400
- 前端：ERP 管理台 `ReceiveScanPage.tsx` 支持按 PO item 分组扫码 + 进度可视化；
  下架"一键收货"快捷按钮，全部走扫码页

### 🔴 剩余 gap（非阻塞）

- **小程序仓管端扫码入口未实现**：后端 API 就绪，miniprogram 侧 uni.scanCode 接入作为后续
  工作。目前 admin 走 PC 端 + USB 扫码枪（键盘输入）路径。
- **扫码枪硬件驱动**：PC 端当作普通键盘输入（无需驱动）；手机蓝牙扫码枪待引入。

---

## 桥 7：通知 — notification_logs 双 recipient_type

### 绑定
- `notification_logs.recipient_type` ∈ {erp_user, mall_user}
- `notification_logs.mall_user_id` nullable（mall_user 路径填）
- `notification_logs.recipient` 对 erp_user 存 employee user_id；对 mall_user 存 mall_user_id（冗余）

### 动作表

| # | 动作 | 触发 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B7.1 | 通知 ERP 用户（按 role） | ERP service | `notify_roles([admin,boss])` | NotificationLog(recipient_type='erp_user') | 🟢 |
| B7.2 | 通知 mall 用户（指定 ID）| mall service | `notify_mall_user(mall_user_id)` | NotificationLog(recipient_type='mall_user') | 🟢 |
| B7.3 | ERP 员工查自己通知 | ERP | `/api/notifications` | 默认 recipient_type='erp_user' 过滤 | 🟢 |
| B7.4 | Mall 用户查自己通知 | mall | `/api/mall/workspace/notifications` | 按 mall_user_id + recipient_type='mall_user' 过滤 · 反查 related_order_no | 🟢 |

### 桥式通知（两边都发）
mall 业务动作同时通知 ERP admin/boss 和 mall salesman：
- 注册申请 → notify_roles(admin/boss/hr) + 审批后 notify_mall_user(申请人)
- 跳单告警达阈值 → notify_mall_user(salesman) + notify_roles(admin, boss 看 SkipAlertList)
- 退货申请 → notify_roles(admin/boss/finance) + 处理后 notify_mall_user(consumer)

状态：🟢 done

---

## 桥 8：通知内容 entity_type → 跳转

### 绑定约定
- `entity_type = "MallOrder"` → C 端跳 `/pages/order-detail?orderNum=<order_no>`（后端响应带 `related_order_no` 反查）
- `entity_type = "MallSkipAlert"` → salesman 跳告警列表
- `entity_type = "MallUser"` → 跳个人中心
- 旧 `MallPayment / MallReturnRequest` → 都已改用 MallOrder（最新 commit）

状态：🟢 done

---

## 桥 9：审计日志 — audit_logs 跨端共享

### 绑定
- `audit_logs.actor_type` ∈ {erp_user, mall_user, anonymous}
- `audit_logs.mall_user_id` nullable（actor 是 mall 用户时填）
- `audit_logs.action` 按"业务模块.动作"命名（如 `mall_user.register`、`mall_return.approve`、`order.confirm_payment`）

覆盖面：
- ERP 操作 ✅（订单/政策/财务/工资/稽查）
- Mall 业务动作 ✅（注册/换绑/退货/告警裁决/凭证审批/邀请码生成作废）
- 登录失败 ✅（账密 + 微信都审计）

状态：🟢 done

### ⚠ 未记录的动作
- C 端浏览商品（量大不宜记）
- 业务员普通查询（量大不宜记）
- 前端本地操作（如删购物车项 — 后端没动态就不记）

---

## 桥 10：定时任务（housekeeping）作用于 mall 表

ERP 既有 APScheduler 调度器被 mall 复用（plan 决策 #20）。job 在 mall service，不在 ERP service。

| Job | 扫描表 | 副作用 | 状态 |
|---|---|---|---|
| `job_detect_unclaimed_timeout` | mall_orders status=pending_assignment | 记 skip_log(NOT_CLAIMED_IN_TIME) | 🟢 |
| `job_archive_inactive_consumers` | mall_users user_type=consumer | status=inactive_archived · notify | 🟢 |
| `job_notify_archive_pre_notice` | mall_users 即将归档 | 发 7 天预告通知 | 🟢 |
| `job_detect_partial_close` | mall_orders delivered>60d 未全款 | status=partial_closed + commission + profit | 🟡（未 E2E） |
| `job_purge_old_login_logs` | mall_login_logs | 删除 >90 天 | 🟢 |

所有 job 被 `_with_job_log` 装饰，历史查 `/api/mall/admin/housekeeping/logs`。

---

## 业务网总图

```
┌────────────────────────────────────────────────────────────┐
│                      ERP 管理台                              │
│  ┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌──────┐          │
│  │订单  │─│政策  │─│工资单  │─│稽查  │─│账户  │          │
│  └──┬───┘ └──────┘ └───┬────┘ └──────┘ └──┬───┘          │
│     │ ① completed       │ pay_salary        │               │
│     │ 生成 Commission   │ settled           │               │
│     ↓                   │                   │               │
│  Commission ─────────────┘                  │               │
│     │                                       │               │
│     │ ② 按 brand 聚合                       │               │
│     ↓                                       │               │
│  ProfitLedger（mall_sales_profit / mall_bad_debt / inspection_loss / ...）
│     │                                       │               │
│     └─── 金额 ──────────────────────────────┘               │
└────────────────────────────────────────────────────────────┘
          ↕ 桥 1（身份）         ↕ 桥 2（商品）    ↕ 桥 6（采购）
┌────────────────────────────────────────────────────────────┐
│                       Mall 小程序                            │
│                                                              │
│  C 端：                业务员：                admin 端：   │
│  注册审批→下单→退货    抢单→ship→deliver→凭证   审批→改派  │
│      │                    │                       │        │
│  mall_order.status      commission 写入         notify_*  │
│      │                    │                       │        │
│      └── 桥 3/4/5 共享 Commission / ProfitLedger / 账户 ─┘ │
└────────────────────────────────────────────────────────────┘
                ↕ 桥 7/8/9（通知+审计+跳转）
                ↕ 桥 10（定时任务）
```

---

## 🔴 全局 gap 汇总（按修复成本排）

| # | gap | 文件位置 | 优先级 | 估工 |
|---|---|---|---|---|
| 1 | ~~mall 仓 ship 无条码扣减路径~~ ✅ 正确修法：采购收货必扫码 + ship 保持强校验 | `purchase.py:receive` + `order_service.ship_order` + `ReceiveScanPage.tsx` | P0 | 2-4h | **done** |
| 2 | **partial_closed 坏账路径未 E2E** | 造数据脚本 | P0 | 1-2h |
| 3 | **完整贯通 E2E 脚本**（注册→下单→ship→deliver→凭证→确认→退货→退款）| 新建 e2e_full_mall_flow.py | P0 | 2-3h |
| 4 | ~~ERP 商品下架不级联 mall~~ ✅ | `products.py` mall-cascade-impact + ProductList.tsx | P1 | 1h | **done** |
| 5 | ~~mall 业务员绑错 employee 无"换绑"~~ ✅ | admin/salesmen.py rebind-employee | P2 | 1h | **done** |
| 6 | ~~ERP employee 停用后 mall 前端无友好提示~~ ✅ | miniprogram http.js 识别 detail | P2 | 30min | **done** |
| 7 | ~~行政区划仅河南 + 北京 smoke~~ ✅ | `seed_regions_national.py`（全国 34 省 + 地级市） | P1 | 1-2h | **done** |
| 8 | ~~热搜词 admin 管理页~~ ✅ | search_keywords.py + ERP 前端 SearchKeywords.tsx + migration m5a9 | P2 | 1h | **done** |
| 9 | ~~dismissed skip_log 阈值计算回归~~ ✅ | `scripts/e2e_skip_alert_threshold.py` | P1 | 30min | **done** |
| 10 | 9.8 跨月退货对 KPI 影响设计决策 | 业务决策 · 文档见 `business-decisions-pending.md` | P1 | 决策 + 0-1h 实现 |
| 11 | 6.4 settled commission 下月工资单处理 | 业务决策 · 文档见 `business-decisions-pending.md` | P1 | 决策 + 1-2h 实现 |
| 12 | ~~reversed commission 是否被下月工资单排除**回归**~~ ✅ | `scripts/e2e_reversed_commission_excluded.py` | P1 | 30min | **done** |

### P0 三项加起来 5-9 小时。做完即可上线。
### P1 七项加起来 7-11 小时。建议上线后一周内完成。

---

## 维护说明

- 本文件与 `business-atoms-mall.md` + `business-atoms-erp.md` 同步更新
- 新增业务动作须同时更新 E2E 状态
- gap 修完时把 🔴 改 🟢 并注明 commit hash
