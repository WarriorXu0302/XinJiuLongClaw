# 新鑫久隆 ERP

面向多品牌白酒经销业务的企业管理系统。一个公司下多个品牌事业部（青花郎 / 五粮液 / 汾酒 / 珍十五 …）独立核算，统一管理。

## 系统规模

| 指标 | 数量 |
|---|---|
| API 端点 | 267 |
| MCP 工具 | 86（查询 24 + 操作 39 + 审批 17 + 飞书 legacy 6） |
| 数据库表 | 61 |
| 前端页面 | 60 |
| 用户角色 | 9 |
| RLS 保护表 | 14 |
| 利润台账科目 | 11 |

## 功能模块

- **销售** — 订单（指导价强制从政策模板取）、客户、销售目标（三级：公司/品牌/员工，含审批流）
- **政策** — 政策模板、申请、兑付、到账对账（Excel 两轮匹配）、政策应收
- **仓储** — 库存双轨制（数量账 + 条码追溯）、出入库流水、低库存预警、采购订单、收货扫码
- **稽查** — 五种案件类型（A1-A3 外流 / B1-B2 流入）、盈亏自动核算、品牌现金账户扣款
- **财务** — 账户总览、利润台账（11 科目按品牌独立核算）、回款进度、资金往来、报销、融资
- **人事** — 员工、薪酬方案（品牌×岗位底薪模板）、月度工资（自动计算+审批流）、厂家补贴、KPI、佣金、考勤打卡
- **审批中心** — 政策审批、确认收款、请假审批、销售目标审批、工资审批、垫付返还、采购审批、拨款审批、融资还款、稽查案件
- **权限** — PostgreSQL RLS 行级安全（14 张表）+ JWT RBAC + 菜单角色过滤；所有 267 个 API 写入端点均有 `require_role` 权限校验
- **分页** — 所有列表端点统一返回 `{items: [...], total: N}` 服务端分页格式

## 资金流规则

```
客户回款           → master 现金（公司总资金池）
政策 / F类到账     → 品牌 F类账户
工资补贴到账       → 品牌现金账户
付款 / 工资 / 稽查  → 品牌现金账户（余额不足提示调拨）
资金调拨           → master → 品牌现金/融资（需老板审批）
```

### 三种结算模式

| 模式 | 公司应收 | 提成基数 | 全款触发 |
|---|---|---|---|
| customer_pay（客户按指导价付） | 指导价全额 | 指导价全额 | 客户付齐 |
| employee_pay（业务员垫差价） | 指导价全额 | 指导价全额 | 客户 + 业务员凑齐 |
| company_pay（公司垫差价） | 客户到手价 | 客户到手价 | 客户付到手价即可 |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI · SQLAlchemy 2.0 async · Pydantic v2 · Alembic |
| 前端 | React 19 · TypeScript 6 · Vite 8 · Ant Design v6 · React Query · Zustand |
| 数据库 | PostgreSQL 16（RLS 行级安全）· Redis 7 |
| 部署 | Docker Compose |

## 安全设计

- **数据库层**：PostgreSQL RLS 14 张表强制品牌隔离，防 Agent/prompt 注入绕过
- **双引擎连接**：`erp_app`（受限，业务请求用）+ `erpuser`（管理员，迁移/seed 用）
- **JWT**：access + refresh token，载荷含 roles / brand_ids / is_admin / can_see_master
- **应用层**：require_role / can_see_salary / can_see_master 等 helpers
- **前端**：菜单按角色过滤 + AuthGuard 路由守卫

## MCP — AI Agent 工具集

86 个工具让 AI Agent 像人一样操作 ERP，支持双认证：

| 调用方 | 认证 | 安全 |
|---|---|---|
| Claude Code / 外部 Agent | JWT Bearer Token | PostgreSQL RLS 行级安全 |
| 飞书 AI 网关 | X-External-Open-Id | brand_scope 品牌过滤 |

