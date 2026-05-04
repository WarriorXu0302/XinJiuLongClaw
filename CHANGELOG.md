# Changelog

所有值得记录的变更在这里追踪。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
本项目尚未开始语义化版本号（未发布 v1.0）。

<!--
维护规则（见 CLAUDE.md §16）：
- 每个合并到 main 的 PR **必须**在 Unreleased 节补一行
- 格式：`- [#PR 号] 一句话描述（动词开头）`
- 分类按改动主体：Security / Added / Changed / Fixed / Deprecated / Removed
- 发版时把 Unreleased 搬到新版本号 + 日期
-->

## [Unreleased]

### Fixed

- **P0**: payroll.generate_salary_records 漏扫门店零售提成（Commission.store_sale_id 非空那条路径从未进过工资单，店员辛苦扫码的提成永远发不出去）。
  改动（migration m6b3）:
  - salary_order_links 加 store_sale_id 列 + FK
  - 旧 CHECK（"order_id XOR mall_order_id"）改为"三者恰一个非空"
  - 新增 UNIQUE(store_sale_id, commission_id) 防同一门店提成重复入工资单
  - generate_salary_records 加 store_commission 扫描分支（同 mall 分支模式）
  - SalaryOrderLink 构造时传 store_sale_id
  - /pay-all 批量发薪时按 commission_id 统一 settled（覆盖 B2B/mall/store 三路径），不再只按 mall_order_id
  - E2E `scripts/e2e_store_commission_in_payroll.py` 验证 payroll 扫描能挂上门店 Commission

### Added

- **决策 #2 月榜快照 vs 实时双显**（migration m6c4） — 上月榜冻结不受退货影响
  - 新表 `mall_monthly_kpi_snapshot`（employee_id, period UNIQUE）冻结 GMV/订单数/提成
  - `services/mall/kpi_snapshot_service.py::build_snapshot_for_month(y, m)` ON CONFLICT UPSERT 实现幂等
  - APScheduler 新任务：每月 1 号 00:05 跑 `job_build_last_month_snapshot` 冻结上月
  - 新端点 `GET /api/mall/admin/dashboard/salesman-ranking?mode=snapshot|realtime&year_month=YYYY-MM`
  - 新端点 `POST /api/mall/admin/dashboard/salesman-ranking/build-snapshot?year_month=YYYY-MM`（admin/boss 手工回补）
  - ERP 前端 `Dashboard.tsx` 业务员排行卡片改双模式：实时/快照 Tab 切换 + 月份选择器 + 空快照一键冻结按钮
  - E2E `scripts/e2e_kpi_snapshot.py` 覆盖：冻结 → 退货 → 实时 vs 快照数据分叉 → UPSERT 幂等

- **G11/G12/G14/G15/G16/G17：业务员管理 + 退货并发 + 隐私加固（m6c6）**
  - G11：`/api/mall/workspace/store-sales/customers/search` 限制关键字 ≥5 字符 + 手机号脱敏 + 本店消费客户优先排序（原 2 字符会把全库手机号漏出去）
  - G12：`return_service.approve_return` + `store_return_service.approve_return` 加 `SELECT FOR UPDATE` 锁 `MallReturnRequest/StoreSaleReturn` + 源订单；migration m6c6 给 `commissions.adjustment_source_commission_id` 加 partial UNIQUE index（`WHERE is_adjustment=true`）DB 层兜底防双扣
  - G14：`update_salesman` 切 `assigned_store_id` 前检查店员 24h 内在途销售单 + 待审退货单，有则 409 拦；通过 `force_switch=true` 强切
  - G15：新 APScheduler job `job_notify_aged_pending_vouchers`（每小时 :15）扫 `PENDING_CONFIRMATION` 超 24h/48h → 推 admin/boss/finance；title 前缀 `[PAYMENT_AGING_24h]` 做幂等去重
  - G16：`/api/mall/salesman/my-customers` 列表手机号脱敏为 `138****1234`；新 `/my-customers/{id}/phone` 揭示完整号 + 写 `mall_customer.reveal_phone` 审计；miniprogram `salesman-my-customers.vue` 点拨号时才查号
  - G17：`disable_salesman` 释放 assigned 订单时同步通知客户"订单配送员变更"（与 `admin_reassign` 对齐）
  - E2E `scripts/e2e_return_approve_concurrency.py` + `scripts/e2e_salesman_mgmt_hardening.py`
  - 20/20 E2E 全绿

- **G4/G6：跨月退货追回透明化 + 业务员 commission 流水**
  - G4：`/api/payroll/salary-records/{id}/detail` 返回 3 个新字段
    * `clawback_details[]`：本月工资扫入的 is_adjustment 负数 Commission（含原订单号/原提成金额/原类型）
    * `clawback_settled_history[]`：本月结清的历史挂账
    * `clawback_new_pending[]`：本月工资不足扣减挂账到下月
  - G4：ERP 前端 `SalaryDetail.tsx` 新增"跨月退货追回扣减"卡片，三段式展示（本期扫入 / 结清历史 / 新建挂账）
  - G6：新端点 `GET /api/mall/workspace/my-commissions` 业务员自查流水，支持 status=all/pending/settled/reversed/adjustment 过滤 + year/month 筛选
  - G6：新端点 `GET /api/mall/workspace/my-commissions/stats?year&month` 返 by_status 四格 + adjustment 汇总
  - G6：miniprogram 新增"我的提成"页（`salesman-commissions.vue`），4 格汇总 + Tab 切换列表 + 追回单独标红显示原 commission
  - E2E `scripts/e2e_clawback_transparency.py` 覆盖 5 步：收银→settled→退货→追回建 adjustment→salary_detail/commission 查询验证

- **G3/G7/G9：看板利润卡 + 门店报表导出 + 快照批量回补**
  - G9：`/api/mall/admin/dashboard/summary` 返回 today/month 加 `revenue/profit/commission/gross_margin_pct`（聚合 profit_service）+ month 加 `bad_debt`
  - G9：ERP Dashboard 新增 4 个卡片（本月收入/净利润/毛利率/提成·坏账）
  - G3：`/api/store-sales/stats?group_by=store` 支持按店分组（每店一行 + 合计）
  - G3：`/api/store-sales/export` CSV 导出（带 UTF-8 BOM 支持 Excel 中文），字段：日期/单号/门店/店员/客户/瓶数/销售额/成本/利润/提成/毛利率/付款方式/状态
  - G3：门店销售页加「汇总 / 按店分组」Segmented + 「导出 CSV」按钮
  - G7：`/api/mall/admin/dashboard/salesman-ranking/build-snapshot-range?from_month=YYYY-MM&to_month=YYYY-MM` 批量回补端点
  - G7：Dashboard 排行榜卡片快照模式下加"批量回补"月份范围选择 + 一键按钮
  - E2E `scripts/e2e_dashboard_profit_export.py` 覆盖 3 项

- **审计三连 G1/G2/G8**（migration m6c5 FK 硬化） — 涉及金额/状态的写操作全部留痕
  - G8：`store_sale_service.create_store_sale` 加 log_audit（actor=cashier_employee_id）
    管理端 `/api/store-sales` 路由区分为 `store_sale.create_by_admin`（代下）
  - G1：`store_return_service` apply/approve/reject 三个分支全部加 log_audit（reason/金额/瓶数/refunded commissions/adjustment 数）
  - G2：`mall/return_service` apply/approve/reject/mark_refunded 四处加 log_audit
  - G10（顺手）：mark_refunded 金额与 approve 时不一致会单独记 `refund_amount_adjusted` 字段
  - migration m6c5：`audit_logs.actor_id/mall_user_id` FK 改为 `ON DELETE SET NULL`，员工/mall_user 被清理后审计记录仍保留不丢失
  - E2E `scripts/e2e_audit_coverage.py` 验证收银 + 三种退货状态变更的 audit_log 记录完整

- **决策 #4 商品销量双数据**（migration m6c3） — 区分"曾售卖"vs"净销量"
  - `mall_products.net_sales` 列新增（初始化 = total_sales）
  - `order_service.apply_post_confirmation_effects` + `housekeeping_service.close_partial_orders` 同步递增 total_sales + net_sales
  - `return_service.approve_return`（mall）增加 `net_sales = max(0, net_sales - qty)` 扣减逻辑
  - 首页榜单排序（`/api/mall/products?sort=hot`、`/api/mall/search/products`）从 total_sales 切到 net_sales
  - Schema `MallProductListItemVO` / `MallProductDetailVO` 导出 `netSoldNum`
  - 管理后台 `/api/mall/admin/products` 列表/详情返回 `total_sales + net_sales`；ERP 前端 ProductList 销量列改为"总/净"双显（净小于总时标红）
  - E2E `scripts/e2e_mall_product_net_sales.py` 验证单调递增/退货扣减/超额保底 0/再下单

