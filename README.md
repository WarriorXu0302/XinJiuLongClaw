# 新鑫久隆 ERP

面向多品牌白酒经销业务的企业管理系统。一个公司下多个品牌事业部（青花郎 / 五粮液 / 汾酒 / 珍十五 …）独立核算，统一管理。

## 功能模块

- **销售订单** — 下单、政策匹配、出库、回款、利润计算
- **政策管理** — 政策模板、客户申请、厂家审批、到账对账、理赔结算
- **库存管理** — 主仓/备用仓/门店仓、条码追溯、FIFO 成本分配
- **财务** — 多账户体系（总资金池 / 品牌现金 / F类 / 融资）、资金调拨、报销、利润台账
- **采购** — 采购单、审批、到货扫码
- **人事 / 薪资** — 员工、品牌岗位、薪酬方案、月度工资、考勤、KPI、厂家工资补贴
- **稽查** — 窜货案件、市场清理、盈亏核算
- **权限** — JWT + RBAC + 品牌数据范围隔离

## 资金流规则

```
客户回款           → master 现金（公司总资金池）
政策 / F类到账     → 品牌 F类账户
工资补贴到账       → 品牌现金账户
付款 / 工资发放    → 品牌现金账户（余额不足走资金调拨）
```

## 技术栈

- **后端**：FastAPI · SQLAlchemy 2.0 async · Pydantic v2 · Alembic
- **前端**：React 19 · TypeScript · Vite · Ant Design v6 · TanStack React Query · Zustand
- **基建**：PostgreSQL 16 · Redis 7 · Docker

## 本地开发

### 准备基础设施

```bash
docker-compose up -d          # PostgreSQL(5433) + Redis(6379)
```

### 后端（`backend/`）

```bash
pip install -r requirements.txt
alembic upgrade head                   # 应用数据库迁移
python -m app.scripts.seed             # 初始化角色/员工/品牌/商品/客户
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API 文档：http://localhost:8001/docs

### 前端（`frontend/`）

```bash
npm install
npm run dev                            # http://localhost:5173
```

> 前端 Vite 代理 `/api` 和 `/mcp` 指向 `localhost:8001`。

### 默认账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 超级管理员 |
| boss | boss123 | 老板 |
| finance | finance123 | 财务 |
| salesman | sales123 | 业务员 |
| warehouse | wh123 | 库管 |

## 核心实体关系

```
Brand ── BrandSalaryScheme ── EmployeeBrandPosition ── Employee
         (品牌×岗位底薪模板)    (员工兼职多品牌)

Order ── OrderItem ── StockOutAllocation ── InventoryBarcode
  │
  ├── PolicyTemplate（指导价 + 客户到手价）
  ├── PolicyRequest ── PolicyRequestItem ── PolicyClaim
  └── Receipt ── Account(master cash)

SalaryRecord ── SalaryOrderLink
           └── ManufacturerSalarySubsidy
```

## 项目结构

```
backend/
├── app/
│   ├── api/routes/       # FastAPI 路由 (~22 个业务模块)
│   ├── models/           # SQLAlchemy 模型
│   ├── schemas/          # Pydantic 请求/响应
│   ├── services/         # 业务服务（审计、通知、政策结算）
│   ├── core/             # 配置、数据库、安全、权限
│   └── scripts/          # 种子数据、运维脚本
├── migrations/           # Alembic 迁移
└── uploads/              # 文件上传目录（.gitignore）

frontend/
└── src/
    ├── pages/            # 业务页面（orders/policies/finance/hr/…）
    ├── layouts/          # 布局与路由守卫
    ├── router/           # 路由注册
    ├── stores/           # Zustand 状态（auth、brandFilter）
    ├── api/client.ts     # Axios 实例（自动注入 JWT）
    └── utils/            # 工具函数
```

## 业务约定

- **订单单价**：按政策模板 `required_unit_price`（指导价），不允许业务员手工填写
- **客户到手价**：按政策模板 `customer_unit_price`，可在订单上微调
- **结算模式**：
  - `customer_pay` — 客户按指导价结账（业务员赚政策差）
  - `employee_pay` — 业务员垫付差额（政策到账后返还给业务员）
  - `company_pay` — 公司垫付差额（政策到账留公司毛利）
- **提成基数**：
  - `customer_pay` / `employee_pay` → 按指导价
  - `company_pay` → 按客户到手价

## 授权

Proprietary — 仅限新鑫久隆内部使用。
