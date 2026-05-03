# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NewERP System (新鑫久隆 ERP) — 多品牌白酒经销 ERP。一个公司下多个品牌事业部（青花郎/五粮液/汾酒/珍十五）独立核算。FastAPI + React/TypeScript + uni-app 小程序。

### 部署拓扑（monorepo, 独立部署）

- **`backend/`** = 所有端的统一后端。ERP 管理台、小程序 C 端、小程序业务员工作台共用一个 FastAPI 进程 + 同一个 PostgreSQL + 同一套 JWT 工具
- **`frontend/`** = React ERP 管理台，独立 npm、独立打包（Nginx 托管），只调 `/api/*`
- **`miniprogram/`** = uni-app Vue 3 小程序，独立 pnpm、独立打包（H5 / 微信小程序 / App），只调 `/api/mall/*`

frontend 和 miniprogram **不共享包管理**，也**不做 pnpm workspace**（Vue 和 React 生态差异大，统一反而麻烦）。后端新功能按端分路由前缀即可：
- ERP 管理台专属 → `backend/app/api/routes/xxx.py`，前缀 `/api/`
- 小程序专属 → `backend/app/api/routes/mall/xxx.py`，前缀 `/api/mall/`
- 共享 service 层（如 attendance / expense_claims）通过 `ActorContext` 对象承接两端调用

### 新 Agent 上手必读

**先读这 4 份文档再动手写代码：**
- `docs/系统架构书.md` — 全系统业务模块 + 资金流 + 权限 + 审批 + 薪资 + 利润台账
- `docs/数据库文档.md` — 61 张表字段说明 + RLS 策略
- `docs/开发文档.md` — 267 个 API 端点 + 开发规范 + 新功能开发流程
- `docs/MCP工具文档.md` — 86 个 AI Agent 工具 + 双认证

### 核心业务规则（速查）

**资金流**：客户回款 → master 现金池；政策/F类到账 → 品牌 F 类账户；工资补贴到账 → 品牌现金；所有付款 → 品牌现金（不够走调拨）。

**三种结算模式**：
- `customer_pay`：客户按指导价全额付 → 公司应收 = 指导价 → 提成按指导价
- `employee_pay`：客户付到手价 + 业务员补差额 → 公司应收 = 指导价 → 提成按指导价
- `company_pay`：客户只付到手价 → 公司应收 = 到手价 → 提成按到手价

**订单闭环**：建单 → 政策审批 → 出库 → 送达 → 上传凭证（每笔建 Receipt + 进 master + 更新 payment_status）→ 全款锁定 → 审批中心确认收款 → completed → 解锁政策兑付

**权限**：PostgreSQL RLS 14 张表强制品牌隔离。双引擎：erp_app（受限）/ erpuser（管理员）。每次 API 请求 SET LOCAL 注入 brand_ids/is_admin 到 PG session。

**薪资**：底薪从 BrandSalaryScheme（品牌×岗位）取。厂家补贴不进工资条（独立走政策应收）。工资审批流：draft → pending_approval → approved → paid。

**稽查**：A1 亏损 = -(回收价 - 到手价) × 瓶数。扣款从品牌现金账户。只有已执行案件才进利润台账。

**利润台账**：11 个科目覆盖销售利润 / 政策盈亏 / 稽查盈亏 / 报销 / 融资利息 / 人力成本。按品牌独立核算。

**仓库调拨**：品牌主仓（`warehouse_type='main' AND brand_id NOT NULL`）**出入都禁**——只能通过采购单入 + 销售订单出。其他仓（ERP 非主 / backup / tasting / 所有 mall 仓）可互相调拨（每瓶扫厂家码过户）。同品牌内免审，跨品牌 / 涉 mall / 跨端必审。桥 B11 详见 `skills/xinjiulong-erp/references/business-atoms-bridges.md`。

**白酒扫码铁律**：每瓶都有厂家防伪码。采购收货 / 业务员出库 / 仓库调拨 —— 全部必须扫码过户，绝不允许按数量散装。

## Development Commands

### Infrastructure (required first)
```bash
docker-compose up -d          # Start PostgreSQL (port 5433) and Redis (port 6379)
```

### Backend (from `backend/`)
```bash
pip install -r requirements.txt                          # Install dependencies
python app/main.py                                       # Run dev server (port 8000)
alembic upgrade head                                     # Apply all migrations
alembic revision --autogenerate -m "description"         # Generate new migration
```

### Frontend (from `frontend/`)
```bash
npm install        # Install dependencies
npm run dev        # Dev server (port 5175, proxies /api and /mcp to localhost:8002)
npm run build      # Type-check then build (tsc -b && vite build)
npm run lint       # ESLint
```

