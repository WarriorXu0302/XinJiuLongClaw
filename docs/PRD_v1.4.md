# 新鑫久隆ERP系统 - 需求文档（封版）

> 版本：v1.4 （封版）
> 日期：2026-04-12

---

## 1. 系统概述

### 1.1 项目背景

鑫久隆是一家酒类代理公司，主营五粮液、青花郎、珍十五、贵州平坝等品牌白酒的销售业务。公司业务员通过飞书群进行报单，订单涉及复杂的厂家政策匹配与兑付流程。现有的 ERP 系统功能分散，已不能满足业务需求，需构建一套完整的、支持人机协作的新 ERP 系统。

### 1.2 核心盈利逻辑

酒类销售存在"倒挂"现象——进货价 = 销售价，但客户实际到手价 < 销售价。中间的差价由厂家政策补贴。

**举例：**
- 青花郎进货价 **885元/箱**，销售价 **885元/箱**
- 客户到手折算价 **650元/箱**
- **差价 235元/箱 = 厂家的政策补贴**
- 业务员或公司**先垫付**这笔差价
- 等待厂家**审核通过并打款**后，兑付给客户/业务员/公司

> **因此，系统的核心不是"卖酒"，而是"政策管理 + 政策执行 + 资金垫付与核销回收"。**

### 1.3 系统目标

1. 实现销售与客情全流程线上化：包含有单出货与无单招待。
2. 通过 openclaw（AI Gateway）+ Skills 实现飞书群聊的智能协作。
3. 精确管理政策兑付的四级链路：申请 → 执行(含品鉴消耗) → 申报 → 多对多到账核销。
4. 建立基于**批次管理**的精准财务核算与多账户联动体系。
5. 实现双入口隔离：内部员工 Web+Agent，外部厂家人员**纯 Agent (Headless)** 交互。

### 1.4 技术选型

| 层级 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite + Ant Design + Zustand + TanStack Query |
| 后端 | Python FastAPI (async) + SQLAlchemy 2.0 (async) |
| 数据库 | PostgreSQL 16+（JSONB + pgvector） |
| 缓存/队列 | Redis 7+（会话 + 缓存 + Celery broker） |
| AI 交互 | openclaw + MCP Server + Skills |
| LLM | DashScope (Qwen) / Anthropic |

### 1.5 系统入口与交互模式

| 角色类型 | 入口 | 使用方式 |
|----------|------|----------|
| **内部管理/后端** | React Web | 老板、财务、库管、HR、采购等通过浏览器操作 |
| **内部业务端** | openclaw + 飞书内部群 | 业务员在内部群发消息，Agent 自动处理业务 |
| **外部厂家端** | **仅限 openclaw + 飞书外部联络群** | 厂家人员**无 Web 账号**。系统通过飞书外部群识别其 open_id，通过对话/卡片完成方案号回填、审批与动态推送 |

> ⚠️ **安全红线：openclaw 在没有鉴权密钥（JWT token 或白名单 open_id）的情况下，无法操控 ERP。厂家人员指令通过后端校验 `open_id` 绑定的 `manufacturer_id` 进行越权拦截。**

---

## 2. 用户角色与权限体系

### 2.1 角色定义

| 角色 | 代码 | 说明 |
|------|------|------|
| 超级管理员 | admin | 全公司数据，无限制 |
| 老板 | boss | 全公司数据，**政策一级审批人（内部审批）**，可查看所有账户 |
| 财务 | finance | 仅财务相关模块（账户/收款/付款/融资/核算） |
| 业务员 | salesman | 仅自己负责的客户和订单 |
| 库管 | warehouse | 仅自己有权限的仓库的库存和出入库操作 |
| 人事 | hr | 仅 HR 相关模块 |
| 采购 | purchase | 供应商管理和采购订单 |
| 厂家人员 | manufacturer_staff | **政策最终确认人（外部审批）**，回填方案号、推送销售新动向。**仅通过飞书 Agent 交互，无 Web 权限** |

### 2.2 数据范围过滤规则

所有查询自动注入数据范围 filter：

| 角色 | 过滤规则 |
|------|----------|
| admin / boss | 无过滤（全公司） |
| finance | 仅 finance 相关模块 |
| salesman | `WHERE salesman_id = 当前员工ID` |
| warehouse | `WHERE warehouse_id IN (授权仓库IDs)` |
| manufacturer_staff | 飞书 Agent 接口底层强制注入：`WHERE manufacturer_id = 绑定的厂家ID` |

### 2.3 鉴权方式

| 入口 | 鉴权方式 |
|------|----------|
| React Web (内部) | 用户名 + 密码 → JWT token → 存 localStorage |
| openclaw / 飞书 (内部) | 员工姓名 + 密码 → JWT token → MCP 请求头携带 |
| openclaw / 飞书 (厂家) | **无感知鉴权**：通过飞书外部群上下文获取 `open_id`，后端查表匹配 `manufacturer_id`，生成短期内部 Token。 |

> 系统需维护 `manufacturer_external_identities` 绑定表，记录 `open_id -> manufacturer_id` 的映射关系、品牌范围、状态与最后活跃时间。所有厂家外部指令必须先查该表，再签发短期内部 Token；解绑或禁用后应立即失效。执行外部审批、方案号回填、动态发布时，除校验 `manufacturer_id` 外，还必须校验操作对象是否落在 `brand_scope` 范围内。

---

## 3. 业务模块详细需求

### 3.1 销售模块

#### 3.1.1 订单信息格式
业务员报单格式：**姓名/店名 + 产品名称 + 数量 + 单价**
示例：`张三 青花郎 10箱 885`

#### 3.1.2 订单状态流转 (履约状态与支付状态解耦)
```text
pending（待处理）
    ↓ 匹配政策，业务员确认
policy_pending_internal（待老板审批）
    ↓ 老板审批通过
policy_pending_external（待厂家确认 - 仅限微调/自定义政策，或标准政策缺少预置方案号时进入此步）
    ↓ 厂家在外部群卡片确认并回填方案号
approved（政策已彻底通过）
    ↓ 扫码出库
shipped（已出库）
    ↓ 上传送货凭证 / 妥投确认
 delivered（已妥投）
    ↓ 履约归档
completed（履约完成）
```