- **决策 #3 门店散客支持**（migration m6c2） — C 端无会员的客户也能在门店买酒
  - `store_sales.customer_id` 改 nullable；新增 `customer_walk_in_name(100)` + `customer_walk_in_phone(20)` 选填快照
  - `store_sale_returns.customer_id` 同步 nullable（散客原单的退货）
  - `store_sale_service.create_store_sale` 接受 `customer_id: Optional`，散客路径不校验；walk_in 快照写入 StoreSale
  - ERP `/api/store-sales` + mall `/api/mall/workspace/store-sales` 收银接口 body 全部接受 `customer_id: Optional + customer_walk_in_name/phone`
  - 列表/详情 `customer_name` 展示优先走 `walk_in_name`，否则展示"散客"或"散客 ****1234"
  - 小程序收银页 `store-cashier.vue` 加"会员 / 散客"两个模式 Toggle，散客模式只需选填姓名手机号
  - E2E `scripts/e2e_store_walk_in.py` 覆盖散客下单 + 纯匿名 + 散客退货

- **决策 #1 跨月退货提成追回**（migration m6c1） — settled Commission 跨月退货走负数调整 + 工资不足挂账
  - `commissions` 加 `is_adjustment` + `adjustment_source_commission_id`
  - 新表 `salary_adjustments_pending`：当月工资不够扣时挂账下月扣（先进先扣）
  - `return_service.approve_return`（mall）+ `store_return_service.approve_return`（store）settled Commission 分支改为建一条负数 `is_adjustment=True, status=pending` Commission（幂等：source_commission 唯一）
  - `payroll.generate_salary_records`：1）先扣历史未结清挂账；2）当月仍负 → 实发 0 + 新挂账
  - E2E `scripts/e2e_cross_month_commission_clawback.py` 覆盖完整链路

- **门店退货（桥 B12 延伸）** — 客户来店退货的完整闭环
  - 新表 `store_sale_returns` + `store_sale_return_items`（每瓶一行快照）
  - 状态机：pending → approved/rejected → refunded（批准时一并执行）
  - service `store_return_service`：apply / approve / reject 三个动作
    * approve 时原子执行：条码 OUTBOUND → IN_STOCK + Inventory 回加 + StockFlow retail_return + Commission pending → reversed（已 settled 不追溯，只 notes 留痕）+ StoreSale.status = refunded（profit 自动排除）
    * 一单只能活跃退一次（409 防重）
    * 店员只能退本店单（403）
  - 后端：`/api/store-returns`（admin 列表/详情/审批）+ `/api/store-returns/pending-approval`（审批中心聚合）+ `/api/mall/workspace/store-returns`（店员小程序发起 + 查自己流水）
  - ERP 审批中心加 tab"门店退货待审"，一键通过/驳回
  - 小程序"我的业绩"每行加"申请退货"按钮（支持填原因）
  - E2E `scripts/e2e_store_return.py` 覆盖 5 场景：正常闭环 / 非本店店员拒 / 重复退货拒 / 批准后 6 处一致性（原单/条码/库存/流水/提成/退货单）
  - migration m6b2

- **门店零售收银系统（桥 B12）** — 4 家专卖店店员用小程序记账式收银
  - 新表 `store_sales` + `store_sale_items`（每瓶一行）+ `retail_commission_rates`（每员工×每商品一个利润提成率）
  - `products` 加 `min_sale_price/max_sale_price`（老板配售价区间）
  - `employees` + `mall_users` 加 `assigned_store_id`（店员归属）
  - `commissions` 加 `store_sale_id`（零售提成挂靠，和 order_id/mall_order_id 三者互斥）
  - `WarehouseType` 枚举加 `STORE` + 补 `TASTING`（原漏写）
  - 后端 service `store_sale_service.create_store_sale`：扫码 + 售价区间校验 + 客户校验 + 逐瓶算提成 + 生成 Commission pending，整笔回滚保证一致性
  - 端点：`/api/store-sales`（admin 列表/统计/详情/创建）+ `/api/retail-commission-rates`（提成率 CRUD）
  - 小程序店员端：`/api/mall/workspace/store-sales`（扫码校验 + 提交收银 + 查自己流水/本月业绩 + 搜索客户）
  - 付款方式限定：cash/wechat/alipay/card（DB CheckConstraint 强制，不允许赊账）
  - ERP 管理台新菜单组"门店"：门店管理 / 销售流水 + 统计 / 店员提成率
  - 小程序工作页加"门店收银"+"门店业绩"入口（仅 `assigned_store_id` 非空店员可见）
  - 小程序登录响应补 `assigned_store_id` 字段，前端据此渲染入口
  - migration m6b1

- **仓库调拨（桥 B11）** — 跨 ERP + mall 的条码过户
  - 新表 `warehouse_transfers` + `warehouse_transfer_items`（每瓶一行），migration m6a1
  - 业务规则：品牌主仓（`warehouse_type=main AND brand_id NOT NULL`）**出入都禁**；只能通过采购单入 + 销售订单出。其他仓（ERP 非主 + 所有 mall）互相可调拨
  - 审批策略：ERP↔ERP 同品牌内免审直接 executed；跨品牌 / 涉 mall / 跨端必审（boss/finance）
  - 扫码粒度：每瓶必扫厂家防伪码，条码软锁（活跃 transfer 查询实现，不改 barcode.status）
  - 执行四种路径：ERP→ERP（条码改 warehouse_id）/ ERP→mall（条码 DELETE + mall 端 INSERT）/ mall→ERP（反向，ERP 用虚拟 batch 接盘）/ mall→mall
  - 端点：`POST /api/transfers` + `/submit` `/approve` `/reject` `/execute` `/cancel` + `GET /` `GET /pending-approval` `GET /{id}`
  - ERP 前端：`/inventory/transfers` 列表 + `/inventory/transfers/new` 扫码新建 + 审批中心新 tab "仓库调拨待审"
  - E2E `scripts/e2e_warehouse_transfer.py` 覆盖 4 种路径 + 品牌主仓拦截
  - 权限索引：所有 `source_side/dest_side` + `status` 有索引，活跃 transfer 软锁查询不扫表

- 业务员"我的订单"在途 Tab 现在同时显示 `assigned` + `shipped` 两个状态（原仅 assigned → 导致已出库未送达的单消失）。后端 `/api/mall/salesman/orders` 的 `status` 参数支持逗号分隔多值
- 三份业务原子化文档 `skills/xinjiulong-erp/references/business-atoms-{mall,erp,bridges}.md`：按业务流切原子动作，标注 E2E 测试状态与全局 🔴 gap 汇总
- `GET /api/products/{id}/mall-cascade-impact` + `PUT /products/{id}?cascade_mall=true` — ERP 下架商品时提示挂靠的 mall_products 数量，可选同步下架；前端 ProductList 增加"下架/启用"按钮，有影响时弹确认框
- 桥 B6.2（mall 仓收货 + ship 扫码）**正确修法**：白酒业务硬要求每瓶扫厂家防伪码，之前"散装 bulk 路径"思路废弃并回滚
  - `POST /api/purchase-orders/{id}/receive` 改为 body 入参；mall 仓路径**必传** `barcodes_by_item = [{item_id, barcodes: [...]}]`
  - 每 PO item 条码数必须精确等于应入瓶数；全局 UNIQUE（同厂家码不能入库两次）+ 本次内去重；通过后生成 MallInventoryBarcode × N 行（每瓶 status=in_stock）
  - `ship_order` 强化：`scanned_barcodes` 缺失直接 400（原宽松兜底逻辑改为硬校验）
  - ERP 前端 `ReceiveScanPage.tsx` 重写：按 PO item 分组扫码（点击切换当前目标） + 进度 `got/expected` 可视化 + 所有 item 扫满才能提交 + Excel 批量导入到当前 item；删除"mall 仓快捷入库"错误分支
  - 前端 PurchaseOrderList 删除"一键收货"快捷按钮，收货一律走扫码页
