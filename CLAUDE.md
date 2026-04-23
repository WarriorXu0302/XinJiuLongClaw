# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NewERP System (新鑫久隆 ERP) — 多品牌白酒经销 ERP。一个公司下多个品牌事业部（青花郎/五粮液/汾酒/珍十五）独立核算。FastAPI + React/TypeScript。

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
npm run dev        # Dev server (port 5173, proxies /api and /mcp to localhost:8001)
npm run build      # Type-check then build (tsc -b && vite build)
npm run lint       # ESLint
```

**Note:** The Vite proxy targets port 8001, not 8000. When running both together, start the backend on port 8001 or update `vite.config.ts`.

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