> 补充状态约束：`approved` 表示**内部审批以及所有必需的外部确认均已完成**。标准政策若已在模板侧预置 `scheme_no` 且无微调，可在老板审批通过后直接进入 `approved`。任一审批环节拒绝时，订单状态回写为 `policy_rejected`，并记录 `rejection_reason` 供业务修改后重新提交。
>
> `delivered` 表示货物已妥投，且送货凭证/签收信息已上传。对于账期客户，在进入 `delivered` 时系统即可自动生成 `receivables`。
>
> `completed` 表示**订单履约流程结束**，不再依赖收款完成。收款状态通过独立字段 `payment_status` 管理，允许账期客户在 `payment_status = unpaid / partially_paid` 时订单仍进入 `completed`。通常在订单已 `delivered`，且出库、签收、送货凭证上传等履约必要动作全部完成后，由系统自动流转或由具备权限人员确认归档进入 `completed`。
>
> 政策申请、政策执行、兑付申报资格不依赖 `payment_status = fully_paid`，而依赖于政策审批结果与业务履约事实（通常为 `approved`、`shipped` 或 `delivered`）。

#### 3.1.3 订单与明细核心字段
- `orders`: `order_no`, `customer_id`, `total_amount`, `status`, `payment_status`, `settlement_mode_snapshot`, `salesman_id`, `rejection_reason`
- `order_items`: `order_id`, `product_id`, `quantity`, `unit_price`, `cost_price_snapshot`（可选快照；**真实成本以出库分配明细为准**）
- `stock_out_allocations`: `order_item_id`, `stock_flow_id`, `batch_no`, `allocated_quantity`, `allocated_cost_price`, `cost_allocation_mode`

> 客户主数据需支持 `settlement_mode`（现款/账期）、`credit_days`、`credit_limit` 等字段，用于控制是否在 `delivered` 后自动生成应收账款。

### 3.2 政策与兑付模块 (核心重构：四级单据链路)

真实业务中，不仅有随单出货的政策，还有大量“无出货”的客情招待。厂家汇款也是多笔打包的。系统必须遵循 **“申请 → 执行 → 申报 → 核销”** 四层解耦模型。

#### 3.2.1 第一层：政策申请单 (policy_request) —— “入口”
**不强制绑定订单**，它是所有资源消耗的统一入口。
- **业务场景**：随单申请补贴 / 老板手动申请 3 瓶酒搞客情 / 市场部申请办品鉴会 / 其他手工补录场景。
- **核心字段**：
  - `request_source`: 枚举 `order` (销售订单) / `hospitality` (客情招待) / `market_activity` (市场活动) / `manual` (其他手工发起)
  - `approval_mode`: 枚举 `internal_only` / `internal_plus_external`。标准模板且已预置方案号时为 `internal_only`；微调、自定义或缺少预置方案号时为 `internal_plus_external`。
  - `order_id`: **Nullable（可空）**，当 `request_source = order` 时必填。
  - `customer_id`: **Nullable（可空）**。当 `request_source = order` 时应与订单客户一致；在 `hospitality` / `market_activity` / `manual` 场景下可空。
  - `target_name`: 非标准客户主体名称，如关键人、渠道联系人、单位名称。
  - `usage_purpose`: 文字说明申请目的与去向。在 `customer_id` 为空时必填。
  - `brand_id`, `policy_id`
  - `policy_version_id`: 政策版本号/版本主键，用于指向申请时刻采用的政策版本
  - `policy_snapshot`: JSONB 快照，保存申请时的关键政策参数（补贴规则、赠品规则、默认方案号等）
  - `scheme_no`: 方案号。**标准政策优先取 `policy_template` 中预置的默认方案号；微调/自定义政策由厂家外部确认时回填。进入 `approved` 前必须存在有效 `scheme_no`。**
  - `internal_approved_by`: 老板/高管审批记录
  - `manufacturer_approved_by`: 厂家外部审批记录
  - `status`: `pending_internal` / `pending_external` / `approved` / `rejected`

> 约束：当 `request_source != order` 时，`customer_id` 可空，但必须保留足够的业务去向信息；最少要求 `usage_purpose` 非空，建议配合 `target_name` 使用。政策申请创建时，应保存 `policy_version_id` 或 `policy_snapshot`，避免后续模板变更影响历史单据解释。

#### 3.2.2 第二层：政策权益使用记录 (policy_usage_record) —— “执行明细”
记录“事”的发生。一个申请单（如批了3场品鉴会）可拆分为 3 条执行明细。
- **核心字段**：
  - `policy_request_id`: **必填**（向上追溯源头）
  - `benefit_item_type`: 权益类型（如 `tasting_event`, `cash_subsidy`）
  - `usage_scene`, `usage_applicant_id`: 实际使用场景与申请人
  - `planned_amount`: 预算额
  - `actual_amount`: 实际发生花费（如报销餐费）
  - `reimbursement_amount`: 可对厂家申报的金额上限；执行完成后由系统或财务确认
  - `advance_payer_type`: 垫付主体类型，建议枚举 `employee` / `company` / `customer`
  - `advance_payer_id`: 垫付主体 ID
  - `surplus_handling_type`: 结余处理方式（转利润/转备用库/无）
  - `execution_status`: `pending` / `in_progress` / `completed`
  - `claim_status`: `unclaimed` / `partially_claimed` / `fully_claimed`（可为派生字段，也可落库缓存）
- **约束规则**：
  - 一条 `policy_usage_record` 允许被拆分到多条 `policy_claim_items` 中，支持跨月、分批申报。
  - 同一条 `policy_usage_record` 的累计 `declared_amount` **不得超过** `reimbursement_amount`；超过时系统必须拒绝提交。
  - 涉及实物消耗的执行记录，必须能够追溯到库存流水；否则不得标记为 `completed`。