- `PUT /api/mall/admin/salesmen/{id}/rebind-employee` — 管理员换绑业务员的 ERP 员工，校验 active + 未占用 + 无在途订单 + bump token_version；ERP 前端 SalesmanList 加"换绑员工"按钮
- 热搜词 admin 管理：`mall_hot_search_keywords` 表 + `/api/mall/admin/search-keywords` CRUD + ERP 前端 `/mall/search-keywords` 页；`/api/mall/search/hot-keywords` 改读 DB（硬编码 5 个词降级为 fallback）
- `backend/app/scripts/seed_regions_national.py` — 全国 34 省/自治区 + 全地级市/自治州 level 1+2 行政区划 seed（区县仍由 `seed_regions_henan.py` 分省补）
- E2E 脚本三枚 · `scripts/e2e_mall_partial_close.py`（桥 B3.5 坏账路径）· `scripts/e2e_full_mall_flow.py`（注册→下单→ship→deliver→凭证→确认→退货 10 步贯通）· `scripts/e2e_skip_alert_threshold.py`（dismissed 排除阈值）· `scripts/e2e_reversed_commission_excluded.py`（工资单过滤回归）
- `skills/xinjiulong-erp/references/business-decisions-pending.md` — 跨月退货/提成追溯的业务现实梳理，给 openclaw 飞书智能体回答老板问题用
- 权限隔离索引补齐（migration m5b1）：`mall_users.linked_employee_id` UNIQUE partial(user_type=salesman) 保证"一 employee 一 salesman 账号"· `mall_inventory_barcodes(sku_id,status,warehouse_id)` 复合 · `commissions(employee_id,mall_order_id,status)` partial 覆盖工资单扫描

### Fixed

- mall http.js 识别后端"您绑定的 ERP 员工已停用"detail，改为弹模态 + 清 token + 跳登录页（之前靠通用 401 链路，体验差且没提示）
- `order_stats` 过滤 `consumer_deleted_at IS NULL`（软删订单不进角标计数）+ partial_closed 归入 payed 分组（原先在任何计数里都看不到）
- `register_mall_user` 移除 IntegrityError 后的冗余 `db.rollback()` —— 原行为会提前释放 FOR UPDATE 锁，让并发注册抢同一张邀请码
- `auth/register` + `auth/wechat_register` 补 `mall_user.register` 审计（含 IP、推荐人、注册方式）
- `adjust_barcode_damaged` 严格校验 inventory 行存在且 quantity ≥ 1，原先 `max(qty-1, 0)` + `inv=None` 时流水 `inventory_id=NULL` 静默埋孤儿记录
- 加购（cart）+ 下单（order_service.preview/create）三处都加 `MallProduct.status='on_sale'` 校验，避免整品下架但 SKU 未同步下架时漏网
- workspace expense/leave/inspection 都补 `Employee.status='active'` 校验（离职业务员不能提报销/请假/稽查）
- expense 加 `claim_type` 枚举校验 + `f_class` 必须带 brand_id + 提交审计
- `job_detect_partial_close` 不再写 `order.completed_at`（原写法导致后续 manual_record 真正全款时间被 `if not` guard 保留成折损时刻）；`manual_record` 全款恢复时**始终**覆盖 `completed_at`
- `job_detect_partial_close` 新增给 assigned + referrer 推"订单坏账关单"通知
- `job_notify_archive_pre_notice` 加幂等去重（过去 8 天已发过同标题通知就跳过），防定时任务重跑/手动触发时重复推送
- `create_order` 校验 `cost_price_snapshot` 非空，两头都没成本时抛 409 拒绝下单（避免利润台账按 0 成本算虚高）
- `add_collection` 校验 `MallProduct.status='on_sale'`（草稿/下架商品不允许收藏）+ IntegrityError 不手动 rollback 改抛 409
- `admin_cancel` 多处修复：(1) 退库存按原出库 flow 定位目标仓（原按默认仓错误）(2) `prev_status` 审计被覆盖后的值（bug，永远记 cancelled）(3) `restocked_quantity` 与 `barcodes_reverted` 拆开 (4) FOR UPDATE 锁订单防与业务员 ship/deliver 并发
- miniprogram `login.js` refresh token 竞态：并发请求碰到正在刷新时直接 return 让后续用旧 token → 改用模块级 Promise 合并所有并发的 refresh，等同一个结果
- `enable_salesman` 恢复 `is_accepting_orders=True`（原 disable 时关了但 enable 不开 → 启用后是僵尸账号）
- `claim_order` 校验 `is_accepting_orders` + `linked_employee_id`：关了开关不能自抢；没绑员工不能抢（与 admin_reassign 一致）
- `appeal_skip_alert` reason 限长 1-500 + `resolve_skip_alert` 通知业务员裁决结果（resolved / dismissed 都推）
- kpi `_calc_mall_actual` 排除 `refunded`（原仅排 cancelled → 退款订单仍被算销售）
- salesman `stats` + admin `dashboard` 业务员/商品排行：`partial_closed` 订单按 `delivered_at` 落窗口（原用 completed_at，但前轮修完后该字段对 partial_closed 留空 → 新数据从统计里消失）
- `profit_service` 同上：利润台账时间窗口对 partial_closed 改走 `delivered_at`，避免老板看月度利润少一块坏账
- `admin_reassign` 补通知消费者"配送员已变更"（之前只通知新旧业务员；消费者可能已加原业务员微信，突然换人不告知）
- `resolve_skip_alert` 推送业务员裁决结果通知 + `appeal_skip_alert` reason 限长 1-500
- `create_leave`（mall workspace）补提交审计 + leave_type 枚举校验
- `create_case`（mall inspection）补提交审计 + barcode|qrcode 至少一项 + quantity > 0 校验
- mall 打卡复用 ERP 的 `_get_rule_for_employee` + `_haversine`：统一**地理围栏 + 迟到判定规则**（原 mall 硬编码 9:10、无围栏，导致业务员走 mall 绕过工资制度）
- mall 拜访离店判定统一用 `_get_rule_for_employee`（原 `select(AttendanceRule).limit(1)` 随便拿一条，个人规则失效）
- 凭证被驳回通知文案用 `order_no`（原 `p.order_id` UUID，业务员看不懂）
- admin dashboard `low_stock_count` + `low_stock` 列表过滤下架 SKU/商品（原把下架商品当告警虚增工作量）
- admin 作废邀请码 + 换绑推荐人补通知：老/新业务员都要被告知推荐关系变动（影响提成归属）
- `disable_warehouse` 前置校验：仓内有库存或在途订单时拒绝禁用（避免库存挂空 / 退货找不到原仓）
- **小程序 C 端订单列表 UI 全错**：orderList.vue 用 `item.status==1/2/3/5/6`（数字）比较，但后端返字符串 → 所有订单都显示"已取消"；字段用 `orderNumber`/`orderItemDtos`/`actualTotal` mall4j 老协议，后端返 `orderNo`/`items_brief`/`payAmount`。重写 UI + 状态映射（覆盖 8 个 status 和 partial_closed/refunded）；detail 页"删除订单"按钮同样问题已修
- 小程序 `list_my_orders` 后端支持逗号分隔多值 status（与业务员端一致）；orderList tab "已完成" 合并 `completed + partial_closed`、"已取消" 合并 `cancelled + refunded`
- `user.vue` 首页订单角标映射错位：原 `payed`（已完成）显示在"待发货"位置，改显示在"已完成"位置
- `preview_order` 返回 items 字段对齐驼峰 alias（`prodId/skuId/prodName/skuName/count/price/subtotal`），让 submit-order + order-detail 用同一套字段读取（原 snake_case 让 submit-order 的 `item.prodName`/`prodCount` 读不到）
- `submit-order.vue` 下单时 `addrId` 兼容 `id`（preview 返的 address snapshot 字段是 `id`，老地址对象是 `addrId`）
- `order-detail.vue` 商品数量模板改读 `count` 优先（VO serialization_alias="count"），原读 `prodCount` 永远为空
- `order-detail.vue` 地址栏 `userAddrDto.area` 重复渲染两次，删掉重复
- **`parsePrice`（wxs/number.js）**：后端 Decimal 序列化为字符串，前端 `.toFixed()` 直接崩。加 `Number()` 转换 + NaN 兜底（影响全站所有价格展示）
- `prod.vue` 商品详情轮播图 `data.imgs.split(',')` 崩（后端返数组，老协议返逗号字符串）→ 兼容两种格式
- `prod.vue` groupSkuProp 多 SKU 时 `properties.split` 崩（后端无 properties 字段）→ 加兜底，无 properties 跳过
- 首页 + 商品详情：价格为 null（未绑推荐人）时显示"联系业务员获取价格"，原状态整块空白
- 加购接口补**消费者必须已绑定推荐人**校验（与 create_order 一致），避免加购后下单 403 的破 UX
- **业务员订单详情多处字段错位**：`total_amount / shipping_fee / discount_amount / pay_amount` + 时间线 6 个节点（created_at/claimed_at/...） + item 字段（prod_name/sku_spec/quantity）全按 snake_case 读，后端序列化为驼峰 → 全显示空；兼容两种命名
- `onCall` 拨号读 `order.customer_phone`（不存在字段）→ 改读 `address.mobile`
- 业务员凭证上传补 `size / mime_type`（后端 schema 支持但前端漏传）
- **`salesman-alerts.vue` 客户/申诉字段全错**：`a.customer_nick` → `a.customer?.nickname`，`a.customer_phone_mask` → `a.customer?.masked_phone`；移除后端不返的 `first_at/last_at/logs`，改展示 `appeal_reason` + `resolution_note`
- **`salesman-attendance.vue` 月汇总字段完全不匹配**：前端读 `late_count/absence_count/visit_count/valid_visit_count`，后端返 `late_times/late_over30_times/leave_days/valid_visits/is_full_attendance`；重写 5 个格子对齐后端口径
- **`salesman-kpi.vue` 结构不匹配**：前端期望 `{target,actual,completion}` 嵌套，后端返扁平列表 `[{sales_target, actual_sales, sales_completion, ...}]`；重构前端按列表首项展示
- 业务员邀请码：后端 create 返回补 `remaining_today`，history 批量 join 出 `used_by_nick`（被谁使用的昵称）— 原前端模板引用的字段后端完全没返
- `salesman-checkin.vue` 客户地址字段 `pickedCustomer.address` → `contact_address`（后端返 `contact_address`）
- `salesman-expense.vue` 列表项时间格式化用 `relativeTime`（原直接渲染 ISO 字符串）
- 公告路由过滤 `publish_at > now` 的未来公告（原状态=published 就立即展示，直链可泄漏预发内容）
- `ship_order` 补通知消费者"订单已出库"（原只记审计不推通知，用户要自己查状态）
- `create_salesman` (admin) 移除冗余 `db.rollback()`（和 C 端 register 同样的事务 bug）
- `confirm_receipt` 放宽状态：`delivered / pending_payment_confirmation / completed / partial_closed` 都允许点确认收货（原仅 delivered，客户晚点点会 400）
- ERP 前端 `OrderList` + `SkipAlertList` 支持 `?status=xxx` URL 参数（从 Dashboard 点击跳转时自动选中对应 Tab）
- 购物车接口返回 `is_available` 标记下架商品；前端 basket 展示"已下架"红色标签 + 禁用勾选 + 结算自动跳过 + 合计不计入下架商品
- 业务员收款码上传实装：miniprogram profile 页菜单用 `uni.showActionSheet` 选微信/支付宝、拍照/相册上传、支持清空；`attachments` 端点新增 `payment_qr` kind
- `workspace/customers` 过滤 `status=active`：业务员打卡/拜访客户选择器不再显示停用/归档客户
- admin OrderDetail 抽屉补展示**收款凭证图**（expandable 行展开）和**送达照片**（物流区下方九宫格）；后端补返 `payments[*].vouchers` + `delivery_photos`
- **邀请码 H5 二维码**：后端 `/salesman/invite-codes` POST 返 `qr_svg`（SVG 字符串）+ `deeplink`；前端 H5 `v-html` 渲染，mp 端展示链接文本兜底
- **邀请码小程序码（扫码一键注册骨架）**：后端 `wechat_service.py` 封装 access_token 缓存 + `wxacode.getUnlimited`；新端点 `GET /invite-codes/{id}/qr-mp` 返 PNG；小程序新页 `register-by-scan` 解析 scene → `uni.login` → `/wechat-register` 完成注册；salesman-invite 加"下载小程序码"按钮（mp-weixin 编译条件）；onShareAppMessage 分享路径改为 `register-by-scan?invite_code=...`。**未配 MP_APPID 时返 1x1 占位 PNG 走 mock**，等生产 AppID 到位即可联调
- `wechat_register` 对已注册 openid 不再 409，直接当登录处理（不消耗邀请码）。前端 register-by-scan 移除 409 降级二次 uni.login 路径，新老用户走同一个按钮体验一致
- `register.vue` 兼容三种邀请码 query 参数：`?code=`（老链接）/ `?invite_code=`（分享卡片）/ `?scene=`（小程序码），分享/扫码/历史链接共用同一注册页
- `salesman-invite.vue` 历史记录时间格式化为 `YYYY-MM-DD HH:mm`（原直接渲染 ISO 字符串）
- **accountLogin.vue 加微信一键登录按钮**（mp-weixin 专用）：`uni.login` → `/wechat-login`；已注册→直接登录并按 user_type 分流到 consumer/salesman 首页；404 未注册→引导"扫业务员邀请码注册"
- **register.vue 加顶部 tab 切换微信/账密注册**（mp-weixin 默认微信）：微信注册 = 输邀请码 + uni.login + `/wechat-register`；账密注册 = 用户名密码 + 邀请码 + `/register`；两种方式都强制校验邀请码
- **C 端注册走审批流**（重要变更）：
  - `mall_users` 加字段 `application_status / real_name / contact_phone / delivery_address / business_license_url / rejection_reason / approved_at / approved_by_employee_id`（migration m5a5）；业务员账号 default='approved' 跳过审批
  - 注册 `/wechat-register` 必填姓名/电话/配送地址/营业执照 URL，**不签发 token**，返 `{application_id, application_status}`；通知 admin/boss 待审批
  - 新建 `/api/mall/public-uploads/upload` 匿名上传端点（kind=business_license 白名单，单 IP 5 次/分钟限流）
  - 登录端点对 `application_status != approved` 消费者返 403 `{reason, application_id, application_status, rejection_reason}` 让前端跳"审批中"页
  - `/application-status?application_id=` 匿名查询端点供 pending 页 10s 轮询
  - ERP 管理台 `/api/mall/admin/user-applications` 列表/详情/approve/reject；驳回自动作废邀请码 + 推驳回通知
  - 小程序新 `pages/pending-approval` 轮询页；`register-by-scan` 改为跳 register 填资料；register 页加姓名/电话/配送地址/营业执照 4 个必填字段
  - ERP 前端新菜单"注册审批"（`/mall/user-applications`）+ 详情抽屉看营业执照 + 通过/驳回按钮
