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

### Added

- [#11] `vite.config.ts` 提取 `BACKEND` 常量；`CLAUDE.md` / `README.md` 新增端口选择说明（为啥不用 8001）
- [#9] 迁移内置 `_ensure_rls_prerequisites()` 幂等创建 erp_app role + helper 函数，migration 独立可跑

### Changed

- [#6] React Query 全局 `staleTime: 30_000 + refetchOnMount: 'always'`，避免重复请求、切回页面保证看到最新数据（M15）
- [#8] MCP 工具集加业务不对齐警告（Server instructions + 57 个写入类 tool description 前缀 + 模块 docstring）
- [#11] Vite 代理目标 8001 → 8002（避免被 SSH 端口转发 / VS Code Plugin Host 占用导致 502）

### Fixed

- [#3] `requirements.txt` 补 `mcp` / `openpyxl`；锁 `bcrypt==4.3.0`（passlib 1.7 跟 bcrypt 5.x 自检冲突）
- [#3] `.env.example` `CORS_ORIGINS` 改 JSON 数组格式，Pydantic v2 不接受逗号分隔
- [#4] antd v6 废弃 API 批量替换：`Drawer.width → size`（1 处）、`Statistic.valueStyle → styles.content`（30 处）、`Alert.message → title`（15 处）
- [#5] antd v6 `InputNumber.addonBefore/After` → 原生 `prefix/suffix`（19 处）。视觉略有差异（addon 灰底块 → 内嵌符号），功能等价

### Known issues（未修复）

- RLS `fund_flows` 写策略仍是 `WITH CHECK (true)`，任何登录用户可伪造资金流水（health-check S2，待 P2c 配合业务改造修复）
- `<Space direction="vertical">` 12 处 antd v6 废弃（issue #2 跟踪）
- 上传下载端点 GET `/api/uploads/files/{path}` 仍无鉴权，靠 UUID 不可枚举降级（issue #7 跟踪 signed URL 方案）
- Alembic 初始 migration 未建全 31 张表，只能靠 `init_db create_all` 兜底（issue #1 跟踪）