#### 3.2.3 品鉴酒消耗追踪 (tasting_wine_usage)
作为“实物执行”的延伸，挂载在 `usage_record` 之下。
- **关联调整**：**必须关联 `source_usage_record_id` (多对一)**。因为一次品鉴权益可能分多次喝完。
- **建议字段**：`usage_type`, `product_id`, `quantity`, `batch_no`, `source_usage_record_id`, `stock_flow_id`, `target_warehouse_id`, `into_company_backup_stock`
- **库存联动规则**：
  - 当 `usage_type` 为 **招待消耗** / **客户使用** 时，必须自动生成一条 `flow_type = outbound` 的 `stock_flow`，扣减对应品鉴仓/活动仓库存。
  - 当 `usage_type` 为 **转公司备用库** 时，必须生成一组调拨流水：来源仓 `outbound` + 目标仓 `transfer_in`。
  - 当 `usage_type` 为 **对外变现** 时，必须生成库存出库，同时联动生成现金收入或应收记录。
- **硬约束**：没有关联库存流水的 `tasting_wine_usage`，不得标记为执行完成。

#### 3.2.4 第三层：兑付申请与明细 (policy_claim & claim_items) —— “申报明细”
记录“钱”的申报。财务把本月几十条已完成的 `usage_record` 挑选出来，打包向厂家要钱。
- **`policy_claims` (主单)**:
  - 汇总级别的申报单，核心字段至少包括：`claim_no`, `manufacturer_id`, `brand_id`, `claim_batch_period`, `claim_amount`, `approved_total_amount`, `settled_amount`, `unsettled_amount`, `status`, `submitted_at`, `claimed_by`。
  - `status` 建议枚举：`draft` / `submitted` / `partially_settled` / `settled` / `rejected`。
  - **说明**：`policy_claims` 是汇总打包单，不作为垫付主体的唯一归属来源；垫付主体以 `policy_usage_record` 为准。
- **`policy_claim_items` (明细项)**:
  - `claim_id`
  - `source_usage_record_id`: 关联具体的执行明细，实现从财务单据到业务动作的穿透。
  - `declared_amount`: 本项向厂家申报的金额。
  - `approved_amount`: 厂家实际核准金额。
  - `advance_payer_type_snapshot`, `advance_payer_id_snapshot`：可选快照字段，便于对账时保留申报时刻视图。
- **约束规则**：
  - 同一 `source_usage_record_id` 可以出现在多条 `policy_claim_items` 中，用于分批申报。
  - 系统必须按 `source_usage_record_id` 维度校验累计申报金额，防止重复超额申报。

#### 3.2.5 第四层：厂家到账与核销 (settlements & links) —— “资金闭环（厂家 → 公司）”
解决多对多烂账问题：一个到账单可能核销多个 Claim，一个 Claim 也可能分多次到账。
- **`manufacturer_settlements`**: 记录厂家实际打款（如：打入 F 类账户 50,000 元）。
- **`claim_settlement_links` (新增核销表)**:
  - `settlement_id`: 关联打款单
  - `claim_id`: 关联兑付申报单
  - `allocated_amount`: 本次分配核销的金额。
  - **效果**：系统可随时计算某个 Claim 申报了 2 万，已核销 1.5 万，还欠 5 千。
- **部分核销分摊规则**：
  - 当一个 `claim` 仅被部分到账核销时，系统必须将已核销金额继续分摊到其下属 `policy_claim_items`，再回推到 `source_usage_record_id`，作为后续生成 `payment_requests` 的依据。
  - 默认分摊规则建议固定为：**按 `policy_claim_items.approved_amount` 或 `declared_amount` 比例分摊**；若业务上需采用录入顺序优先（FIFO）等其他口径，必须在财务实现阶段固定为唯一规则，禁止同库多套分摊口径并存。
- **AI 辅助规则**：
  - 系统允许 AI 基于 `scheme_no`、品牌、批次、历史分配记录生成**核销建议**。
  - 只有财务确认后，系统才允许真正写入 `claim_settlement_links`，AI 不得直接落库敏感分配结果。

> 说明：`claim_settlement_links` 只代表**厂家对公司**的回款核销闭环，不等于垫付人已经拿回钱。

#### 3.2.6 垫付资金回收闭环 (公司 → 垫付人)
厂家把钱打到公司 F 类账户后，若先前差额是由业务员或其他主体垫付，系统必须继续完成第二段内部财务闭环。
- 当 `claim_settlement_links` 被财务确认，且关联 `policy_usage_record.advance_payer_type = employee` 时：
  - 系统必须自动生成一张 `payment_request`，或写入员工应付报销账本；
  - 由出纳/财务从现金账户或指定结算账户实际付款后，才算该笔垫付彻底闭环。
- 当 `advance_payer_type = company` 时：
  - 厂家到账核销即可视为公司垫付回收完成，无需再生成内部付款。
- 当 `advance_payer_type = customer` 时：
  - 系统应按业务规则生成客户返利、退款或冲应收记录，不得简单视为已闭环。

> 必须区分两个状态：
> 1. **厂家回款状态**：是否已到公司账上；
> 2. **垫付返还状态**：公司是否已把钱还给最终垫付人。
>
> `claim.status = settled` 不代表员工/客户已经实际收回款项。

### 3.3 财务模块

#### 3.3.1 利润核算逻辑 (修正)
不能简单使用“进货价-售价”。必须按以下公式在 `profit_records` 中动态生成：
> **实际单笔利润 = (订单售价 - 实际出库批次成本) + (关联的政策核销到账收益) - (垫付差额) - (执行损耗/实际花费) - (违规罚款)**

> 其中“实际出库批次成本”优先来自条码精确绑定的批次扣减结果；若该批商品未建立条码与批次映射，则按 FIFO 生成 `stock_out_allocations` 后参与核算。

#### 3.3.2 账户联动
- **现金账户 (cash)**：给供应商打款、客户打款收入、违约去外地赎酒打款、员工垫付返还付款。
- **F类账户 (f_class)**：仅接收厂家报销、政策打款，以及抵扣厂家货款。
- **融资账户 (financing)**：独立计息，不计入公司总净资产联动。