- **C 端账号必绑微信**：register.vue 重构为仅微信注册（移除账密 tab，品牌卡片 UI + 邀请码锁定卡 + 必填资料表单 + 绿色微信 CTA）；配送地址拆到独立 `pages/register-address-picker`（3 列省市区 picker + 门牌号 textarea，`getCurrentPages` 回写主页）；后端对应删除 `/api/mall/auth/register`（账密注册端点）+ `MallRegisterRequest` schema。业务员账号由 ERP 后台 `/api/mall/admin/salesmen` 创建，不受影响
- register.vue 邀请码支持手动输入：URL 带 `?code=/?invite_code=/?scene=` 时锁定显示；手动打开注册页时允许用户输入（统一转大写）。原先没入口导致直接打开页面没地方填邀请码
- 新建 `scripts/seed_regions_henan.py`：导入河南省完整三级行政区划（1 省 + 18 地市 + 156 区县，共 175 条），原 `mall_regions` 只有 4 条北京 smoke test，picker 只能选北京
- dev H5 下 `uni.login` 返的 code 每次随机 → mock openid 跟着变 → 注册后再登录永远 404。后端 `wechat_code2session` 支持 `devmock:<openid_suffix>` 前缀（未配 MP_APPID 时）固定返回同一 openid；前端 accountLogin 加 DEV 调试面板（仅 H5 dev 可见）设置/清除 `devMockOpenid`；register 页也读取同一值，注册/登录在开发环境复用同一个微信身份
- accountLogin 的"微信一键登录"按钮去掉 `#ifdef MP-WEIXIN` 限制，H5 dev 也能看见（真机走 uni.login，dev H5 走 mock）
- 注册时填的配送地址没进 `mall_addresses` 表 → 审批通过登录后"我的地址"空白。`register_mall_user` 现在同步建一条 is_default=True 的 MallAddress（含省市区 codes）；register.vue 把 picker 返的 address_parts 一起发给后端。老数据用临时 SQL 回填
- `disable_salesman` 加级联：assigned 状态订单自动释放回 pending_assignment（记 claim log）；shipped/delivered/待确认订单返 `in_progress_orders_need_reassign` 给 admin 提示手动改派。原先禁用业务员时在途订单无人负责 / 业务员端仍能看到
- 消费者的推荐业务员被禁用时 `create_order` 直接 403 拒绝下单（原先订单进 pending_assignment 但独占期内没人能看到 → 开放期才被其他业务员抢）
- 业务员登录（账密 / 微信 / refresh）新增 `assert_salesman_linked_employee_active` 校验：linked ERP employee 的 status != 'active' 时直接 403，防离职业务员继续通过 mall token 刷 ERP 复用端点
- `reject_application` 释放 openid / username 唯一键（改 `rejected_<ts>_` 前缀），否则被驳回用户无法用同一微信/账号重注册，测试环境里尤其堵
- 业务员订单详情（salesman-order-detail）展示凭证列表 + 驳回原因 + 重传按钮文案切换：后端 `MallOrderDetailVO` 补 `payments` 字段；delivered 状态下有 rejected 凭证时按钮文案改成"重新上传收款凭证"。原先业务员不知道凭证被驳回为何/下一步做什么
- `salesman-my-customers` 加一键拨号 + 导航按钮；后端返完整 `contact_phone`（注册留的电话，原只返脱敏）+ `default_address`（默认收货地址）。业务员跟客户对接/送货时不用手工输地址
- admin `change_referrer`（换绑推荐人）补通知消费者本人："您的业务员已调整 XXX"。原先只通知了新老业务员，C 端用户完全不知道自己推荐人被换了
- **采购跨仓**（P0）：`purchase_orders` 加 `target_warehouse_type`（'erp_warehouse'/'mall_warehouse'）+ `mall_warehouse_id`（migration m5a6）；`POST /api/purchase` 接受 `target_warehouse_type=mall_warehouse + mall_warehouse_id` 创建入商城仓的 PO；`receive_purchase_order` 按 target 分支到 `mall_inventory` + 加权平均成本 + MallInventoryFlow 流水。前提：ERP 商品必须有对应 `MallProduct`（source_product_id 映射），没有会拒绝并提示先建商城商品
- **定时任务执行历史**：`MallJobLog` 表（migration m5a7）+ 装饰器 `_with_job_log` 包裹所有 `job_*`（unclaimed_timeout / archive_inactive / pre_notice / partial_close / purge_login_logs），每次执行落条记录（started/finished/duration/status/result/error）。admin 端新端点 `GET /api/mall/admin/housekeeping/logs` + `/logs/summary`（按 job_name 取最近一次），看 dashboard 能知道定时任务是否真的跑了
- **C 端通知中心**（之前的 gap）：`notify_mall_user` 后端一直在发但 C 端用户没入口看。新建 `pages/notifications/notifications`（复用 `/api/mall/workspace/notifications` 通用端点），个人中心加"消息通知"菜单项 + 未读角标（红色数字 badge），点击通知按 entity_type 跳转（MallOrder/MallReturnRequest/MallPayment/MallUser）
- admin ConsumerDetail 补 3 个 tab：审批资料（含营业执照大图 + 真实姓名电话配送地址审批状态）+ 退货记录（状态+原因+退款金额+时间）；后端 `GET /mall/admin/users/{id}` 返回 `application` + `returns` + `returns_count` 字段。原先 admin 想看 C 端真实姓名只能翻注册审批列表
- admin `GET /mall/admin/salesmen/{id}` 返回 stats：completed_order_count / total_gmv / in_progress_order_count / referred_customer_count / open_skip_alerts。前端暂未接，后端 API 先就位
- 地址删除时如果删的是默认地址，自动把最早的剩余地址提为新默认（原本是删掉就没默认了，下单时 preview 拿不到地址报错）
- skip_log 处理自买单边缘：业务员自己给自己下单后被 release / admin_reassign / timeout，都不记 skip_log（原逻辑会污染自己的跳单告警统计）
- ERP admin 前端补 4 个一直缺的管理页面：
  - `/mall/housekeeping-logs` 定时任务（summary 卡片 + 执行历史，能看每个 job 最后执行的状态 / 耗时 / 结果，点"手动触发"可直接跑）
  - `/mall/warehouses` 商城仓库（列表 + 新建 + 编辑 + 禁用启用，管理员下拉从业务员池选）
  - `/mall/inventory` 商城库存（按仓库/SKU 查询，低库存标红，加权平均成本展示）
  - `/mall/notices` 店铺公告（草稿/已发布 tab + CRUD + 发布/撤回）
  以上端点后端一直都有但前端没 UI，admin 以前只能靠 curl 用这些功能
