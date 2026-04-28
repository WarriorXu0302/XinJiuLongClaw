# 订单模块 — 建单到送达完整闭环

覆盖：建单、政策审批、出库、送达、上传凭证。收款审批见 `receipt-approval.md`。

## 状态机

```
pending  ─(salesman 提交政策)→  policy_pending_internal
                                      ↓
                               (boss 批准)  → approved
                               (boss 驳回)  → policy_rejected
                                      ↓
                             (warehouse 出库)  → shipped
                                      ↓
                           (warehouse 上传送货照)  → delivered
                                      ↓                       ↑
                           (凭证+财务审批流程)              |
                                      ↓                       |
                                  completed                  |
                                (policy_rejected  ─ salesman resubmit)
```

**Agent 对应的 API**：

| 动作 | 端点 | 角色 |
|---|---|---|
| 建单预览（算金额/匹配政策） | `POST /api/orders/preview` | 任何登录员工 |
| 建单 | `POST /api/orders` | salesman/sales_manager/boss |
| 提交政策审批 | `POST /api/orders/{id}/submit-policy` | salesman/sales_manager |
| 批准政策 | `POST /api/orders/{id}/approve-policy` | boss |
| 驳回政策 | `POST /api/orders/{id}/reject-policy` | boss |
| 重新提交（被驳回后） | `POST /api/orders/{id}/resubmit` | salesman/boss |
| 出库 | `POST /api/orders/{id}/ship` | warehouse/boss |
| 上传送货照片 | `POST /api/orders/{id}/upload-delivery` | warehouse/boss |
| 上传收款凭证 | `POST /api/orders/{id}/upload-payment-voucher` | salesman/finance/boss |
| 查看订单 | `GET /api/orders/{id}` 或 `GET /api/orders` | 按 RLS 过滤 |
| 订单利润 | `GET /api/orders/{id}/profit` | finance/boss |
| 删除订单 | `DELETE /api/orders/{id}` | 仅 pending 状态可删；已过政策审批的禁止删 |

## 建单流程 — Agent 分步

### 第一步：收集必填参数（Agent 问用户）

**用户必须提供**：
- 客户（名字或编号，Agent 查 `GET /api/customers?keyword=...`）
- 品牌（一般从商品自动推断）
- 商品 + 数量（每条：product_id + quantity + quantity_unit='箱'）
- 结算模式（`customer_pay` / `employee_pay` / `company_pay`）— 必须明确问，**不要默认**

**可选**：
- 到手单价（`deal_unit_price`）覆盖政策模板默认值
- 备注

**关键校验**：
- 业务员（salesman 角色）不能给未绑到自己名下的客户建单——Agent 先用 `GET /api/customers` 确认客户可见（RLS 会挡住不该看的）
- 必须有已启用的政策模板匹配（品牌 × 箱数 × 到手价）——调 `GET /api/policy-templates/templates/match?brand_id=X&cases=N&unit_price=P` 先确认

### 第二步：预览（Agent 调 preview 不用用户确认）

```
POST /api/orders/preview
{
  "customer_id": "...",
  "salesman_id": "...",
  "settlement_mode": "customer_pay",
  "items": [{"product_id": "...", "quantity": 5, "quantity_unit": "箱"}],
  "policy_template_id": "..."    // 可空，后端自动匹配
}
```

返回金额（参见 `settlement-modes.md`）。

### 第三步：展示 + 用户确认

Agent 用大白话重复：

> 将建订单：
> - 客户：张三烟酒店
> - 品牌：青花郎
> - 商品：青花郎 53 度 500ml × 5 箱
> - 结算：客户按指导价付
> - 公司应收：¥27,000
> - 匹配政策：青花郎 5 箱基础政策（含赠品 1 箱）
>
> 确认建单？

### 第四步：建单（用户"确认"后）

```
POST /api/orders
{ 同 preview 的参数 }
```

返回 `order_no`（如 `SO-20260427091234-abc123`）告诉用户。

### 第五步：自动提交政策审批（可选）

建单后订单是 `pending`，**Agent 询问用户**是否立即提交政策审批：

> "订单建好了（SO-xxx）。要立刻提交政策审批吗？"

用户"是" → `POST /api/orders/{id}/submit-policy` → 进入 `policy_pending_internal`。

**Agent 不自动提交**——让用户有机会先检查再提。

## 接下来的流转 Agent 不介入

- **政策审批**：只能 boss 在前端点按钮或通过 `/api/orders/{id}/approve-policy` 端点。Agent 若是 boss 的 Agent，**必须展示完整订单摘要后要用户确认**。
- **出库**：warehouse 扫码流程，Agent 一般不做，提示用户"请在仓库扫码页面出库"
- **送达上传照片**：warehouse 完成，Agent 不做

## Agent 可以帮的"查询"类

| 用户问法 | Agent 调 |
|---|---|
| "我有哪些订单在等审批？" | `GET /api/orders?status=policy_pending_internal` |
| "这单到哪一步了？" | `GET /api/orders/{id}` 看 status + payment_status |
| "本月我建了多少单？" | `GET /api/orders?salesman_id=me&date_from=...&date_to=...` 聚合 |
| "张三烟酒店有哪些未付款订单？" | `GET /api/orders?customer_id=X&payment_status=unpaid` |

## 常见错误码

| HTTP | detail | Agent 怎么说 |
|---|---|---|
| 400 | "settlement_mode 必须为 ..." | 重新问用户模式 |
| 400 | "无法出库：该订单没有已审批的政策申请" | 告诉用户先完成政策审批 |
| 400 | "订单状态为 'X'，只有..." | 原样告诉用户 |
| 403 | （RLS 挡住） | "你看不到该订单，可能不在你绑定的品牌范围内" |

## 订单状态中英对照（给用户说话用）

| status | 中文 |
|---|---|
| pending | 待提交（新建） |
| policy_pending_internal | 内部审批中 |
| policy_pending_external | 厂家审批中 |
| approved | 已审批（待出库） |
| shipped | 已出库 |
| delivered | 已妥投 |
| completed | 已完成 |
| policy_rejected | 已驳回 |

| payment_status | 中文 |
|---|---|
| unpaid | 未付款 |
| partially_paid | 部分付款 |
| pending_confirmation | 凭证已交，待财务审批 |
| fully_paid | 已付清 |