#### 3.3.3 应收与应付联动
- 对于账期客户，订单进入 `delivered` 时自动生成 `receivables`，后续通过收款核销推进 `payment_status`。
- 对于员工垫付场景，厂家回款核销完成后自动生成 `payment_requests` 或员工应付账款，由财务完成付款。
- 订单 `completed` 与客户 `payment_status` 独立管理，避免账期客户订单长期卡死。

### 3.4 库存与稽查模块 (批次管理引入)

白酒的串货稽查和主动回购，会导致同一个物理仓库里，放着“885元正常进货”的酒和“700元低价赎回”的酒。

#### 3.4.1 批次与库存 (Inventory)
- `inventory` 表联合主键升级为：`(product_id, warehouse_id, batch_no)`。
- 出入库流水 (`stock_flow`) 强制记录批次号。
- 订单真实成本不以 `order_items.cost_price_snapshot` 为唯一依据，而以 `stock_out_allocations` / `stock_flow` 的批次分配结果为准。

#### 3.4.2 扫码入库与条码绑定
为解决“扫码出库无法反查批次”的问题，入库时需优先建立条码与批次的映射关系。
- 新增 `inventory_barcodes` 映射表，至少包含：`barcode`, `barcode_type`, `product_id`, `warehouse_id`, `batch_no`, `stock_in_id`, `status`, `outbound_stock_flow_id`
- 当入库环节可逐箱扫码时，必须将扫描到的**大箱码**与当前进货批次 `batch_no` 绑定。
- 若后续拿到瓶码与箱码映射，也可补录 `bottle_barcode -> case_barcode -> batch_no` 的追溯关系。
- `inventory_barcodes.warehouse_id` 表示条码**当前所在仓位**，应随调拨、转仓、出库等库存动作同步更新；历史仓位轨迹以 `stock_flow` 为准。

#### 3.4.3 出库扫码与批次扣减
- **优先方案（精确绑定）**：若出库扫描到的条码已存在于 `inventory_barcodes` 且状态为 `in_stock`，系统必须根据条码反查 `batch_no`，并精确扣减对应批次库存。
- **兜底方案（FIFO）**：若该商品历史入库未建立条码与批次绑定，则出库扫码仅用于核对产品与数量；系统按 **FIFO** 自动生成 `stock_out_allocations` 并扣减库存。
- 系统必须记录 `cost_allocation_mode`（如 `barcode_exact` / `fifo_fallback`），以便财务区分成本来源。

#### 3.4.4 扫码稽查与追溯 (扫箱与扫瓶)
**系统逻辑约定**：条码为厂家自带。由于市场稽查既可能拿到大箱码，也可能只拿到小瓶码：
- 提供 `mcp/tools/query_barcode_tracing` 工具。
- 若系统有条码映射，直接反查所属批次、仓库、销售订单、客户和业务员。
- 若系统无瓶码记录，Agent 自动将查获的瓶码推送到【厂家对接外部群】，请求厂家人员协助反查所属箱码，再录入系统追溯原销售订单。

#### 3.4.5 案件处理 (inspection_cases)
- 违约赎回后，商品按“赎回价”作为新批次成本，转入备用仓库。后续再销售时，利润核算自动抓取该赎回成本，避免财务失真。

### 3.5 采购模块

#### 3.5.1 供应商/厂家档案

| 字段 | 类型 | 说明 |
|------|------|------|
| code | 字符串 | 编号 |
| name | 字符串 | 名称 |
| type | 枚举 | supplier（供应商）/ manufacturer（厂家） |
| contact_name | 字符串 | 联系人 |
| contact_phone | 字符串 | 联系电话 |
| address | 文本 | 地址 |
| category | 字符串 | 类别 |
| tax_no | 字符串 | 税号 |
| bank | 字符串 | 开户行 |
| account_no | 字符串 | 银行账号 |
| credit_limit | 数值 | 信用额度 |
| status | 枚举 | active / inactive |

#### 3.5.2 采购订单

| 字段 | 类型 | 说明 |
|------|------|------|
| po_no | 字符串 | 采购单号，唯一 |
| supplier_id | 外键 | 供应商/厂家 |
| warehouse_id | 外键 | 目标仓库 |
| payment_method | 枚举 | supplier_cash / manufacturer_cash_f_class / manufacturer_financing |
| total_amount | 数值 | 总金额 |
| paid_amount | 数值 | 已付款金额 |
| status | 枚举 | pending / approved / paid / shipped / received / completed / cancelled |
| expected_date | 日期 | 预计到货日期 |
| actual_date | 日期 | 实际到货日期 |
| items | 数组 | 采购明细 |

> 说明：当 `supplier_id.type = supplier` 时，`payment_method` 只能取 `supplier_cash`；当 `supplier_id.type = manufacturer` 时，才允许 `manufacturer_cash_f_class` 或 `manufacturer_financing`。

#### 3.5.3 进货工作流

> 进货支持两种入口：
> 1. **预警触发**：安全库存低于阈值后触发补货流程
> 2. **主动发起**：即使没有预警，老板/财务也可以根据经营需要主动发起进货申请

```
入口A：安全库存 < 阈值
    ↓
库存 Agent → 控制中心群推送预警卡片
    ↓
老板/财务发起进货申请

入口B：无预警场景
    ↓
老板/财务主动发起进货申请

两条入口汇合后：
    ↓
财务 Agent → 发起扣款明细（现金+F类 / 纯现金 / 纯F类）
    ↓
确认付款
    ↓
库存 Agent → 待入库设为待办
    ↓
到货扫码入库
    ↓
完成
```

### 3.6 市场稽查与主动清理模块

#### 3.6.1 扫码稽查

- 通过商品唯一条形码或二维码识别异常流转商品
- 支持追溯该商品从入库到客户、再到市场被发现的完整轨迹
- 若发现本公司售出的商品在外地流通，则进入“违约销售”处理流程
- 若发现别的市场货物进入本地，则可进入“主动清理”流程

#### 3.6.2 违约销售

分为两种场景：

**场景A：赎回处理**
- 公司出给烟酒店或团购客户的商品在外地被发现
- 公司需通过现金账户打款给对方，把酒赎回
- 赎回后的货物转入备用库
- 赎回成本可能高于客户实际到手价，需单独核算亏损与罚款