- PurchaseOrderList 列表加"入库仓"列：ERP/商城 两类仓 tag 化展示 + 商城仓名字从 mallWarehouses 反查
- ReceiveScanPage 区分 mall 仓 PO：
  - 选 mall PO 时显示黄色 Alert "商城仓按 SKU 总量入库，无需扫码"
  - 扫码区替换成"直接入库"按钮
  - success 消息按仓类型分别展示
- 商城订单列表（admin）加"已折损"和"已退货" tab（原先这两种状态找不到）
- salesman `stats` 端点修复：Commission `status=reversed`（退货冲销）原被错误算进 `pending`，现在独立返 `month_commission_reversed` 字段；小程序业务员 profile 加"退货冲销"红底卡片展示
- admin 改派订单下拉智能化：`_helpers/salesmen` 端点补返 `is_accepting_orders / has_linked_employee / in_progress_count / open_alerts`，按"可接单 + 绑员工 优先 → 在途订单少 → 告警少"排序；前端下拉展示 3 个 tag（接单中/未开放/告警数），选中后有问题会黄色警告提示
- 跳单告警申诉时通知 admin/boss（notify_roles）—— 原先业务员申诉后 admin 无提示，申诉沉没；现在新申诉进通知中心后 admin 一眼看到
- 通知点击直跳订单详情：reject_payment / return 3 处通知都改 `entity_type=MallOrder + entity_id=order.id`，`workspace/notifications` 响应补 `related_order_no`（反查 MallOrder.id → order_no），C 端点通知用 order_no 直跳 orderDetail 而非兜底订单列表
- 微信登录失败也记审计（原只有账密登录失败有），admin 追溯用户"登不上"问题有线索：openid 未注册 / disabled / archived / pending / 驳回 / 员工离职全覆盖
- 前端采购单 UI 加目标仓库类型切换：Radio 切 ERP 仓 / 商城仓，切商城仓时下拉列出 mall_warehouses；createMutation 按 target_warehouse_type 互斥传 warehouse_id 或 mall_warehouse_id。`/api/mall/admin/warehouses` GET 角色放开 purchase（采购员录入 PO 时选商城仓用）
- **C 端退货流程**（P0 完整落地）：新表 `mall_return_requests`（migration m5a8）+ `MallReturnStatus` 枚举（pending/approved/refunded/rejected）+ `return_service.py`（apply/approve/reject/mark_refunded）。后端接口：
  - C 端 `POST /api/mall/orders/{order_no}/return` 申请退货（completed / partial_closed 可申，同订单最多一条活跃申请）
  - C 端 `GET /api/mall/orders/{order_no}/return` 查状态
  - Admin `GET /api/mall/admin/returns` 列表（4 tab：待审批 / 已通过待退款 / 已退款 / 已驳回）
  - Admin `POST /{id}/approve` 批准：退库存（反向 MallInventoryFlow.IN）+ 订单→refunded + pending commission→reversed
  - Admin `POST /{id}/reject` 驳回（通知消费者）
  - Admin `POST /{id}/mark-refunded` 线下退款打款完成后标记（refund_method + 通知消费者）
  - ERP 前端新菜单"退货审批"（`/mall/returns`）：详情抽屉含订单明细、退款金额可调、审批/驳回/标记完成按钮
  - 通知齐：申请时通知 admin/boss/finance；批准时通知消费者 + 配送业务员；退款完成时通知消费者
- `cancel_order` 退库存按原出库流水的 inventory 定位目标仓，不再依赖 `get_default_warehouse()`。**修复**：默认仓换过后，取消订单会把货退到错的仓
- `release_order` 仅允许在 `assigned` 状态释放；`shipped` 后条码已 OUTBOUND 绑定原业务员，不再允许自行释放（出库后须走管理员改派）
- `admin_reassign` 在 shipped/delivered/pending_payment_confirmation 状态改派时，同步把本订单的 OUTBOUND 条码 `outbound_by_user_id` 过户到新业务员，避免归属数据错乱
- `post_commission_for_order` 改为**按当前 received_amount 计算差额**：partial_closed 订单先按已收额计过提成，再被 manual-record 补款恢复 completed 时，会追加一条"补发差额"commission。原逻辑的 `order.commission_posted` 一旦 True 就跳过，导致 top-up 永远不发
- `salary_order_links` 加 `commission_id` 列 + 唯一约束改 `(mall_order_id, commission_id, is_manager_share)`；`generate_salary_records` 按 commission_id 幂等去重、`pay_salary` 按 commission_id 精确结算。**修复**：同一 mall_order 的 top-up commission 原会被 `(mall_order_id, is_manager_share)` 老约束挡在第二次工资单之外

### Changed

