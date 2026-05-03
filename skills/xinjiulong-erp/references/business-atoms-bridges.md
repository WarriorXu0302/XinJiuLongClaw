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

## 桥 4：库存 — ERP Inventory ↔ mall_inventory（支持跨端调拨）

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
| B4.5 | ~~ERP 调拨到 mall 仓不做~~ ✅ **已实现**：仓间调拨单（桥 11）覆盖 ERP↔ERP / ERP↔mall / mall↔mall 四种路径 | — | `WarehouseTransfer` | 🟢 |

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

## 桥 11：仓库调拨（跨 ERP + mall 的条码过户）

### 业务规则铁律

1. **品牌主仓**（`warehouse_type='main' AND brand_id IS NOT NULL`）**不参与调拨**——出入都禁。品牌主仓只能通过：
   - 采购订单（入库）
   - 销售订单 + 政策审批（出库）
2. 其他所有仓（ERP 非主仓 / backup / tasting / 所有 mall 仓）可以互相调拨
3. 每瓶必须扫厂家防伪码（条码过户，不允许按数量散装）
4. 所有商品**第一次入仓**都走采购订单；调拨是已入仓之后的仓间流转

### 数据模型

- `warehouse_transfers` 主单：`source_side/dest_side` ∈ {erp, mall} + 对应 warehouse_id（不建 FK，应用层+service 层校验）
- `warehouse_transfer_items`：每瓶一行（barcode + product_ref + cost_price_snapshot + batch_no_snapshot）
- 注意：**跨 side 时 warehouse_id 指向不同表**，所以主单不能对 warehouse_id 加 FK

### 状态机

```
pending_scan ─submit→ pending_approval ─approve→ approved ─execute→ executed
     │                       │
     │                       └─reject→ rejected（终态）
     └─execute（免审时直接）→ executed
     └─cancel→ cancelled（源端条码"软锁"自动释放）
```

### 审批策略

| 场景 | 是否审批 |
|---|---|
| ERP↔ERP 同品牌内（src.brand_id == dst.brand_id 且都非 None）| **免审**，直接 executed |
| 跨品牌 ERP↔ERP | **必审**（boss/finance）|
| ERP↔mall 跨端（双向） | **必审** |
| mall↔mall | **必审** |

### 执行粒度（四种路径）

| 源 → 目标 | 条码处理 | 库存处理 |
|---|---|---|
| ERP → ERP | `InventoryBarcode.warehouse_id` 改 | `Inventory` 源减目加 + `StockFlow` 双向 |
| ERP → mall | 源端 `InventoryBarcode` **DELETE** + 目标端 `MallInventoryBarcode` **INSERT**（同 barcode 字符串）| `Inventory` 源减 + `mall_inventory` 目加（加权平均） |
| mall → ERP | 反向；ERP 侧用虚拟 batch `TRANSFER-{transfer_no}`（因为 ERP 是按 batch 追溯，要给它造一个接盘 batch） | `mall_inventory` 源减 + 新建 `Inventory` 行（batch=虚拟） |
| mall → mall | `MallInventoryBarcode.warehouse_id` 改 | `MallInventory` 源减目加 + 加权平均 |

### 动作表

| # | 动作 | 角色 | 端点 | 副作用 | 状态 |
|---|---|---|---|---|---|
| B11.1 | 创建调拨单（扫码） | warehouse/boss/purchase | `POST /api/transfers` | 主单 + items；条码**不动状态**（靠"活跃 transfer 查重"软锁）| 🟢 |
| B11.2 | 提交审批 | initiator | `POST /api/transfers/{id}/submit` | status → pending_approval | 🟢 |
| B11.3 | 审批通过 | boss/finance | `POST /api/transfers/{id}/approve` | status → approved | 🟢 |
| B11.4 | 驳回 | boss/finance | `POST /api/transfers/{id}/reject` | status → rejected（终态） | 🟢 |
| B11.5 | 执行（真正过户）| warehouse/boss | `POST /api/transfers/{id}/execute` | 按四种路径分支；status → executed | 🟢 |
| B11.6 | 取消 | initiator | `POST /api/transfers/{id}/cancel` | status → cancelled | 🟢 |
| B11.7 | 品牌主仓拦截 | — | create 内校验 | `_is_brand_main_warehouse` → 400 | 🟢 |
| B11.8 | 审批中心 tab | finance/boss | 审批中心"仓库调拨待审" | 聚合 status=pending_approval | 🟢 |

### 软锁机制（避免跨事务锁）

同一条码不能出现在多个活跃 transfer 中（pending_scan/pending_approval/approved）。
通过 `_assert_barcode_not_in_active_transfer` 在 create 时查询拦截，cancel/reject/execute 后自然释放。
**不改 barcode.status**（避免污染 ERP 原有 LOCKED 语义），纯靠"transfer items + status 查询"的软锁。

### E2E 测试状态

🟢 `scripts/e2e_warehouse_transfer.py` 覆盖 4 种路径 + 品牌主仓拦截（源 + 目标）

### 🔴 剩余 gap

- **mall→ERP 方向要求 MallProduct.source_product_id 非空**：纯商城 SKU 没挂靠 ERP 产品时不能反向调拨。service 层已抛 400 指引，但业务上是否合理？P2
- **条码软锁 vs LOCKED 状态**：当前用活跃 transfer 查询实现软锁，没改 barcode.status。如果以后业务要做"调拨中库存冻结"报表，得另外 JOIN transfers。P2

---

## 桥 12：门店零售（专卖店收银系统）

### 业务场景
4 家品牌专卖店（青花郎专卖店 / 五粮液专卖店 / 华致名酒库 / 鑫久酒），店员用小程序收银，记账不在线收款。每瓶扫厂家防伪码出库，老板给售价区间，店员输入实际成交价（须在区间内），付款方式只记"现金/微信/支付宝/刷卡"四种不含赊账。