### Miniprogram (uni-app · Vue 3, from `miniprogram/`)
```bash
pnpm install              # 包管理强制 pnpm（preinstall 校验）
pnpm run dev:h5           # H5 开发，浏览器预览（默认 :5173；和 frontend 冲突时按端口依次递增）
pnpm run dev:mp-weixin    # 微信小程序开发编译（输出 dist/dev/mp-weixin，用微信开发者工具打开）
pnpm run build:h5         # H5 生产构建
pnpm run build:mp-weixin  # 微信小程序生产构建
pnpm run lint             # ESLint
```

小程序同一套代码既跑 C 端商城也跑业务员工作台，按 `user_type` 分流。M1–M5 里程碑（plan `rustling-floating-treehouse`）目前只完成了业务员工作台前端骨架（17 个 salesman-* 页），后端 mall_* 路由/表尚未落地。

**Note:** 后端默认跑在 **8002**（`uvicorn app.main:app --port 8002 --reload`）。Vite 代理也默认指向 8002。
不用 8001 是因为常被 SSH 端口转发 / VS Code Plugin Host 占用，会导致前端请求 502 且难以排查。

## Architecture

### Backend (FastAPI + SQLAlchemy 2.0 Async)

**Layered pattern:** Routes (`app/api/routes/`) → Services (`app/services/`) → Models (`app/models/`)

- **Routes** define API endpoints. Each route module is registered in `app/main.py` with a `/api/` prefix.
- **Models** use SQLAlchemy 2.0 declarative style. All models inherit from `Base` in `models/base.py`. Common column types (`StrPK`, `IntPK`, `CreatedAt`, `UpdatedAt`) and all business enums are defined there.
- **Schemas** (`app/schemas/`) are Pydantic models for request/response validation.
- **Config** is via Pydantic Settings loading from `.env` (`app/core/config.py`). Access settings via the `settings` singleton.

**Key patterns:**
- Database sessions: inject via `db: AsyncSession = Depends(get_db)`. Sessions auto-commit on success, auto-rollback on exception.
- Authentication: JWT Bearer tokens. Use `CurrentUser` type alias (from `app/core/security.py`) for authenticated endpoints. The token payload contains `sub` (user ID), `role`, and `brand_ids`.
- Roles (RBAC): `admin`, `boss`, `finance`, `salesman`, `warehouse`, `hr`, `purchase`, `manufacturer_staff` — defined in `UserRoleCode` enum.
- MCP tools endpoint at `/mcp` prefix for Claude Code integration.

### Frontend (React 19 + Vite + TypeScript)

- **UI:** Ant Design v6 components
- **State:** Zustand stores (`src/stores/`) — `authStore` persists JWT tokens and roles to localStorage under key `erp-auth`
- **Data fetching:** TanStack React Query + Axios client (`src/api/client.ts`). The Axios instance auto-attaches the JWT token and redirects to `/login` on 401.
- **Routing:** React Router v7 (`src/router/`)
- **Pages:** Feature-based organization under `src/pages/` (orders, inventory, finance, hr, etc.)
- **Layouts:** `MainLayout` with sidebar navigation, `AuthGuard` for route protection

### Database

- PostgreSQL 16 via Docker (host port **5433** → container port 5432)
- Default credentials: `erpuser` / `erppassword` / database `newerp`
- Migrations managed by Alembic (`backend/migrations/`)
- Redis 7 for caching (port 6379)

## Code Conventions

- Backend: Python 3.10+, async/await throughout, Pydantic v2 for validation
- Frontend: TypeScript strict mode, functional components only, Ant Design for all UI elements
- All business status enums are centralized in `backend/app/models/base.py`
- The project language context is Chinese (UI labels, business terms, docs in `docs/`)

## 必须遵守的开发纪律（血泪教训）

### 1. 改完必须端到端验证，不走完不说"完成"
每次改完一个功能，从业务员建单开始，到财务确认、政策兑付，**完整走一遍**再报完成。不能改一个点就交差——上下游没跑通等于没改。

### 2. 涉及金额/状态的字段，先写注释定义再写逻辑
每个金额字段必须用注释标清：
- 这个字段代表什么（"公司应收"还是"客户应付"？）
- 三种结算模式（customer_pay / employee_pay / company_pay）下分别等于多少
- 谁写入、谁读取

**不定义清楚就动手写 = 必出 bug。**

