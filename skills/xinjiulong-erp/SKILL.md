---
name: xinjiulong-erp
description: "新鑫久隆多品牌白酒经销 ERP 的业务操作指南。Agent 以自然语言协助员工完成：(1) 建单、上传凭证、审批收款；(2) 查订单/客户/库存/账户余额；(3) 政策申请/兑付/到账确认；(4) 工资生成/提成结算/厂家补贴到账；(5) 稽查案件登记/执行；(6) 采购单创建/审批/收货。适用场景：员工在飞书/Claude 对话里说『帮我建单』『看一下本月回款』『这单已经打款了』这类自然语言请求。不适用：复杂多品牌资金调拨（老板亲自在审批中心操作）、涉及大额二审的财务动作、任何需要法律意见的场景。"
---

# 新鑫久隆 ERP 业务操作 Skill

Agent 基于这份 skill 用自然语言帮员工操作 ERP 系统。核心原则：**业务逻辑的唯一真相源在后端 API，Agent 只负责把自然语言翻译成 API 调用序列，不要自己算金额。**

## 系统概览

- **多品牌事业部独立核算**：一个公司下多个品牌（青花郎/五粮液/汾酒/珍十五 …），每个品牌自己的现金账户、F 类账户、融资账户。
- **Master 总资金池**：客户回款全部进 master 现金池，然后按需调拨到品牌现金账户。
- **权限模型**：9 个角色（admin / boss / finance / salesman / warehouse / hr / purchase / sales_manager / manufacturer_staff），PostgreSQL RLS 在数据库层强制品牌隔离。

## 基本使用原则（Agent 必须遵守）

### 0. 先绑定身份，用用户**本人**的 JWT 调 ERP

Agent **永远不持有任何固定账号 / 万能 token**。每个员工第一次来对话时：

1. Agent 拿他的 `open_id` 调 `POST /api/feishu/exchange-token`
2. 如果返回 404 未绑定 → 推"绑定 ERP 账号"卡片让**员工本人**填 ERP 用户名 + 密码，提交到 `POST /api/feishu/bind`
3. 绑定成功后再 exchange 拿到**本人**的 JWT（15 分钟 TTL，含 role / brand_ids / user_id）
4. 后续所有 ERP 调用用这个 JWT。过期重新 exchange。

**绝对铁律**：
- ❌ 不用 admin / service account 万能 token 代 salesman 查数据
- ❌ 不跨 open_id 复用 JWT（按 open_id 分桶缓存）
- ❌ 不把 ERP 密码记进 memory / 对话历史（bind 成功立即擦除）
- ❌ 不缓存超过 15 分钟（过期重新 exchange，自动失效离职 / 调岗的旧权限）

这样后端 RLS + RBAC 自动按员工本人权限过滤数据，审计日志 `user_id` 落的是本人 —— 责任归属清楚。详见 `references/business-rules.md` §零。

### 1. 不要替用户做决策性动作

**凡是涉及**金额、状态流转、资金出入、审批**的操作，必须**向用户展示完整信息后等待用户明确确认**（"确认 / OK / 好的"）才能调接口。

**例外**：纯查询（订单列表、余额查看、库存查询）可以直接调。

### 2. 不要自己算金额

前端和后端都会计算金额（应收、政策差、提成）。Agent 不要重算——用对应的 preview 接口（如 `POST /api/orders/preview`）让后端返回，然后原样展示给用户。

### 3. 三种结算模式是核心概念

每单有 `settlement_mode` 字段决定资金如何流动：

| 模式 | 客户付 | 谁垫差额 | 公司应收 | 提成基数 |
|---|---|---|---|---|
| `customer_pay` | 指导价 | 不需要 | 指导价 | 指导价 |
| `employee_pay` | 到手价 | 业务员补差 | 指导价 | 指导价 |
| `company_pay` | 到手价 | 公司让利 | 到手价 | 到手价 |

细节和公式见 `references/settlement-modes.md`。

### 4. 订单闭环的状态流转

```
pending → policy_pending_internal → approved → shipped → delivered → completed
                   ↓                     ↓
              policy_rejected     (拒绝时)
```

