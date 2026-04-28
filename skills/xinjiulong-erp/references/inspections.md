# 稽查案件（5 种场景）

**业务背景**：白酒行业"窜货"是最头疼的问题——客户买了酒没卖到自己的市场，跑到外省低价销售，扰乱市场。公司要监控条码追溯，发现后走稽查流程追责/回收。

## 5 种案件类型

`case_type` 字段决定场景（不要与旧的 INSPECTION_VIOLATION 等枚举混淆，**以下是当前模型**）：

| case_type | direction | 含义 | 盈亏公式 |
|---|---|---|---|
| `outflow_malicious` | outflow | A1 **恶意外流** 客户故意窜货 | `-(回收价 - 到手价) × 瓶数 - 罚款` |
| `outflow_nonmalicious` | outflow | A2 **非恶意外流** 客户无意中转卖 | `+(指导价 - 回收价) × 瓶数 - 罚款` |
| `outflow_transfer` | outflow | A3 **被转码** 酒被转手码，扣回款抵 | `-罚款` |
| `inflow_resell` | inflow | B1 **回售入库** 找到被窜酒买回来再卖 | `+(回售价 - 买入价) × 瓶数 + 奖励` |
| `inflow_transfer` | inflow | B2 **转码入库** 找到酒打码转入主仓 | `+(指导价 - 买入价) × 瓶数 + 奖励` |

**Agent 理解**：A 系列是"发现我方酒跑到别处了"，B 系列是"把别处的酒搞回自家"。

## 字段对应

```
case_no             自动生成 IC-YYYYMMDDHHMMSS-<6char>
case_type           上表之一
direction           outflow / inflow
barcode / batch_no  条码/批次（从现场扫码而来）
product_id          哪个产品
brand_id            哪个品牌
original_order_id   源订单（A 系列知道哪单跑的）
original_customer_id 源客户（谁的货跑了）
original_sale_price 指导价
deal_unit_price     到手价（原本卖客户的价）
recovery_price      回收价（我们花多少买回来）
purchase_price      买入价（B 系列的买入成本）
resell_price        回售价（B1 卖出去的价格）
transfer_amount     A3 被转码扣除的金额
penalty_amount      对客户的罚款
rebate_deduction_amount 返利扣款（从政策应收扣）
reward_amount       给发现人的奖励
quantity            瓶数（或箱数，看 quantity_unit）
quantity_unit       瓶 / 箱
profit_loss         系统计算的盈亏（不要前端传，后端算）
voucher_urls        JSONB 数组，证据图片
```

## Agent 场景 1：建案件

**权限**：boss / finance。稽查员（salesman 角色）不能直接建，要报告给上级。

```
POST /api/inspection-cases
{
  "case_type": "outflow_malicious",
  "direction": "outflow",
  "brand_id": "<品牌 id>",
  "product_id": "<产品 id>",
  "barcode": "<条码>",
  "batch_no": "<批次>",
  "quantity": 2,
  "quantity_unit": "箱",
  "found_location": "云南昆明某超市",
  "found_time": "2026-04-26T14:30:00Z",
  "found_by": "<稽查员 employee id>",
  "original_order_id": "<源订单 id>",       // 通过 barcode 追溯查到
  "original_customer_id": "<源客户 id>",
  "original_sale_price": 900,                // 自动取原单指导价
  "deal_unit_price": 650,                    // 到手价
  "recovery_price": 700,                     // 花 700/瓶回收
  "penalty_amount": 10000,                   // 客户挨罚 1 万
  "voucher_urls": ["/api/uploads/files/..."],
  "notes": "客户李四把货拉到云南"
}
```

后端做的事：
- `case_no` 自动生成
- `profit_loss` 后端权威计算（忽略前端传的），公式见上表
- A3/B2 如果带 `brand_id`，立刻扣/加 `payment_to_mfr` 账户余额 + 写 fund_flow

### Agent 引导流程

1. 用户："我在昆明发现了窜货，条码 ABC123，两箱"
2. Agent 先调 `GET /api/inventory/barcode-trace/ABC123` 查历史 → 拿到 original_order_id / customer_id / sale_price / deal_price
3. Agent 问用户：
   - 这是恶意的还是不知情的？→ 决定 outflow_malicious vs outflow_nonmalicious
   - 回收价多少？
   - 罚款多少？