**示例：**
- 出货价 885/瓶
- 客户实际折价到手 650/瓶
- 回收价 700/瓶
- 转入备用库后，该批货成本记为 700/瓶
- 若后续销售价为 650/瓶，则每瓶亏损 50，另需承担罚款

**场景B：返利扣减**
- 例如外地发现 10 箱本公司货物
- 按我方打款价 885/瓶计算货值 53100
- 厂家会扣减等值返利
- 另需承担对应罚款

#### 3.6.3 主动清理

- 若在本地市场发现别的市场货物，可主动低价回购
- 例如按 700/瓶买回 10 箱，总货值 42000
- 回购后该批货物按 885/瓶的厂家货值重新转入主仓库库存
- 后续可再次按本地正常政策销售
- 同时增加相应的销售返利

#### 3.6.4 稽查/清理记录要求

系统需至少支持以下记录字段：
- case_no：案件编号
- case_type：inspection_violation / inspection_redemption / rebate_deduction / market_cleanup
- product_id、barcode/qrcode、batch_no
- found_location、found_time、found_by
- original_order_id、original_customer_id
- recovery_price、manufacturer_price、penalty_amount、rebate_deduction_amount
- into_backup_stock（是否转备用库）
- into_main_warehouse（是否转主仓）
- related_inventory_flow_id
- status：pending / processing / recovered / closed
- notes

#### 3.6.5 inspection_cases 表字段建议

| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | 稽查案件ID |
| case_no | 字符串 | 稽查案件编号，唯一 |
| case_type | 枚举 | inspection_violation / inspection_redemption / rebate_deduction |
| barcode | 字符串 | 商品唯一条码 |
| qrcode | 字符串 | 商品唯一二维码 |
| batch_no | 字符串 | 批次号 |
| product_id | 外键 | 商品ID |
| brand_id | 外键 | 品牌ID |
| found_location | 字符串 | 发现地点 |
| found_time | 日期时间 | 发现时间 |
| found_by | 外键 | 发现人 |
| original_order_id | 外键 | 原销售订单 |
| original_customer_id | 外键 | 原客户 |
| original_sale_price | 数值 | 原销售价 |
| recovery_price | 数值 | 赎回价格 |
| manufacturer_price | 数值 | 厂家打款价/基准价 |
| penalty_amount | 数值 | 罚款金额 |
| rebate_deduction_amount | 数值 | 扣减返利金额 |
| into_backup_stock | 布尔 | 是否转入备用库 |
| backup_stock_cost | 数值 | 转入备用库后的成本 |
| related_inventory_flow_id | 外键 | 关联库存流水 |
| related_payment_id | 外键 | 关联付款记录 |
| status | 枚举 | pending / confirmed / recovered / penalty_processed / closed |
| notes | 文本 | 备注 |
| created_at | 日期时间 | 创建时间 |
| closed_at | 日期时间 | 关闭时间 |

**inspection_cases 状态流转：**

```
pending（发现异常，待确认）
    ↓
confirmed（已确认违约/异常流转）
    ↓
recovered（已赎回或已处理回收）
    └─ 若为返利扣减场景 → penalty_processed（已完成扣减/罚款处理）
    ↓
closed（已归档）
```

#### 3.6.6 market_cleanup_cases 表字段建议

| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | 主动清理案件ID |
| case_no | 字符串 | 清理案件编号，唯一 |
| barcode | 字符串 | 商品唯一条码 |
| qrcode | 字符串 | 商品唯一二维码 |
| batch_no | 字符串 | 批次号 |
| product_id | 外键 | 商品ID |
| brand_id | 外键 | 品牌ID |
| found_location | 字符串 | 发现地点 |
| found_time | 日期时间 | 发现时间 |
| found_by | 外键 | 发现人 |
| buyback_price | 数值 | 回购价 |
| total_buyback_amount | 数值 | 回购总金额 |
| manufacturer_price | 数值 | 按厂家货值重新入主仓的计价 |
| into_main_warehouse | 布尔 | 是否转入主仓库 |
| main_warehouse_id | 外键 | 转入主仓库ID |
| rebate_increase_amount | 数值 | 增加的销售返利 |
| related_inventory_flow_id | 外键 | 关联库存流水 |
| related_payment_id | 外键 | 关联付款记录 |
| status | 枚举 | pending / bought_back / stocked_in / rebate_recorded / closed |
| notes | 文本 | 备注 |
| created_at | 日期时间 | 创建时间 |
| closed_at | 日期时间 | 关闭时间 |

**market_cleanup_cases 状态流转：**

```
pending（发现市场货，待确认）
    ↓
bought_back（已回购）
    ↓
stocked_in（已转入主仓）
    ↓
rebate_recorded（已登记新增返利）
    ↓
closed（已归档）
```

### 3.7 HR模块

#### 3.7.1 员工档案

| 字段 | 类型 | 说明 |
|------|------|------|
| employee_no | 字符串 | 员工编号 |
| name | 字符串 | 姓名 |
| department_id | 外键 | 所属部门 |
| position | 字符串 | 职位 |
| phone | 字符串 | 手机号 |
| open_id | 字符串 | 飞书 open_id |
| hire_date | 日期 | 入职日期 |
| leave_date | 日期 | 离职日期（nullable） |
| status | 枚举 | active / on_leave / left |

#### 3.7.2 KPI指标

| 字段 | 类型 | 说明 |
|------|------|------|
| employee_id | 外键 | 员工 |
| period_type | 枚举 | year / quarter / month |
| period_value | 字符串 | 周期值（如"2026-Q1"） |
| kpi_type | 字符串 | KPI类型 |
| target_value | 数值 | 目标值 |
| actual_value | 数值 | 实际值 |
| score | 数值 | 得分 |

#### 3.7.3 佣金记录

| 字段 | 类型 | 说明 |
|------|------|------|
| employee_id | 外键 | 员工 |
| order_id | 外键 | 关联订单 |
| commission_amount | 数值 | 佣金金额 |
| status | 枚举 | pending / settled |
| settled_at | 时间戳 | 结算时间 |