配套的 `payment_status`：`unpaid → pending_confirmation → partially_paid → fully_paid`

**关键**：业务员上传凭证**不动账**，只建 `status=pending_confirmation` 的 Receipt；必须财务在审批中心点"确认收款"后才真正进账户、生成提成。详见 `references/receipt-approval.md`。

## 业务模块索引

Agent 根据用户意图加载对应模块。**不要一次加载全部**。

### 总览类（每次会话都该扫读一遍）

| 文件 | 作用 |
|---|---|
| `references/agent-playbook.md` | **30 个场景剧本**：员工说什么 → Agent 怎么做（API 调用序列） |
| `references/business-rules.md` | **硬性业务规则速查**：权限 / 幂等 / 锁 / 校验 / 红线（19 节 + §零 身份隔离） |
| `references/pitfalls.md` | **坑位总结**：过去犯过的 43 个 bug 分类，Agent 绝不能重复 |
| `references/state-machines.md` | 所有业务实体的状态机（Order/Receipt/InspectionCase 等 13 种） |
| `references/field-semantics.md` | 关键字段语义精确定义（customer_paid_amount / comm_base / 等） |
| `references/fund-flows-catalog.md` | 22 个资金流场景（触发 / 金额 / 动账 / 反向 / 幂等） |
| `references/miniprogram-status.md` | **小程序端现状**：哪些 `/api/mall/*` 已接通 / 哪些仍 404，避免盲调 |

### 按业务模块查

| 意图关键词 | 读这个文件 |
|---|---|
| 建单、下单、开单、订单、出库、送达 | `references/orders.md` |
| 上传凭证、收款、确认收款、拒绝凭证 | `references/receipt-approval.md` |
| 客户、建客户、客户明细、客户绑定 | `references/customers.md` |
| 政策申请、政策模板、政策兑付、政策到账 | `references/policies.md` |
| 库存、出入库、低库存、扫码、采购 | `references/inventory-purchase.md` |
| 工资、薪酬方案、提成、厂家补贴 | `references/payroll.md` |
| 稽查、案件、A1/A2/A3/B1/B2、窜货 | `references/inspections.md` |
| 账户、余额、调拨、资金流水、融资 | `references/accounts-finance.md` |
| 审批中心、待审、批准、驳回 | `references/approvals.md` |
| 考勤、打卡、请假、绩效、KPI | `references/attendance-hr.md` |

**结算模式**是跨模块共享概念，独立文件：`references/settlement-modes.md`。
**飞书交互模式**（卡片 JSON 模板、图片接收、update_card）：`references/feishu-interaction.md`。
**全部 API 端点速查**：`references/api-reference.md`。

**辅助脚本** `scripts/`（Agent 可直接 `python3 xxx.py` 或 import）：

| 脚本 | 用途 |
|---|---|
| `feishu_image_to_upload.py` | 飞书图片 → ERP `/api/uploads` 返回 URL |
| `login_and_exchange.py` | open_id → ERP 短期 JWT（含 404 自动引导绑定）|
| `preview_order.py` | 建单前调 `/orders/preview` 拿金额 + 匹配政策 |
| `fetch_approvals.py` | 并发拉 10+ 审批端点，聚合审批中心数据 |
| `match_policy.py` | 按品牌 / 箱数 / 单价匹配政策模板 |

脚本只依赖 `httpx`，纯 Python 3.10+，可直接用。详见 `scripts/README.md`。

## 通用调用模板（所有业务动作）

```
1. 用户自然语言请求
   ↓
2. Agent 识别意图 + 加载对应 references/ 文件
   ↓
3. Agent 收集必要参数（缺了问用户、不要猜）
   ↓
4. Agent 调 preview/list 接口拿到后端计算结果
   ↓
5. Agent 展示结果 + 明确问"确认执行吗？"
   ↓
6. 用户确认 → Agent 调真正的操作接口
   ↓
7. Agent 反馈结果（成功 / 失败 + 原因）
```

**凡是第 5 步用户没明确说"确认"，Agent 绝对不能跳过直接执行。**

## 交互渠道：**一律通过飞书**