### 3. SQLAlchemy async `autoflush=False` 下，INSERT 后查 SUM 前必须 flush
`db.add(obj)` 后如果紧接着查同一张表的聚合（SUM/COUNT），新记录还在内存没落库，查出来是旧值。**必须 `await db.flush()` 之后再查。**

### 4. 前端弹窗/详情页禁止用通用 JSON dump
不准用 `Object.entries(data).map(...)` 渲染用户可见的弹窗。每个业务场景必须写专用的 `<Descriptions>` 展示，用中文标签、格式化金额、隐藏 UUID。

### 5. 一个业务动作 = 一个原子接口
"上传凭证 + 登记收款 + 更新付款状态"是一个动作，不要拆成三个接口让前端分别调。拆太碎必然有遗漏。

### 6. 列表/Tab 必须考虑中间态过滤
凡是"待审批""待确认"类的列表，必须想清楚：什么条件的数据该进来、什么条件的不该进来。不能只按一个状态字段过滤——业务流程是多字段联合判定的。

### 7. 禁止偷懒
以下行为全部禁止，出现一次就是事故：
- **复用不该复用的代码**：不同业务场景不能共用"万能渲染"。订单详情和拨款详情不是一回事，不能用同一个 `showDetail` 函数糊弄。
- **字段赋值图省事**：不能因为"反正也差不多"就把两种模式的赋值合并。`employee_pay` 和 `company_pay` 的应收金额不一样，必须分开写清楚。
- **跳过状态流转**：不能因为"先做个简单版"就省掉 payment_status 更新、省掉通知推送、省掉前端锁定。要么一步到位做完整，要么明确告诉用户"这一步还没做"。
- **不写 flush 就查聚合**：每次 INSERT/UPDATE 后面如果有同表查询，必须先 flush。不要抱侥幸心理觉得"ORM 会自动处理"——autoflush=False 就是不会。
- **不验证就报完成**：改完代码后必须自己跑一遍。不是语法检查通过就算完——要用真实数据、真实角色、从头到尾走完业务流程。curl 也好、前端也好，至少走一遍。
- **半成品当成品交**：如果一个功能有 3 步（上传凭证→建 Receipt→更新状态），不能只做了第 1 步就说"做完了"。做不完就说做不完，不要藏着。

### 8. 出错后立刻定位根因再动手
发现 bug 后不要急着改前端或加 if 判断糊弄过去。先查数据库确认数据对不对，再查后端逻辑哪一步没执行到，找到根因后一次性改对。头痛医头的补丁只会制造更多 bug。

### 9. 已理解业务就必须写到位，不准"先简单版后面再补"
你已经完整理解了这个系统的业务逻辑：
- 三种结算模式（客户付/业务垫/公司垫）的资金流和提成规则
- 收款→审批→政策兑付→垫付返还的完整闭环
- RLS 数据隔离 + 角色权限矩阵
- 品牌事业部独立核算 + 总资金池调拨

既然都懂了，写代码时就必须**一次性把完整链路写对**：
- 建订单时三种模式的 customer_paid_amount 各是多少——当场写对，不留"TODO 后面改"
- 上传凭证=建 Receipt+更新状态+判全款+推通知——一个接口全做完，不拆成三次
- 前端页面状态（可编辑/锁定/已完成）——建页面时就考虑全部状态，不是先做"能用"再补"不能用的情况"
- 审批 Tab 的过滤条件——建 Tab 时就把"什么该进、什么不该进"想清楚写上

**"先出个简单版"在这个项目里等于"先出个有 bug 的版本"。用户每次测都能发现问题，说明你偷的每一步懒都被看到了。不要心存侥幸。**

### 10. 每个接口改动前先问自己三个问题
1. **这个动作完成后，数据库里哪些字段会变？** 列出来，确认每个都写了更新逻辑。
2. **前端哪些页面会读这些字段？** 确认它们都能正确响应新值。
3. **上下游闭环通不通？** 这个动作完成后，下一步操作的前置条件满足了吗？（比如：Receipt 建了→payment_status 更新了→审批 Tab 能看到了→财务能确认了→政策兑付解锁了）

三个问题答不上来就不要动手写代码。

### 11. Plan 拆完任务后，每个子任务完成时必须验证和上下游的衔接
大功能拆成小任务是对的，但**完成一个子任务不等于标 completed 往下冲**。每完成一个子任务必须做：
- **向上验证**：这个子任务的输入（上一步的输出）我真的用对了吗？字段名、类型、值域对吗？
- **向下验证**：这个子任务的输出，下一步能直接用吗？下游页面/接口能读到正确的值吗？
- **联调验证**：不是只跑本步骤的语法检查，而是**从整个 plan 的起点跑到当前步骤**，确认串起来是通的。