- 小程序邀请码申诉模态改用 `uni.showModal editable=true`（跨端最稳的输入方案），注释标明决策；原"TODO 正式版加富文本"误导后续维护者
- 通知页 `jumpByEntity` 路由到 MallOrder / MallSkipAlert / MallPayment 对应页面（原 TODO 占位）
- 审计中间件 `audit_request_middleware` 用 ContextVar 自动注入 IP：68 个 `log_audit(...)` 调用点无需改签名即拿到真实 IP（X-Forwarded-For 优先）
- profit_service 增加 `mall_bad_debt` 科目：partial_closed 订单的未收部分按 item 比例切分到 brand；`/api/dashboard/profit-summary` 独立展示"商城坏账"行

### Removed

- 删除 4 个 mall service dead stub（actor_context / attachment_service / notification_service / skip_alert_service）—— 实际业务逻辑已在 `order_service.py` 和 `attachments.py` 路由内联实现，占位文件误导读者
- 删除 5 个 mall schema dead stub（admin / payment / salesman / shipment / common）—— 实际 Pydantic 模型散落在 auth/order/product 等具体 schema 文件
- 删除 10 个 ERP 前端 mall 未挂载占位页（SkuList / Warehouse 系列 / SalesmanCreate / SalesmanImport / ReferrerManagement / NoticeList / HotSearchList），均未在 router 注册，删除避免未来误以为还有未完成工作

### Security