### 3.8 知识库

- 存储品牌、政策、公司制度文档
- 支持全文检索
- 通过 pgvector 支持向量检索
- **知识库按权限级别分层管理**，不同角色只能查看自己有权限的知识内容

**知识库权限级别建议：**

| 级别 | 代码 | 说明 | 可见角色 |
|------|------|------|----------|
| 全员公开 | public | 公司通用知识，如基础品牌资料、公共流程说明 | 全角色 |
| 内部管理 | internal | 内部制度、经营规则、流程文档 | admin / boss / finance / salesman / warehouse / hr / purchase |
| 部门专属 | department | 仅特定部门可见，如财务制度、仓库SOP、HR制度 | 对应部门角色 |
| 角色专属 | role_based | 按角色控制，如仅财务可看财务知识，仅业务可看销售话术 | 指定角色 |
| 厂家专属 | manufacturer_only | 仅本厂家相关政策、方案号说明、厂家销售动态 | manufacturer_staff + admin / boss |
| 私密文档 | confidential | 高敏感资料，如老板审批说明、特殊政策细则 | admin / boss（必要时指定财务） |

**权限控制规则：**
- 每篇知识文档必须标记 `visibility_level`
- 可选标记 `department_id`、`role_code`、`manufacturer_id`、`brand_id`
- 检索结果必须先过权限过滤，再返回全文或向量召回结果
- openclaw 查询知识库时同样受权限约束，不能越权读取文档
- 厂家人员只能看到所属厂家的政策知识、方案号说明、厂家销售动态等内容

---

## 4. openclaw Skills 与飞书群协作设计

### 4.1 飞书群阵列与隔离

| 群名称 | 成员 | 用途 | 对应 Skill |
|--------|------|------|------------|
| **业务大群** | 内部业务/财务 | 报单、内部审批结果、出库通知 | sales-skill |
| **控制中心群** | 老板/财务主管 | 高级预警、私密微调申请、进货审批 | inventory / finance |
| **【品牌名】厂家对接群** | 内部高管 + **厂家外部人员** + Bot | **跨租户审批**，回填方案号、发布销售动态、对账 | **policy-skill (外部模式)** |

### 4.2 policy-skill (政策技能 - 核心交互设计)
**触发场景 A：外部审批与回填**
1. 内部老板审批了一个带“自定义微调”的青花郎政策申请。
2. `policy-skill` 将卡片推至“青花郎厂家对接群”：“贵司客户张三申请增加 1 场品鉴会，请确认并下发方案号。”
3. 厂家人员点击卡片按钮，弹出飞书表单，输入 `QHL-2026-88`。
4. Agent 接收后更新 ERP 数据库，并转告内部群“厂家已批复”。

**触发场景 B：厂家动态推送**
1. 厂家人员在对接群 @Bot 发送活动海报和文字。
2. Agent 调用 LLM 提炼关键信息（生效期、补贴额），生成结构化【政策动态卡片】。
3. 厂家人员点击“确认下发”后，Agent 将卡片广播至内部业务大群。

> 厂家外部审批、方案号回填、动态下发都属于高敏感跨租户动作，必须同步记录到 `audit_logs`；涉及广播下发的还需记录到 `notification_logs`。

---

## 5. 数据库设计 (核心架构与数据字典)

### 5.1 ER 图概览

```text
users ← user_roles → roles
         ↓
    employees ← departments
manufacturer_external_identities (open_id → manufacturer_id / brand_scope)
         ↓
customers (settlement_mode / credit_days / credit_limit)
         ↓
orders ← order_items ← stock_out_allocations → stock_flow
  ↓                                 ↑
receivables                         │
                                    │
products ← brands → inventory (带 batch_no) → inventory_barcodes (条码 → 批次)

policies → policy_templates
         ↓
policy_requests (来源: 订单/客情/市场活动/手工; order_id可空; customer_id可空)
         ├─→ policy_adjustments
         ├─→ policy_usage_records (执行明细: 事; 含 advance_payer)
         │       ├─→ tasting_wine_usage (品鉴酒流向)
         │       └─→ payment_requests (垫付返还)
         ↓
policy_claims ← policy_claim_items (申报明细: 钱, 关联 usage_records)
         └─< claim_settlement_links >─ manufacturer_settlements (厂家实际到账)
```

### 5.2 核心单据表字段规范 (v1.4 核心重构部分)

#### 5.2.1 policy_request (政策申请总单)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| request_source | 枚举 | `order` / `hospitality` / `market_activity` / `manual` |
| approval_mode | 枚举 | `internal_only` / `internal_plus_external` |
| order_id | 外键 | Nullable；当 `request_source = order` 时必填 |
| customer_id | 外键 | Nullable；非订单场景可空 |
| target_name | 字符串 | 非标准客户主体名称 |
| usage_purpose | 文本 | 申请用途；当 `customer_id` 为空时必填 |
| policy_id | 外键 | 关联政策模板 |
| policy_version_id | 外键/字符串 | 申请时采用的政策版本 |
| policy_snapshot | JSONB | 申请时的关键政策快照 |
| scheme_no | 字符串 | 厂家方案号；标准政策优先取模板预置值，微调/自定义场景由厂家回填 |
| internal_approved_by | 外键 | 老板/高管审批人 |
| manufacturer_approved_by | 字符串 | 外部审批人 `open_id` 或标识 |
| status | 枚举 | `pending_internal` / `pending_external` / `approved` / `rejected` |

#### 5.2.2 policy_usage_records (政策执行明细表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| policy_request_id | 外键 | 归属申请单 |
| benefit_item_type | 枚举 | 权益类型，如 `tasting_event` / `cash_subsidy` |
| usage_scene | 字符串 | 实际执行场景 |
| usage_applicant_id | 外键 | 申请/执行人 |
| planned_amount | 数值 | 预算金额 |
| actual_amount | 数值 | 实际发生金额 |
| reimbursement_amount | 数值 | 可申报金额上限 |
| advance_payer_type | 枚举 | `employee` / `company` / `customer` |
| advance_payer_id | 外键 | 垫付主体 |
| execution_status | 枚举 | `pending` / `in_progress` / `completed` |
| claim_status | 枚举 | `unclaimed` / `partially_claimed` / `fully_claimed` |