### 数据模型
- 门店 = ERP `warehouses.warehouse_type='store'`（新增枚举值）的仓——4 家店对应 4 个仓
- 门店商品清单 = 仓库当前有库存的所有 SKU（不另建映射表）
- 店员：`employees.position='cashier'` + `employees.assigned_store_id` 指向门店仓
  同步 `mall_users.assigned_store_id`（小程序端收银入口可见性判定）
- 售价区间：`products.min_sale_price` / `max_sale_price`（老板维护）
- 提成：`retail_commission_rates(employee_id, product_id, rate_on_profit)` 每员工×每商品一条
  → 提成 = (售价 - 成本) × rate_on_profit；成本用 `Inventory.cost_price`（按 batch 精确）
- 销售单：`store_sales` + `store_sale_items`（每瓶一行）+ `commissions.store_sale_id`

### 状态机
只有一个终态：`completed`。扫码即成交，不走审批（店员现场操作，没时间审批）。

### 原子动作表

| # | 动作 | 角色 | 端点 | 前置 | 副作用 | 状态 |
|---|---|---|---|---|---|---|
| B12.1 | 店员预校验条码（扫一瓶查商品 + 区间）| cashier | `GET /api/mall/workspace/store-sales/verify-barcode` | 小程序店员 | 返回 product + min/max_sale_price | 🟢 |
| B12.2 | 搜索客户 | cashier | `GET /.../store-sales/customers/search` | mall_users.user_type=consumer | 返回姓名 + 电话匹配的前 20 条 | 🟢 |
| B12.3 | **提交收银**（核心）| cashier | `POST /api/mall/workspace/store-sales` | 客户+扫码+售价+付款方式 | Inventory 扣 + Barcode OUTBOUND + StockFlow(retail_sale) + StoreSale + Commission pending | 🟢 |
| B12.4 | 店员查自己流水 | cashier | `GET /.../store-sales/my/sales` | — | 列表 | 🟢 |
| B12.5 | 店员查本月业绩 | cashier | `GET /.../store-sales/my/summary` | — | 销售额/利润/提成/瓶数聚合 | 🟢 |
| B12.6 | admin 查销售流水 | boss/finance/warehouse/hr | `GET /api/store-sales` + `/stats` | — | 全局看板 | 🟢 |
| B12.7 | admin 管理提成率 | boss/finance/hr | `/api/retail-commission-rates/*` CRUD | — | 决定收银能否提交 | 🟢 |
| B12.8 | admin 配售价区间 | boss | `PUT /api/products/{id}` 含 min/max_sale_price | — | 决定收银能否提交 | 🟢 |

### 收银流程校验链（提交时全跑）
1. 付款方式 ∈ {cash, wechat, alipay, card}
2. 门店仓 warehouse_type='store' + is_active
3. 店员 employees.status='active' + assigned_store_id 匹配当前门店
4. 客户 mall_users.user_type='consumer' + status='active'
5. 每瓶条码：存在 + 在本门店仓 + status='in_stock' + 去重
6. 每瓶售价 ∈ [product.min_sale_price, product.max_sale_price]
7. 门店库存足够（按 product_id + batch_no 聚合扣减）
8. 每个商品都有 `retail_commission_rates(cashier, product)` 配置（没配 → 400 指引管理员先配）

任一失败整笔回滚，不允许"扫一半"。

### 利润 / 提成口径
- **利润（按瓶）** = sale_price - Inventory.cost_price（按源 batch_no 精确）
- **提成（按瓶）** = 利润 × retail_commission_rates.rate_on_profit
- 一个销售单产生 **一条 Commission**（按店员聚合多瓶合计 commission_amount）
- Commission.store_sale_id 非空 + status=pending → 月结工资单自动纳入（payroll 扫描时加 or 条件）

### 桥 12 和既有桥的交互
- **桥 B11 仓库调拨**：门店仓不是品牌主仓，**可以**互相调拨 + 品牌主仓下游调入 + mall 仓互调
- **桥 B1 身份**：店员 mall_user 也必须 linked_employee_id 非空（复用 ERP 员工档案算工资）
- **桥 B7 通知**：目前不推送（收银实时完成，店员看小程序即知结果）

### E2E 测试状态
🟢 `scripts/e2e_store_sale.py` 覆盖 5 场景：正常闭环 / 售价越界 / credit 赊账拒 / 越权拒 / 无提成率拒
关键断言：StoreSale 金额 + StoreSaleItem + Commission pending + Inventory 扣减 + 条码 outbound + StockFlow 六处一致

### 🔴 已知 gap
- ~~**退货**：当前无店面退货流程~~ ✅ **已实现**：`StoreSaleReturn` + `StoreSaleReturnItem` 整单退，pending→approved/rejected→refunded 状态机，批准后 6 处一致性（原单 refunded / 条码 IN_STOCK / Inventory 回加 / StockFlow retail_return / Commission reversed / 退货单状态）。小程序店员从"我的业绩"发起，管理台审批中心新 tab"门店退货待审"审批。E2E `scripts/e2e_store_return.py` 覆盖 5 场景。
- **客户首次到店**：如果没注册过 mall_user，店员能不能临时建个客户？目前必须客户自己注册完才能买。P1 业务决策
- **条码来源 = 采购入仓或调拨入仓**：门店仓进货靠 B11 从品牌主仓调过来或 B6 采购直入。两条路径都支撑，但**店仓目前没进货接口前端**——桥 B6 的收货页已经能选 store 仓，但 B11 调拨的前端也行，所以不缺端点缺的是"从哪个品牌主仓货源搬来"的运营流程文档。P2

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