- [#6] POST `/api/uploads` 补加 CurrentUser 鉴权，防未登录滥用上传（修 health-check S1）
- [#6] 文件名改用完整 UUID（2^128 枚举空间），去掉用户原文件名防业务名可预测爆破
- [#6] 飞书服务间密钥比较改 `hmac.compare_digest`，防时序攻击（M7）
- [#6] JWT decode 异常消息通用化，不再泄露 `"exp claim has expired"` 等细节（L1）
- [#6] 审计日志 `open_id` 由前 8 字符明文改成 sha256 hash，防指纹定位个人（L2）
- [#9] 给 8 张带 brand_id 的表补 RLS 品牌隔离策略（purchase_orders / financing_orders / expense_claims / receivables / policy_templates / brand_salary_schemes / policy_usage_records / tasting_wine_usage，修 health-check S3 的 8/11）
- [#10] 给 4 张表补 RLS：customer_brand_salesman + customers（多对多反查）+ sales_targets（按品牌/层级隔离）+ policy_claims
- [007b14a] **严重修复**：补齐 12 张核心表（orders/receipts/payments/accounts/fund_flows/salary_records 等）的 RLS policy。原 migration a1b2c3d4e5f6 因部署流程走 `stamp head` 从未真正应用，导致业务员自部署起就能看到 master 总资金池金额、所有品牌订单等跨品牌数据
- [007b14a] POST /api/receipts 业务员不再直接动账，走"上传凭证 → 待财务审批 → 确认后才入账"流程（P2c-1，按用户 D3 决策）

### Added

- **M4d Mall 月结对接**：`salary_order_links` 加 `mall_order_id` + `CHECK(order_id xor mall_order_id)`；`generate_salary_records` 追加 mall pending commission 聚合段（按已有 SalaryOrderLink 幂等挡重复）；"纯 mall 业务员"（无主属品牌 scheme）特例：底薪/全勤 0，仅发提成；`pay_salary` / `batch_pay_salary` 同步把 commission.status='pending'→'settled' + settled_at；mall 业务员同步收到"本月 X 单商城提成已发放"通知。**完整 E2E 通过**：mall 订单 completed → Commission(pending) → SalaryRecord(draft→approved→paid) → Commission(settled) + 通知推送
- **M4a-fix + M4c + M5 Mall 运营闭环**：
  - 补齐业务员工作台 `my-customers` / `invite-codes` (3 端点) / `stats` (2 端点) / `profile` (5 端点)
  - `notification_logs` 表扩 `recipient_type` + `mall_user_id`；`notify_mall_user` 新 shortcut；ERP 现有查询加 `recipient_type='erp_user'` 过滤；workspace `/notifications` 4 端点（列表/未读数/标读/全读）
  - workspace `/attendance` 6 端点（checkin/today/visits/enter/leave/active/list），直接写 ERP 的 `checkin_records` / `customer_visits`，日期按 Asia/Shanghai
  - 关键业务流程推通知：claim/deliver/cancel/admin_reassign/partial_confirm/fully_confirm/skip_alert 触发；归档前 7 天预告（每日扫描）
  - Admin: `/users/{id}/reactivate` / `/disable` / `/referrer` 换绑（均带审计）；`/payments/pending` + `/manual-record/{order_id}` 补录（partial_closed 可被补满恢复 completed + 触发 commission）；`/salesmen` 新建/列表/重置密码
  - E2E 通过：bob 归档→reactivate→last_order_at reset；partial_closed 订单经 manual-record 补款后 completed + 提成入账
- **M4s Mall 定时任务调度**：引入 APScheduler（AsyncIOScheduler）集成到 FastAPI lifespan，4 个定时任务：(1) 超时未接单扫描（每 5min，给推荐人记 skip_log）/ (2) 3 级停用用户归档（每日凌晨 2:10，30/90/180 天阈值按成交订单数分级，归档同时 bump token_version 吊销 token + 清购物车）/ (3) delivered 60 天未全款订单 → partial_closed，已收部分计提成 / (4) 登录日志 90 天清理。4 个 admin 端点 `/api/mall/admin/housekeeping/*` 可手动触发。E2E 4/4 通过
- **M4a Mall 履约闭环**：5 张新表（mall_payments / mall_shipments / mall_attachments / mall_customer_skip_logs / mall_skip_alerts）+ `commissions.mall_order_id` 字段。抢单池两阶段（推荐人独占期 + 开放期）+ FOR UPDATE 锁；业务员 ship/deliver（sha256 防篡改附件）/ upload_payment_voucher 履约三段；财务确认收款触发 completed + 提成计算（按 brand 切分收入 × 3 级提成率查询）。跳单告警 3 次/30 天阈值 + 业务员申诉 + 管理员 resolve/dismissed（dismissed 时对应 skip_logs 标 dismissed 不计入后续阈值），partial unique index 防并发双建 open alert。附件上传端点（POST /api/mall/salesman/attachments/upload）后端计算 sha256，service 层拒绝非本服务器 URL 防伪造。**完整履约 E2E 全通过**：下单→抢单→出库→送达→传凭证→确认收款→completed + 提成 ¥44.97 入账
- **M3 Mall 下单闭环**：4 张新表（mall_cart_items / mall_orders / mall_order_items / mall_order_claim_logs）+ `mall_inventory.quantity >= 0` CHECK 约束。7 个端点（orders preview/create/list/detail/cancel/confirm-receipt/stats）、cart 4 个（info/count/change/delete）、addresses 5 个（CRUD + set-default）。核心流程：预览算金额 → 创建订单（事务内扣库存 FOR UPDATE + 固化 referrer/cost_price + 清购物车 + 更新 last_order_at）→ 列表/详情 → 取消退回库存。未绑推荐人的 consumer 403 拒绝预览/下单（阻断未授权扒价）；库存不足 400 友好提示。**15 个 E2E 场景全通过**：加地址/加购/预览/下单/库存扣 100→98/取消/库存退回/统计/未绑 referrer 403/库存不足 400
- **M2 Mall 商品浏览**：10 张新表（mall_categories / mall_product_tags / mall_product_tag_rels / mall_products / mall_product_skus / mall_collections / mall_warehouses / mall_inventory / mall_inventory_flows / mall_notices）；6 个端点（products 列表/详情/tags、categories、search.products、search.hot-keywords、notices、regions）。**价格脱敏**走 ContextVar + Pydantic field_serializer：未登录 / 未绑推荐人 → price/maxPrice/skuPrice 返 null；已绑 consumer / salesman → 展示。响应字段通过 serialization_alias 保持 mall4j 契约（prodId/prodName/skuId/categoryId），小程序前端零改动。14 个 E2E 场景全通过
- **M1 Mall 鉴权基建（小程序后端起步）**：5 张 mall_* 表（mall_users / mall_addresses / mall_regions / mall_invite_codes / mall_login_logs）+ CHECK 约束（user_type='salesman' 必须有 linked_employee_id）；新增独立 mall JWT 链路（`MALL_JWT_SECRET` / `create_mall_access_token` / `CurrentMallUser`），和 ERP JWT 双向不互认（实测 cross-token 调用 401）；`token_version` 字段 + `bump_token_version` 实现 logout/封禁/换绑即时吊销所有在途 JWT；6 个端点 `/api/mall/auth/*`（login-password/register/wechat-login/wechat-register/refresh/logout）全部按 ERP 原生协议（HTTP status + `{detail}`）；邀请码 2h 一次性 + SQL FOR UPDATE 原子消费 + 每日 20 张上限（按 Asia/Shanghai 日界）；登录日志自动落表用 SAVEPOINT 隔离，日志写失败不阻塞登录。12 个 E2E 场景全通过
- **miniprogram http.js 切 ERP 原生协议**：去掉 mall4j 错误码分支，改按 HTTP status；401 清整套 session（Token/RefreshToken/userType/userId/hadLogin）；loginSuccess 统一写齐 Storage；register/accountLogin 页去掉 `encrypt` RSA 密文改明文（后端 bcrypt 比对）；refresh 失败按 status 区分（仅 401/403 清 session，5xx/网络错静默重试）
- 引入小程序子项目 `miniprogram/`（uni-app · Vue 3），承载 C 端商城 + 业务员工作台双端。完成业务员工作台前端骨架（17 个 salesman-* 页，覆盖接单池 / 履约 / 凭证上传 / 打卡 / 拜访 / 请假 / 报销 / 稽查 / KPI / 通知 / 邀请码 / 我的客户 / 跳单告警），打卡模块对齐 ERP `CheckinRecord` / `CustomerVisit` 模型，C 端注册强制 invite_code。`.gitignore` + `README.md` + `CLAUDE.md` 同步更新
- `README.md` + `CLAUDE.md` 新增"部署拓扑"说明：monorepo 三子项目各自独立部署，backend 是统一后端，frontend/miniprogram 不共享包管理、不做 pnpm workspace；后端按路由前缀分端（`/api/` 给 ERP，`/api/mall/` 给小程序），共享 service 层靠 ActorContext 承接两端调用
- [#11] `vite.config.ts` 提取 `BACKEND` 常量；`CLAUDE.md` / `README.md` 新增端口选择说明（为啥不用 8001）
- [#9] 迁移内置 `_ensure_rls_prerequisites()` 幂等创建 erp_app role + helper 函数，migration 独立可跑
- 新增 `skills/xinjiulong-erp/` Agent 技能包（SKILL.md + 11 份 references + 5 个 helper 脚本）：飞书交互规范、3 种结算模式、订单闭环、收款审批、政策兑付、稽查 5 场景、账户/工资/考勤/审批中心聚合，所有 250+ API 端点速查
- 补充 6 份 **企业 Agent 业务沉淀文档** 到 `skills/xinjiulong-erp/references/`：`state-machines.md`（13 种实体状态机）/ `field-semantics.md`（关键字段三模式语义）/ `fund-flows-catalog.md`（22 个动账场景）/ `business-rules.md`（19 节硬性规则，新增 §零 身份隔离红线）/ `agent-playbook.md`（30 个员工话术 → API 序列剧本）/ `pitfalls.md`（43 个历史 bug，新增身份绑定类 5 条）；SKILL.md 顶部新增"总览类"索引 + 原则 0 "先绑定身份用用户本人 JWT"，明确 Agent 永不持固定 token / 不跨 open_id 复用 / 密码不进 memory
- 新增 `skills/xinjiulong-erp/references/miniprogram-status.md`：沉淀小程序端三端部署拓扑、17 个 salesman-* + C 端页清单、后端 `/api/mall/*` 路由**文件已写但 main.py 未挂载（全部 404）**的真实状态，让 Agent 不要误推"去小程序做 XXX"；约定接通判据是 `GET /api/mall/products` 返 200
- **KPI 系数规则**：新表 `kpi_coefficient_rules`（品牌 × 完成率区间 × 模式），老板/admin 可在 `/hr/kpi-rules` 页面增删改。规则支持 `linear`（系数=完成率）和 `fixed`（区间内固定值）两种模式，留存历史（改规则=旧记录设失效日+插入新记录）。工资单生成时冻结 `kpi_rule_snapshot` 用于审计，老板可对 draft/rejected 工资单 `POST /salary-records/{id}/recompute` 按当前规则重算提成
- 补修 5 处 `SUM(Receipt.amount)` 漏过滤 `status='confirmed'` 的 bug（finance.py 创建 Receipt 后重算 payment_status / finance.py 两处 KPI 刷新 + 里程碑、sales_targets.py `/my-dashboard` 进度、mcp tools_action.py register-payment）。影响：业务员上传凭证未经审批就刷 KPI / 误触发 Commission 生成 / 仪表盘看到虚高进度

### Changed

- **MCP Phase 4 skill 文档改造 + bridge 清理**：新增 3 份 MCP 视角文档到 `skills/xinjiulong-erp/references/`：`mcp-tools-catalog.md`（94 个 tool 按场景分组 + 中文参数说明）、`mcp-agent-playbook.md`（14 个典型场景的 MCP tool 调用序列）、`mcp-alignment-changelog.md`（Phase 1-3 施工记录 + 5 个 review bug + smoke test）；SKILL.md 顶部索引把 MCP 视角文档标为首选，旧 `agent-playbook.md` 降级为 legacy；`bridge.py _MCP_INSTRUCTIONS` 从"业务不对齐告警"改为"薄壳化完成 + 分组说明 + 身份隔离铁律 + 废弃工具清单"；list_tools 删除 `⚠️ [业务不对齐，建议走前端]` description 前缀（47 个写入 tool 不再标警告）
- **MCP 薄壳化对齐前端业务（Phase 1-3）**：MCP 写入类 tool 全部改为"薄壳 → 调 HTTP 真身 handler"，不再复刻 customer_paid_amount / 政策匹配 / 动账 逻辑
  - **Phase 1**：`app/api/routes/orders.py` 抽出 6 个公共函数（`_enforce_salesman_binding` / `_resolve_brand_and_products` / `_validate_customer_belongs_to_salesman` / `_match_or_load_policy_template` / `_compute_order_amounts` / `_build_order_from_computed`），HTTP 和 MCP 共用。新增 4 个合并接口：`POST /api/orders/preview`（金额实时计算）、`POST /api/orders/create-with-policy`（建单 + PolicyRequest + submit-policy 事务化三步合一）、`POST /api/orders/{id}/approve-policy-with-request`（合并 PR.status=approved + Order.approve-policy）、`POST /api/orders/{id}/reject-policy-with-request`
  - **Phase 1.5 权限补丁**：全修 5 个缺陷 —— HTTP `POST /api/orders` 补 salesman 身份硬绑定；`_resolve_brand_and_products` 用 `select()` 而非 `db.get()` 走 RLS；新增 `_validate_customer_belongs_to_salesman` 对 salesman 做 CBS 三元组校验（400 "客户不存在或未绑定到你名下"，不暴露存在性）；approve/reject-policy-with-request 加品牌白名单兜底；preview 补 finance 角色
  - **Phase 2**：14 个写入 MCP tool 薄壳化（`preview-order` / `create-order` / `register-payment` / `upload-payment-voucher`[新增] / `confirm-order-payment` / `reject-payment-receipts`[新增] / `approve-order`合并 / `reject-order-policy` / `approve-fund-transfer` / `approve-financing-repayment` / `approve-inspection` 拆两步 / `approve-purchase-order` / `approve-expense-claim` / `complete-order`）
  - **Phase 3**：12 个缺失 MCP tool 补齐（`fulfill-materials` / `fulfill-item-status` / `submit-policy-voucher` / `confirm-fulfill` / `confirm-policy-arrival`重写 / `cancel-purchase-order` / `close-inspection-case` / `receive-purchase-order`薄壳 / `create-fund-transfer-request`）。删除旧的语义错误 tool `fulfill-policy-materials`（只改字段不扣库存）和旧 `confirm-policy-arrival`（只改 PR.status 不动 item/F 类账户）
  - 新增 `backend/app/mcp/_resolvers.py` 集中管理 name/code → UUID 转换（customer / product / salesman / policy_template / warehouse / brand / supplier / account / order_by_no）
  - smoke test 全绿：三种 settlement_mode 下 HTTP `/api/orders/preview` 与 `/mcp/preview-order` 金额字段逐字段相等；create-with-policy 端到端建 Order + PolicyRequest + submit-policy；CBS 权限边界生效（salesman 建别品牌未绑定客户 → 400）
- [#6] React Query 全局 `staleTime: 30_000 + refetchOnMount: 'always'`，避免重复请求、切回页面保证看到最新数据（M15）
- [#8] MCP 工具集加业务不对齐警告（Server instructions + 57 个写入类 tool description 前缀 + 模块 docstring）
- [#11] Vite 代理目标 8001 → 8002（避免被 SSH 端口转发 / VS Code Plugin Host 占用导致 502）

### Fixed

- [007b14a] **严重 bug**：`server_default="now()"` 是字符串字面量，PG 建表时立即求值固化，导致所有表的 `created_at` 都是同一个静态时间。21 个模型改 `func.now()` + migration 修所有表 DB default
- [007b14a] 前端 11 个上传调用手工设 `Content-Type: multipart/form-data` 覆盖了 axios 的 boundary → 400；2 处 Blob 上传缺 filename → 422
- [007b14a] 11 个页面时间字符串切片显示，实际少 8 小时。统一 `toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })`
- [007b14a] `customers` 列表多品牌客户 JOIN CBS 重复显示，加 `distinct()`
- [007b14a] `seed.py` 补业务员品牌绑定 + 客户 CBS + master 账户 + Position，RLS 启用后本地环境才能跑完整业务流
- [007b14a] `FinanceApproval` 审批中心查询条件适配 P2c-1 新流程（`pending_receipt_count > 0`）
- [651a55c] **review 发现严重 bug**：`POST /api/receipts` 和 MCP register-payment 立即动账但 Receipt.status 默认 `pending_confirmation`，会被 confirm_payment 当"待审"二次处理导致**重复加余额**。两路径显式设 `status=confirmed` 修复
- [651a55c] RLS 补齐后业务员看不到 master 账户 → `upload_payment_voucher` 400。改成 account_id 暂不绑定，审批时才填 master
- [971719c] **严重**：删除 Receipt/Payment/Expense 时没回滚账户余额、没删 fund_flow，账务永久失衡。已 confirmed/paid 的单据改为拒绝删除（要撤销走反向凭证）
- [971719c] **严重**：`salary_order_links` 无唯一约束，并发生成工资单时同一订单提成可能双发。加 `(order_id, is_manager_share)` 唯一约束 + 清理历史重复
- [971719c] **严重**：采购撤销反扣 `payment_to_mfr` 账户时无余额校验，并发多单撤销可能让账户变负。加 SELECT FOR UPDATE + balance 校验
- [971719c] OrderList 建单预览政策应收在 employee_pay（业务员垫差）模式下错误显示为 policy_gap，应为 0
- [6a8027d] **严重**：`confirm_arrival` 无幂等保护，重复点击/网络重试会让 F 类账户余额被加两次
- [6a8027d] **严重**：`confirm_fulfill` 的 settled_amount 用 `+=` 累加，重复确认同一条目会无限膨胀，导致利润台账"政策兑付盈利"虚高
- [6a8027d] 销售目标里程碑通知永远不推送（`prev_rate == rate` 条件始终不成立）
- **严重**：`DELETE /api/inspection-cases/{id}` 拒绝列表漏掉 `'executed'`，已执行案件可被删除，库存+账户永久错乱。修正为只允许删 pending/approved/rejected
- **严重**：`InspectionCase` A3/B2 的 payment_to_mfr 账户动账在 create 阶段就发生，update 不重算、reject 不反转 → 账户漂移。挪到 execute 阶段，统一入口（含余额校验 + account 不存在则 400）
- **严重**：`POST /financing-orders/repayments/{id}/approve` F 类账户余额不足时**静默跳过**，但现金、PO.paid、order.repaid_principal 已更新 → 账务永久失衡。现在提前预校验，不足则整体 400 拒绝
- **严重**：`approve_repayment` 无锁，多笔 pending 并发审批时 `order.repaid_principal +=` 互相覆盖丢一笔还款。加 `SELECT FOR UPDATE` 锁 repayment + order
- **严重**：`submit_repayment` 不校验 `pay_acc.brand_id == order.brand_id`，可跨品牌还款串账。补 brand 一致性校验
- **严重**：`ManufacturerSettlementUpdate` schema 允许 PUT `settled_amount/unsettled_amount`，财务可手工改回"剩余 ¥X"再次分配同一笔结算，导致 F 类账户重复入账。从 schema 移除这两个字段
- **严重**：`DELETE /api/expense-claims/{id}` 无状态校验，删已 approved/paid/settled 的报销会让 share_out 扣款 / 日常拨款的账户变动无法回滚。改为只允许删 pending/rejected
- **严重**：`approve` share_out 时 master/ptm 账户任一不存在就静默只做一半 → 账务失衡。两个账户都必须找到否则 400，且加 ptm 余额校验
- **严重**：`reject_claim` 无状态校验，可驳回已 approved 的 share_out 但不反转账户。改为只允许驳回 pending
- `pay_daily_claim` 无行锁，两个并发请求可能双扣账户。加 `SELECT FOR UPDATE` 锁 claim + account
- **严重**：`_compute_kpi_coefficient` 在 [0.8, 1.0) 区间强制返回 0.8，导致完成率 0.9 的员工提成系数反而比 0.7 的（系数=0.7）低 → 员工提成发错钱。改为按完成率线性返回（<50% 为 0，其余 = rate）
- **严重**：`performance.py` 4 处 `SUM(Receipt.amount)` 没过滤 `Receipt.status='confirmed'`，业务员上传凭证立刻（pending_confirmation 状态）或已被驳回（rejected）的收款也被算进 KPI 实际回款，可刷绩效。所有 Receipt SUM 补 `status='confirmed'` 过滤
- **中等**：`policy_service.confirm_settlement_allocation` 未校验 `settlement.brand_id == claim.brand_id`，跨品牌 settlement 分配到 claim 时走 company_pay 路径会动 claim 品牌的 F 类/现金账户 → 跨品牌资金串账。补品牌一致性校验
- [#3] `requirements.txt` 补 `mcp` / `openpyxl`；锁 `bcrypt==4.3.0`（passlib 1.7 跟 bcrypt 5.x 自检冲突）
- [#3] `.env.example` `CORS_ORIGINS` 改 JSON 数组格式，Pydantic v2 不接受逗号分隔
- [#4] antd v6 废弃 API 批量替换：`Drawer.width → size`（1 处）、`Statistic.valueStyle → styles.content`（30 处）、`Alert.message → title`（15 处）
- [#5] antd v6 `InputNumber.addonBefore/After` → 原生 `prefix/suffix`（19 处）。视觉略有差异（addon 灰底块 → 内嵌符号），功能等价
- **严重**：`mcp_receive_purchase_order` 允许 `approved` 状态直接入库（对比 HTTP 层要求 `paid/shipped`），AI Agent 可跳过付款审批；且无 `received` 幂等挡，重复调用会双写 StockFlow/Inventory。对齐 HTTP 层状态校验 + `received` 拒绝 + 品鉴仓例外
- **严重**：`mcp_confirm_subsidy_arrival` 只改 status 不动账户 → 补贴"已到账"但品牌现金账户没加钱。重写为按 `(brand_id, period)` 批量处理 + 金额精确匹配 + 品牌现金入账（与 HTTP 层一致）
- **严重**：`mcp_confirm_order_payment` 只置 `status=completed` 跳过所有副作用 → Commission 不生成、KPI 不刷新、里程碑不推送。重写为完整对齐 `POST /api/orders/{id}/confirm-payment`（批量 confirm 所有 pending Receipt、动账、分摊应收、调 receipt_service）
- **严重**：`mcp_register_payment` 原本是自实现（Receipt/Commission 等），易与 receipt_service 失同步。改为调用 `apply_per_receipt_effects` + `apply_post_confirmation_effects`，权限收紧到 boss/finance（业务员走 upload-payment-voucher 审批流）
- **严重**：`mcp_receive_purchase_order` 本身的 `PurchaseOrderItem` import 写在使用之后（NameError 潜在），移到使用前
- `sales_targets._calc_actual` / `finance.py` 里程碑 / `receipt_service` / `performance.py`（两处）/ `dashboard.py`（两处）共 6 处 `SUM(Order.total_amount)` 漏过滤 `Order.status`，`rejected`/`cancelled` 订单被算进销售达成/绩效 → 可能虚假触发阶梯奖金；统一 `notin_(["rejected","cancelled"])`
- `apply_post_confirmation_effects` 加 `newly_confirmed_amount` 参数用于里程碑 prev_rate 计算（历史用整单应收估算，partial confirm 场景会误推里程碑档位）。三处调用方（orders.py、mcp tools_action、mcp tools_approval）均补传
- `attendance.visit_enter` 无"未关闭前次拜访"校验 → 员工连续 enter 十次不 leave 会刷多条开放记录；补强制先 leave

### Known issues（未修复）

- RLS `fund_flows` 写策略仍是 `WITH CHECK (true)`，任何登录用户可伪造资金流水（health-check S2，待 P2c 配合业务改造修复）
- `<Space direction="vertical">` 12 处 antd v6 废弃（issue #2 跟踪）
- 上传下载端点 GET `/api/uploads/files/{path}` 仍无鉴权，靠 UUID 不可枚举降级（issue #7 跟踪 signed URL 方案）
- Alembic 初始 migration 未建全 31 张表，只能靠 `init_db create_all` 兜底（issue #1 跟踪）
