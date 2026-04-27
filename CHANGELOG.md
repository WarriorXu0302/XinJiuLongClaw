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

- [#11] `vite.config.ts` 提取 `BACKEND` 常量；`CLAUDE.md` / `README.md` 新增端口选择说明（为啥不用 8001）
- [#9] 迁移内置 `_ensure_rls_prerequisites()` 幂等创建 erp_app role + helper 函数，migration 独立可跑
- 新增 `skills/xinjiulong-erp/` Agent 技能包（SKILL.md + 11 份 references + 5 个 helper 脚本）：飞书交互规范、3 种结算模式、订单闭环、收款审批、政策兑付、稽查 5 场景、账户/工资/考勤/审批中心聚合，所有 250+ API 端点速查
- **KPI 系数规则**：新表 `kpi_coefficient_rules`（品牌 × 完成率区间 × 模式），老板/admin 可在 `/hr/kpi-rules` 页面增删改。规则支持 `linear`（系数=完成率）和 `fixed`（区间内固定值）两种模式，留存历史（改规则=旧记录设失效日+插入新记录）。工资单生成时冻结 `kpi_rule_snapshot` 用于审计，老板可对 draft/rejected 工资单 `POST /salary-records/{id}/recompute` 按当前规则重算提成
- 补修 5 处 `SUM(Receipt.amount)` 漏过滤 `status='confirmed'` 的 bug（finance.py 创建 Receipt 后重算 payment_status / finance.py 两处 KPI 刷新 + 里程碑、sales_targets.py `/my-dashboard` 进度、mcp tools_action.py register-payment）。影响：业务员上传凭证未经审批就刷 KPI / 误触发 Commission 生成 / 仪表盘看到虚高进度

### Changed

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

### Known issues（未修复）

- RLS `fund_flows` 写策略仍是 `WITH CHECK (true)`，任何登录用户可伪造资金流水（health-check S2，待 P2c 配合业务改造修复）
- `<Space direction="vertical">` 12 处 antd v6 废弃（issue #2 跟踪）
- 上传下载端点 GET `/api/uploads/files/{path}` 仍无鉴权，靠 UUID 不可枚举降级（issue #7 跟踪 signed URL 方案）
- Alembic 初始 migration 未建全 31 张表，只能靠 `init_db create_all` 兜底（issue #1 跟踪）