4. Agent 卡片展示完整摘要 + "确认建案"按钮
5. 用户确认后调接口，返回 case_id

## Agent 场景 2：执行案件（动账 + 库存）

建完是 `pending`，要"执行"后才真正动账/库存：

```
POST /api/inspection-cases/{case_id}/execute
```

后端做的事（按 case_type 分）：

### A1 outflow_malicious（恶意外流）

- **不回仓**（客户恶意，产品视为市场流失）
- 扣品牌现金账户 `= 回收价 × 瓶数`（公司花钱回收的）
- 如果 `no_rebate=false`，扣源订单政策应收 = `rebate_deduction_amount`

### A2 outflow_nonmalicious（非恶意外流）

- **回主仓**（产品回收后进正常销售）
- 扣品牌现金账户 `= 回收价 × 瓶数`
- 从源订单的政策应收扣 `rebate_deduction_amount`

### A3 outflow_transfer（被转码）

- **不动库存**（产品已经被别人转了）
- 建案时已扣 `payment_to_mfr` 账户（见场景 1）

### B1 inflow_resell（回售入库）

- **入备用仓**（备用仓库待回售）
- 扣品牌现金账户 `= 买入价 × 瓶数`

### B2 inflow_transfer（转码入库）

- **入主仓**
- 扣品牌现金账户 `= 买入价 × 瓶数`
- 建案时已加 `payment_to_mfr` 账户

### Agent 告诉用户的

"执行案件 IC-xxx 会：
- 从 {品牌} 现金账户扣 ¥Y（回收成本）
- {A2: 2 箱酒回主仓；A1: 不回仓；B1: 入备用仓；B2: 入主仓}
- 预估盈亏 ¥Z
确认执行？"

## Agent 场景 3：A1/A2 回仓（单独按钮）

A1 默认不回仓，如果改主意要回仓可以单独调：

```
POST /api/inspection-cases/{case_id}/recover-to-stock
{ "target_warehouse_id": "<主仓 id>", "cost_per_bottle": 650 }
```

把 A1 或 A2 的库存补进来。

## Agent 场景 4：查案件

```
GET /api/inspection-cases?brand_id=X&case_type=outflow_malicious&status=pending&skip=0&limit=20
```

Agent 给 boss / finance 展示本月案件列表。

### 详情

```
GET /api/inspection-cases/{id}
```

Agent 展示：基本信息 + 图片 + 预估盈亏 + 操作按钮（执行 / 回仓 / 改）。

## 清理案件（市场扫货）

另一套表 `market_cleanup_cases`，表示**主动**去市场扫（买回）竞品或自家漂货。

```
POST /api/cleanup-cases
POST /api/cleanup-cases/{id}/stock-in           入库
```

流程类似稽查 B1，但性质不同（主动 vs 被动）。Agent 很少主动涉及，只在 boss 明确要求时引导建单。

## 常见错误

| detail | 解释 |
|---|---|
| "case_type 不是合法枚举值" | 传错字段 |
| "原订单找不到" | original_order_id 错或不在 RLS 可见范围 |
| "品牌现金账户余额不足" | 执行时账户不够，先调拨 |
| "已执行的案件不能删除" | 已动账不可逆 |
| "找不到备用仓/主仓" | 该品牌没配相应仓库 |

## 数据可见性（RLS）

`inspection_cases` 表的 RLS：
- salesman / sales_manager：只能查到他们绑定的品牌且自己是 `found_by` 的案件（敏感信息需保密）
- finance / boss / admin：查全部
- warehouse：查自己仓库涉及的

## Agent 推通知场景

- 执行成功 → 推卡片给 boss："案件 IC-xxx 已执行，盈亏 ¥Y"
- `rebate_deduction_amount > 0` → 推给 finance："需从政策应收扣 ¥X"
- A1 大额罚款（>1 万）→ 推给 boss 二审

## 利润台账关联

**只有已执行的案件**才进 `dashboard/profit-summary` 的"稽查盈亏"科目。pending 的不算。

## 注意：场景冲突

如果同一 barcode 被建过一个案件（status != closed），再建新案会报错。Agent 先查：

```
GET /api/inspection-cases?barcode=ABC123
```

有 pending 就提示用户"该条码已有未关闭案件 IC-xxx，请先处理"。