#### 5.2.3 policy_claims (兑付申报主单)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| claim_no | 字符串 | 申报单号，唯一 |
| manufacturer_id | 外键 | 申报目标厂家 |
| brand_id | 外键 | 对应品牌 |
| claim_batch_period | 字符串 | 申报批次，如 `2026-04` |
| claim_amount | 数值 | 本次总申报金额 |
| approved_total_amount | 数值 | 厂家累计核准/可确认金额 |
| settled_amount | 数值 | 已被到账核销金额 |
| unsettled_amount | 数值 | 尚未被到账核销的金额 |
| status | 枚举 | `draft` / `submitted` / `partially_settled` / `settled` / `rejected` |
| submitted_at | 时间戳 | 提交时间 |
| claimed_by | 外键 | 提交人 |
| notes | 文本 | 备注 |

#### 5.2.4 policy_claim_items (兑付申报明细表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| claim_id | 外键 | 归属的申报主单 |
| source_usage_record_id | 外键 | **必填**，穿透关联底层执行明细 |
| declared_amount | 数值 | 向厂家申报的金额 |
| approved_amount | 数值 | 厂家实际核准金额（对账后更新） |
| advance_payer_type_snapshot | 枚举 | 可选快照字段 |
| advance_payer_id_snapshot | 外键 | 可选快照字段 |

#### 5.2.5 claim_settlement_links (兑付核销关系表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| claim_id | 外键 | 兑付申请单 ID |
| settlement_id | 外键 | 厂家到账单 ID |
| allocated_amount | 数值 | 本次到账分摊给该 Claim 的金额 |
| confirmed_by | 外键 | 财务确认人 |
| confirmed_at | 时间戳 | 财务确认时间 |
| created_at | 时间戳 | 分摊执行时间 |

#### 5.2.6 inventory_barcodes (库存条码映射表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| barcode | 字符串 | 厂家条码，唯一 |
| barcode_type | 枚举 | `case` / `bottle` |
| product_id | 外键 | 产品 |
| warehouse_id | 外键 | 当前所在仓 |
| batch_no | 字符串 | 对应库存批次 |
| stock_in_id | 外键 | 来源入库单 |
| parent_barcode | 字符串 | 可选，用于瓶码挂箱码 |
| status | 枚举 | `in_stock` / `outbound` / `locked` / `invalid` |
| outbound_stock_flow_id | 外键 | 最终出库流水 |

#### 5.2.7 stock_out_allocations (出库成本分配明细表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| order_item_id | 外键 | 对应订单明细 |
| stock_flow_id | 外键 | 对应出库流水 |
| batch_no | 字符串 | 被扣减的批次 |
| allocated_quantity | 数值 | 从该批次扣减的数量 |
| allocated_cost_price | 数值 | 该批次成本单价 |
| cost_allocation_mode | 枚举 | `barcode_exact` / `fifo_fallback` |

#### 5.2.8 payment_requests (垫付返还付款单)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| source_usage_record_id | 外键 | 来源执行明细 |
| related_claim_id | 外键 | 关联兑付申报单 |
| payee_type | 枚举 | `employee` / `customer` / `other` |
| payee_id | 外键 | 收款对象 |
| amount | 数值 | 待付款金额 |
| status | 枚举 | `pending` / `approved` / `paid` / `cancelled` |
| payable_account_type | 枚举 | 付款账户类型，如 `cash` |
| created_at | 时间戳 | 创建时间 |
| paid_at | 时间戳 | 实际付款时间 |

#### 5.2.9 manufacturer_external_identities (厂家外部身份绑定表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | |
| open_id | 字符串 | 飞书外部人员 open_id，唯一 |
| manufacturer_id | 外键 | 绑定厂家 |
| brand_scope | JSONB / 数组 | 可操作品牌范围 |
| contact_name | 字符串 | 外部联系人姓名 |
| status | 枚举 | `active` / `disabled` |
| last_seen_at | 时间戳 | 最近活跃时间 |
| bound_at | 时间戳 | 首次绑定时间 |

---

### 5.3 基础业务表字段规范 (集成自 v1.0)

#### 5.3.1 财务基础凭证表
**收款记录（receipts）**
| 字段 | 类型 | 说明 |
|------|------|------|
| receipt_no | 字符串 | 收款编号，唯一 |
| customer_id | 外键 | 关联客户 |
| order_id | 外键 | 关联订单 |
| account_id | 外键 | 收款账户 |
| amount | 数值 | 收款金额 |
| payment_method | 枚举 | cash / bank / wechat / alipay |
| receipt_date | 日期 | 收款日期 |
| notes | 文本 | 备注 |

**付款记录（payments）**
| 字段 | 类型 | 说明 |
|------|------|------|
| payment_no | 字符串 | 付款编号，唯一 |
| payee | 字符串 | 收款方 |
| account_id | 外键 | 付款账户 |
| amount | 数值 | 付款金额 |
| payment_type | 枚举 | purchase / expense / refund |
| payment_method | 枚举 | cash / bank / wechat / alipay |
| payment_date | 日期 | 付款日期 |
| notes | 文本 | 备注 |

**费用记录（expenses）**
| 字段 | 类型 | 说明 |
|------|------|------|
| expense_no | 字符串 | 费用编号，唯一 |
| category_id | 外键 | 费用类别 |
| amount | 数值 | 报销金额 |
| payment_account_id | 外键 | 付款账户 |
| reimbursement_account_id | 外键 | 报销到账账户（F类） |
| reimbursement_ratio | 数值 | 报销比例（如120%，表示多报销） |
| actual_cost | 数值 | 实际花费 |
| description | 文本 | 费用说明 |
| applicant_id | 外键 | 申请人 |
| approved_by | 外键 | 审批人 |
| payment_date | 日期 | 付款日期 |
| status | 枚举 | pending / approved / paid / rejected |