**典型反例（已犯过的）**：
- 子任务 1 "后端改 customer_paid_amount 赋值" → completed
- 子任务 2 "前端读 customer_paid_amount 显示" → completed
- 但子任务 1 改完没 flush，前端读到的是旧值 → 两个都标了 completed，实际串起来是坏的

**正确做法**：子任务 1 改完，curl 一下建个订单看 DB 里值对不对；子任务 2 改完，前端开个页面看显示的数字对不对。两步都确认了才标 completed。

Plan 拆得再细也不是偷懒的理由。拆开是为了有序推进，不是为了每步都"差不多就行"。

### 12. 需求没想透不动手
用户提了一个需求，不要急着写代码。先把**所有相关场景**列出来（比如三种结算模式各自怎么走），画成表格或流程图给用户确认。用户说"对"了再动手。不要写完一种模式，用户问另一种模式才现想——说明你一开始就没想全。

### 13. 改了写入必须 grep 所有读取方
任何时候改了一个字段的**写入逻辑**（赋值/计算方式），必须全库 `grep` 这个字段名，找出所有**读取方**（后端查询、前端显示、利润计算、提成计算），逐一确认它们是否还能正常工作。改写不改读 = 必出 bug。

### 14. 用户报问题时先查数据再分析
用户发截图说"这个数字不对"，第一反应不是长篇分析业务逻辑，而是：
1. 查数据库这条记录的相关字段值
2. 看后端是哪行代码写入的这个值
3. 定位到根因
4. 再给用户解释 + 修复

**先查证据再下结论，不要凭推测写半天发现方向都错了。**

### 15. 踩过的坑立刻写成硬规矩
每次犯错后必须在本文件里加一条对应的规矩。不靠记忆——下次对话上下文清空了，只有写在这里的规矩才能活下来。同一个错犯两次是不可接受的。

### 16. 每次改动必须更新 CHANGELOG.md
每合并一次改动（push 到 main 或合 PR 后），**立刻**在 `CHANGELOG.md` 的 `[Unreleased]` 节加一行。
格式：`- [#PR号 或 commit 短 hash] 一句话描述（动词开头）` 放在对应分类下（Security / Added / Changed / Fixed / Deprecated / Removed）。
不记 = 下次对话上下文清空就没人知道改了啥。CHANGELOG 是项目记忆，不是可选文档。

---

## 工作方法论：业务原子化 → 织网 → 找病灶

每次做审计 / 排查 / 交付 / review 都按这个框架走，不要临时拍脑袋。

### 第 1 层：原子化

每个业务流切成"原子动作"：
- 一个原子 = 一张表改动 + 副作用 + 通知 + 绑定的代码位置（file:line）
- 状态标记：🟢 done + E2E · 🟡 coded 未 E2E · 🔴 gap · ⚪ n/a
- 沉淀到 `skills/xinjiulong-erp/references/business-atoms-{mall,erp}.md`

### 第 2 层：织网

跨系统/跨域的连接点做成"桥"，每座桥三层看：
1. **数据绑定**（FK / 冗余字段）
2. **动作触发**（A 域动作 → B 域副作用）
3. **状态同步**（A 字段改，B 要不要跟）

沉淀到 `skills/xinjiulong-erp/references/business-atoms-bridges.md`，结尾加全局 🔴 gap 表，按 P0/P1/P2 排序 + 标注 file:line + 估工。

### 第 3 层：找病灶

网铺开后两类问题会显性化：
- 原子 🟡 coded 但未 E2E → 写 `backend/scripts/e2e_*.py` 脚本，造数据 + 跑真实流 + 断言
- 桥 🔴 断了 → 要么补代码（<30min 顺手修），要么转业务决策（记 `business-decisions-pending.md` 给老板/智能体参考）

### 修 gap 的优先级

- **P0 上线阻塞**：业务跑不通、数据不一致风险 → 立刻修
- **P1 合规/数据质量**：跨月/跨域/定时任务场景下会翻车 → 上线后一周内
- **P2 边角**：体验差但不阻塞 → 有空就修
- **<30 min 的顺手修**：审计时就地改掉，别攒

### 修完立刻三件事

1. bridges.md / atoms.md 对应行把 🔴 改成 ✅，注明端点路径或 commit
2. CHANGELOG.md 的 `[Unreleased]` 加一行
3. 如果是代码改动，**跑一次 E2E 脚本**或者手 curl 验完再说"完成"

---

## Review 的两层（交付前必走）