| 类别 | 数量 | 示例 |
|---|---|---|
| 查询 | 24 | 订单/客户/库存/利润/账户/工资/目标/稽查/补贴/考勤/政策模板/品牌/岗位/采购/费用/商品/供应商/资金流/融资/报销/提成/请假/仓库 |
| 操作 | 39 | 建单/编辑订单/提交政策/重新提交/收款/建客户/绑客户品牌/请假/建员工/绑岗位/建账号/生成工资/批量提交工资/发放工资/薪酬方案/生成补贴/确认补贴/资金调拨/编辑客户/采购/费用/稽查/市场清理/销售目标/订单状态/融资/还款/商品/供应商/收货/编辑员工/结算提成/政策模板/政策申请/物料兑付/确认政策到账/确认政策兑付/厂家结算 |
| 审批 | 17 | 审批订单/驳回订单政策/确认收款/完成订单/请假/工资/目标/调拨/拒绝调拨/采购/费用/稽查/融资还款/报销理赔/政策理赔/确认结算分配/创建政策理赔 |
| 飞书 legacy | 6 | 对账分配/条码追溯/政策审批/使用记录/厂家通知/自然语言建单 |

详见 [MCP 工具文档](docs/MCP工具文档.md)。

## 本地开发

### 基础设施

```bash
docker-compose up -d          # PostgreSQL(5433) + Redis(6379)
```

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m app.scripts.seed
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API 文档：http://localhost:8001/docs

### 前端

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173（代理 /api → localhost:8001）
```

### 默认账号

| 用户名 | 密码 | 角色 | 可见范围 |
|---|---|---|---|
| admin | admin123 | 超级管理员 | 全系统 |
| boss | boss123 | 老板 | 全系统 + 审批 |
| finance | finance123 | 财务 | 全品牌，看不到总资金池和工资 |
| salesman | salesman123 | 业务员 | 只看自己 |
| warehouse | wh123 | 库管 | 授权仓库 |

## 核心实体关系

```
Brand（品牌/事业部）
  ├── Account（现金 / F类 / 融资 / 回款）
  ├── BrandSalaryScheme（底薪模板 × 岗位）
  ├── Warehouse（主仓 / 备用 / 品鉴 / 零售 / 批发）
  └── Product（SKU）

Employee ── EmployeeBrandPosition（多品牌兼职，主属品牌决定底薪）

Order（单价=政策模板指导价）
  ├── OrderItem
  ├── PolicyRequest → PolicyRequestItem → PolicyClaim
  ├── Receipt（凭证+金额，进 master）
  └── StockOutAllocation（FIFO 成本溯源）

SalaryRecord（draft→pending_approval→approved→paid）
  ├── SalaryOrderLink（提成订单明细）
  └── ManufacturerSalarySubsidy（pending→advanced→reimbursed）

SalesTarget（approved/pending_approval/rejected）
  └── 三级：company → brand → employee
```

## 项目结构

```
backend/
├── app/
│   ├── main.py               # FastAPI 入口 + 路由注册
│   ├── api/routes/            # 24 个路由模块（267 端点）
│   ├── models/                # 61 张表 SQLAlchemy 模型
│   ├── schemas/               # Pydantic 请求/响应
│   ├── services/              # 审计、通知、政策结算
│   ├── core/
│   │   ├── database.py        # 双引擎 + RLS 上下文注入
│   │   ├── security.py        # JWT + CurrentUser
│   │   └── permissions.py     # 角色判断 + 数据范围
│   └── scripts/seed.py        # 种子数据
├── migrations/                # Alembic（含 RLS policy 迁移）
└── uploads/                   # 文件上传（.gitignore）

frontend/src/
├── api/client.ts              # Axios（JWT 自动注入 + 401 跳转）
├── stores/                    # authStore（权限 hooks）/ brandStore
├── layouts/                   # MainLayout（固定侧栏+角色菜单）/ AuthGuard
├── router/index.tsx           # 60 个路由
└── pages/                     # 15 个业务目录
    ├── orders/    (4)     ├── finance/     (11)
    ├── hr/        (9)     ├── policies/    (8)
    ├── inventory/ (7)     ├── approval/    (2)
    ├── attendance/(2)     ├── customers/   (2)
    ├── inspections/(2)    ├── purchase/    (2)
    └── ...
```

## 文档

- [系统架构书](docs/系统架构书.md) — 业务模块、资金流、权限体系、审批中心、薪资、利润台账
- [数据库文档](docs/数据库文档.md) — 61 张表字段说明、RLS 策略、索引
- [开发文档](docs/开发文档.md) — API 端点清单、开发规范、新功能开发流程
- [MCP 工具文档](docs/MCP工具文档.md) — 86 个 AI Agent 工具、双认证、bridge 超时处理、调用示例

## 授权

Proprietary — 仅限新鑫久隆内部使用。