#### 5.3.2 市场稽查与清理
**稽查案件（inspection_cases）**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | 稽查案件ID |
| case_no | 字符串 | 稽查案件编号，唯一 |
| case_type | 枚举 | inspection_violation / inspection_redemption / rebate_deduction |
| barcode | 字符串 | 商品唯一条码 |
| batch_no | 字符串 | 批次号 |
| product_id | 外键 | 商品ID |
| found_location | 字符串 | 发现地点 |
| original_order_id | 外键 | 原销售订单 |
| recovery_price | 数值 | 赎回价格 |
| penalty_amount | 数值 | 罚款金额 |
| into_backup_stock | 布尔 | 是否转入备用库 |
| status | 枚举 | pending / confirmed / recovered / penalty_processed / closed |

**主动清理案件（market_cleanup_cases）**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | 主键 | 主动清理案件ID |
| case_no | 字符串 | 清理案件编号，唯一 |
| barcode | 字符串 | 商品唯一条码 |
| product_id | 外键 | 商品ID |
| buyback_price | 数值 | 回购价 |
| total_buyback_amount | 数值 | 回购总金额 |
| into_main_warehouse | 布尔 | 是否转入主仓库 |
| rebate_increase_amount | 数值 | 增加的销售返利 |
| status | 枚举 | pending / bought_back / stocked_in / rebate_recorded / closed |

#### 5.3.3 HR与员工绩效
**员工档案（employees）**
| 字段 | 类型 | 说明 |
|------|------|------|
| employee_no | 字符串 | 员工编号 |
| name | 字符串 | 姓名 |
| department_id | 外键 | 所属部门 |
| position | 字符串 | 职位 |
| phone | 字符串 | 手机号 |
| open_id | 字符串 | 飞书 open_id |
| hire_date | 日期 | 入职日期 |
| status | 枚举 | active / on_leave / left |

**KPI 与 佣金（kpis & commissions）**
| 字段 | 类型 | 说明 |
|------|------|------|
| employee_id | 外键 | 关联员工 |
| period_value | 字符串 | KPI考核周期值（如"2026-Q1"） |
| kpi_type | 字符串 | KPI类型 |
| target_value | 数值 | 目标值 |
| actual_value | 数值 | 实际值 |
| commission_amount | 数值 | 佣金记录表中金额 |
| settled_at | 时间戳 | 结算时间 |

#### 5.3.4 采购模块
**供应商/厂家档案（suppliers）**
| 字段 | 类型 | 说明 |
|------|------|------|
| code | 字符串 | 编号 |
| name | 字符串 | 名称 |
| type | 枚举 | supplier（供应商）/ manufacturer（厂家） |
| contact_name | 字符串 | 联系人 |
| tax_no | 字符串 | 税号 |
| bank | 字符串 | 开户行 |
| account_no | 字符串 | 银行账号 |
| credit_limit | 数值 | 信用额度 |

**采购订单（purchase_orders）**
| 字段 | 类型 | 说明 |
|------|------|------|
| po_no | 字符串 | 采购单号，唯一 |
| supplier_id | 外键 | 供应商/厂家 |
| warehouse_id | 外键 | 目标仓库 |
| payment_method | 枚举 | supplier_cash / manufacturer_cash_f_class / manufacturer_financing |
| total_amount | 数值 | 总金额 |
| paid_amount | 数值 | 已付款金额 |
| status | 枚举 | pending / approved / paid / shipped / received / completed / cancelled |
| expected_date | 日期 | 预计到货日期 |

## 6. 接口与 MCP Tools 清单

### 6.1 常规 API (增删改查)
*保持与原有结构一致，新增以下关联链路接口：*
- `POST /api/manufacturer-settlements/{id}/allocation-preview` (生成到账核销建议，不落库)
- `POST /api/manufacturer-settlements/{id}/allocation-confirm` (财务确认后批量写入 `claim_settlement_links`)
- `POST /api/stock-ins/{id}/bind-barcodes` (为入库批次绑定条码)
- `POST /api/orders/{id}/confirm-delivery` (确认妥投；账期客户自动生成 `receivables`)
- `POST /api/payment-requests/{id}/confirm-payment` (确认垫付返还付款完成)
- `GET /api/inventory/batches` (按批次查询库存与成本)
- `GET /api/profit/order/{order_id}` (获取订单动态综合利润，包含后置政策补贴核销进度)

### 6.2 MCP Tools (openclaw 专属调用)

> 所有 MCP 请求必须强制校验 Header Token。若来自飞书外部群，Token 必须包含特殊的 External 标识与绑定的厂家 ID，防范越权。

| 工具名称 | 职责定位 |
|----------|----------|
| `create_order_from_text` | 解析业务员报单 |
| `submit_policy_approval` | 发起内部双重审批流 |
| `external_approve_and_fill_scheme` | **新增**：供厂家人员确认微调/自定义政策并回填方案号，写入审批审计 |
| `push_manufacturer_update` | **新增**：供厂家人员将外部群消息转发至内部群 |
| `query_barcode_tracing` | 串货查码，若缺失箱码则触发求助流程 |
| `create_policy_usage_record` | 无出货场景下，手工录入执行消耗 |
| `allocate_settlement_to_claims` | AI 生成到账核销建议，需财务确认后才能落库 |

> `allocate_settlement_to_claims` 默认只返回 preview 结果，不直接写入 `claim_settlement_links`；需财务通过 `allocation-confirm` 接口确认后方可生效。

---

## 7. 非功能性需求与技术约束
- **防并发污染**：Agent 会话 (`order_session`) 必须严格绑定 `(chat_id, user_id, 飞书Thread_ID)`，避免多业务员同群并发报单串号。
- PostgreSQL 16+ (深度使用 JSONB 存储政策微调的 DIFF 结构)。
- 接口响应时间 P95 < 500ms。
- **强审计要求**：敏感资金分配、到账核销、厂家外部审批、方案号回填、外部动态广播都必须记录到 `audit_logs`；对外/对群广播动作还需同步写入 `notification_logs`。

---
*文档版本：v1.4 | 状态：封版*