**技术 review 找 bug，业务 review 找 gap**。Bug 从代码里找，gap 从业务网上找。两个一起做，才敢说"这个功能做完了"。

### 技术侧 review（6 个必查项）

| 检查点 | 问自己 | 典型翻车 |
|---|---|---|
| 写入 → 读取闭环 | 改了写入，grep 所有读取方还能读对吗？ | confirm_payment 改了 completed_at，profit_service 按 completed_at 查 partial_closed 订单就查不到 |
| 事务边界 | FOR UPDATE 锁够不够大？手动 rollback 会不会释放锁给并发抢？ | register 里 IntegrityError 后手动 rollback → 并发注册抢同一张邀请码 |
| flush 时机 | INSERT/UPDATE 后同表聚合前有 flush 吗？ | Commission 还没落库就查 SUM，业务员工资虚低 |
| 幂等性 | 重跑不会出问题吗？定时任务手动触发第二次呢？ | job_notify_archive_pre_notice 没去重 → 当天收两条"即将归档"通知 |
| 索引 + 权限 | `WHERE actor_id=?` 查询的字段有索引吗？UNIQUE 约束是业务约束还是只是性能？ | linked_employee_id 没 UNIQUE → 一 employee 被两个 mall 账号绑，commission 归属混乱 |
| 审计留痕 | 涉及金额/状态/权限变更的写操作，有 log_audit 吗？追责能反查吗？ | 管理员换绑推荐人没记 reason → 投诉时追不到根因 |

### 业务侧 review（4 角色换位 + 3 边界场景）

**4 个角色换位走真实流**：

| 角色 | 要走的流 | 典型问题 |
|---|---|---|
| **消费者** | 注册 → 浏览 → 下单 → 收货 → 退货 | 注册后登录看不到已填地址；订单列表状态字符串 vs 数字比较全显"已取消" |
| **业务员** | 抢单 → ship → deliver → 凭证 → 拿提成 → 查 KPI | mall 仓 ship 要求扫码但采购入库没生成条码流程卡死；在途 Tab 漏 shipped 状态 |
| **财务/老板** | 审批凭证 → 看利润台账 → 跨月退货 → 发工资 | 上月发的工资下月客户退货了，那笔钱要不要吐？排行榜 GMV 会不会悄悄变？ |
| **HR/管理员** | 建业务员 → 绑 employee → 换绑 → 停用 | 建错了只能禁用重建；停用后小程序没友好提示就被踢下线 |

**3 个边界场景必问**：
1. **跨域（ERP↔mall）**：A 域动作在 B 域是否自动生效？（employee 停用 → mall 登录拒绝 / 商品下架 → mall 商品是否级联）
2. **跨时间（本月/下月）**：settled 后再发生的变更怎么处理？（退货追溯提成、跨月 KPI 快照、定时任务跑两次）
3. **跨角色并发**：A 角色和 B 角色同时操作同一条数据会出什么？（admin 改派时业务员在 ship、业务员 ship 时管理员 cancel）

### Review 的工具沉淀

| 工具 | 用途 |
|---|---|
| `business-atoms-{mall,erp}.md` | 技术侧：每个端点状态机 + 副作用 + E2E 覆盖率 |
| `business-atoms-bridges.md` | 两侧合一：跨域副作用完整性 + 全局 gap 表 |
| `backend/scripts/e2e_*.py` | 业务侧：造数据跑真实链路每步断言 |
| `business-decisions-pending.md` | 业务侧：边界场景讲清楚给业务方做决策，不是开发替老板拍板 |
| `audit_logs` + `CHANGELOG.md` | 事后 review：出问题时反查"谁何时做了什么改动" |

### 给智能体铺的文档层次

```
skills/xinjiulong-erp/references/
├─ business-atoms-mall.md        ← mall 每个原子的状态
├─ business-atoms-erp.md         ← ERP 每个原子的状态（生产稳定）
├─ business-atoms-bridges.md     ← 桥 + 全局 gap 清单
└─ business-decisions-pending.md ← 业务未决场景（openclaw 飞书智能体读）
```

前三份是"系统此刻的真相快照"，最后一份是"老板会追问但还没定的边界"。

---

## 做任何事之前先问自己

1. 这个改动涉及哪些原子？在业务网上是哪座桥？
2. 改完技术 review 6 项过得去吗？业务 review 4 角色走一遍有问题吗？
3. 有没有 E2E 脚本覆盖？没有就补一个
4. bridges.md / CHANGELOG / decisions 要不要更新？
5. 这是开发能拍板的事，还是要业务方先决策？别替老板做决定
