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

- 业务员"我的订单"在途 Tab 现在同时显示 `assigned` + `shipped` 两个状态（原仅 assigned → 导致已出库未送达的单消失）。后端 `/api/mall/salesman/orders` 的 `status` 参数支持逗号分隔多值
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