本系统的 Agent 交互**只走飞书**（飞书机器人私聊 + 交互式消息卡片）。所有步骤都有对应的飞书交互模式，详见 `references/feishu-interaction.md`。

**关键原则**：
- **信息收集**优先用**飞书消息卡片（Card v2 Form 容器）**，而不是纯文本对话往返——用户在卡片里一次填完多个字段更清晰，Agent 少出错
- **图片/文件上传**：引导用户直接在飞书对话发图片，Agent 收到 `im.message.receive_v1` 事件提取 `image_key`，转为可下载 URL 后 POST 到 ERP `/api/uploads`
- **确认动作**用卡片上的"确认 / 取消"按钮，不依赖用户打字"确认"——避免 Agent 错识别
- **反馈结果**用 `update_card` 把原卡片改成"已提交"状态，而不是新发一条文本消息

详见 `references/feishu-interaction.md`，里面有各场景的卡片 JSON 模板。

## Agent 三种交互模式

### A. 全自动（只读查询）

用户说"查一下我本月回款多少"——Agent 直接调 `GET /api/orders?payment_status=fully_paid&date_from=...&salesman_id=当前用户`，算出总额，**用飞书文本消息**或简单卡片回复。不需要用户确认。

### B. 准备 + 用户确认（写入但无外部依赖）

用户说"给张三烟酒店建一单 5 箱青花郎"——Agent：
1. Agent 查客户 → 查品牌 → 匹配政策模板 → 调 preview 拿到应收 ¥27000
2. **推送飞书卡片**（Form 容器）展示摘要 + "确认建单 / 取消" 按钮
3. 用户点"确认建单"按钮 → 飞书回调 `card.action.trigger` → Agent 调 `POST /api/orders`
4. Agent `update_card` 把卡片改成"已建单 SO-xxx"状态

### C. 需要用户上传材料

用户说"这单打款了，凭证在我手机上"——Agent：
1. 回复文本："请把收款凭证图片直接发给我"
2. 用户在飞书对话里**发图片** → Agent 收 `im.message.receive_v1` 事件，提取 `image_key`
3. Agent 通过飞书 API 下载图片二进制 → POST 到 ERP `/api/uploads`
4. ERP 返回 URL → Agent 推卡片展示摘要："订单 SO-xxx 收款 ¥10000，凭证已上传。[确认登记] [取消]"
5. 用户点"确认登记" → Agent 调 `POST /api/orders/{id}/upload-payment-voucher`
6. Agent `update_card` 改成"已提交，等待财务审批"

## API 认证

所有接口走 JWT Bearer token。

- **飞书场景**：Agent 通过 `/api/feishu/exchange-token` 用 `open_id` 换短期 JWT（15 分钟），调 ERP 业务接口。未绑定的员工 Agent 要引导先调 `/api/feishu/bind` 绑定。
- **Web/Claude Code 场景**：直接用员工登录产生的 JWT。

## 关键禁忌

- ❌ 不要替用户做审批动作（收款审批、政策审批、工资审批）——这些只能在飞书卡片/前端审批中心让有权限的人点按钮
- ❌ 不要在没 preview 接口返回的情况下凭空报告"应收金额"
- ❌ 不要用 MCP 工具（当前 MCP 工具集与前端业务不对齐，已标警告）；所有操作走 `/api/*` 标准接口
- ❌ 不要执行 `DELETE /api/receipts/{id}` 对已 confirmed 的收款——会被后端 400 拒绝（这是对的，Agent 要理解为什么）

## 错误处理约定

当后端返回错误，Agent 应该：

1. **400 业务校验错误**（如"订单状态不对""余额不足"）→ 原样告诉用户 `detail` 字段，**不要自己理解后瞎解释**
2. **401/403 权限错误** → 告诉用户"你的账号（当前角色）没有该操作权限，请联系管理员"
3. **404** → 告诉用户找不到对应记录，确认 ID 是否正确
4. **500** → 告诉用户系统出错，记下时间，建议联系技术
5. **超时/网络** → **不要自动重试**（可能重复动账），问用户是否再试一次

## 时区规则

所有时间 API 返回 ISO-8601 UTC。Agent 对用户展示时**按东八区（北京时间）格式化**：`2026-04-26 10:30:15`。
