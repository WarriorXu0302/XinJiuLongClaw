# 跨月退货 & 提成追溯 — 业务逻辑参考

本文给 openclaw 智能体在飞书对话中回答"退货了业务员的钱怎么办"、"跨月的单子退了要追回吗"类问题用。
内容是系统的**当前行为 + 未决策的边界场景**，不是执行 TODO。

---

## 现有行为（已上线，定稿）

### Commission 生命周期

```
created(pending) ──月结生成工资单──→ settled(已发工资)
   │
   └──客户申请退货 + admin approve──→ reversed（同一条记录 status 变）
```

**关键字段**：
- `commissions.status` ∈ {`pending`, `settled`, `reversed`}
- `commissions.settled_at` — 仅 status=settled 时填
- `commissions.mall_order_id` — 区分 mall / B2B 来源
- `mall_orders.status`: `completed` → `refunded`（退货 approve 后）

### 退货对 Commission 的影响

| 场景 | 现在行为 | 代码位置 |
|---|---|---|
| commission.status=pending → 退货批准 | status → reversed | `return_service.approve_return:162` |
| commission.status=settled → 退货批准 | status **不变**，只加审计 notes | `return_service.approve_return:167`（注释说明"已 settled 不动"）|

### 退货对 KPI / 利润台账的影响

| 聚合维度 | 时间口径 | partial_closed 处理 | refunded 处理 |
|---|---|---|---|
| `profit_service.aggregate_mall_profit` | delivered_at（partial_closed）/ completed_at（completed）| 纳入，扣 bad_debt | **排除**（`status in [completed, partial_closed]`）|
| 业务员 `stats` 页本月 GMV | 同上 | 纳入 | 排除 |
| admin dashboard 商品/业务员排行 | 同上 | 纳入 | 排除 |

**排除 refunded 意味着**：C 端退款后，上月业务员 KPI 统计里那笔单子**已经算过**；本月不再显示，但**上月历史视图**依然保留（因为报表接口按时间窗口查）。

### 工资单扫描规则

`payroll.generate_salary_records` 扫 Commission 的 filter：
```sql
WHERE Commission.employee_id = ?
  AND Commission.mall_order_id IS NOT NULL
  AND Commission.status = 'pending'
```

所以 `reversed` commission **永远进不了任何月份的工资单** —— 这一层逻辑已经闭环。

---

## 未决策的边界场景

这两个是唯一让 mall 团队还没敢拍板的问题。回答老板时需要先问清楚他的**业务预期**再给方案。

### 场景 A：本月订单 completed → 下月退货批准 ✅ 已决策（方案 2+B）

**老板决定**：跨月退货的提成必须追回；工资不足扣时挂账下月扣。

**实现（migration m6c1）**：
- `commissions` 加 `is_adjustment` + `adjustment_source_commission_id` 两字段
- approve_return（mall + 门店双端）逻辑改：
  - pending → reversed（原逻辑）
  - settled → **建一条负数 Commission**（is_adjustment=True, status=pending, amount=-original, source=original.id）
  - 幂等：同一 Commission 只能产生一条 adjustment
- 下月 payroll.generate_salary_records 自然扫入负数 commission（原 filter `status='pending'` 涵盖）
- 新表 `salary_adjustments_pending` 挂账：
  - 当月 total_pay 扣完所有 commission（含负数）仍 < 0 → 实发 0 + 挂账 shortage
  - 下月生成工资单时优先扣历史挂账（按 created_at 先进先扣）
  - 扣完 settled_in_salary_id 标上，未扣完保留 pending_amount - deduction

**E2E**: `scripts/e2e_cross_month_commission_clawback.py` 覆盖完整链路

### 场景 B：业务员 KPI / 排行榜对已退货订单的追溯

**问题**：
- 上月某业务员 GMV 排第一（100 万）
- 下月 20 万订单被批准退货
- **上月的 GMV 排行页**：现在用时间窗口查，refunded 订单在下月批准时已经 status 变了 → 查时被 filter 排除 → 实际上排行榜里的 GMV **会悄悄变**

**这是 bug 还是 feature？**
- 如果老板用"月度排行"给业务员发奖金 → **已经发出去的奖金**对应的 GMV 数据会变化，造成核对困扰
- 如果老板只看"当月截止日的快照" → 需要另存一份快照表 `mall_monthly_kpi_snapshot`

**可选方案**：
1. **快照固化**：月初 1 号定时任务把上月 KPI 写快照表，排行榜查快照不查实时
2. **双栏展示**：排行榜同时显示"当月初统计"+"当前实时"，让老板看得到差异
3. **不管**：接受下月看到的上月数据会轻微波动

### 场景 C：商品销量 `MallProduct.total_sales` 是否回退

**现状**：
- create_order 时 product.total_sales += quantity？**否，confirm_payment 里 +，partial_close 里 +**
- approve_return 时：**不 -**

**老板可能问**："A 商品销量 1000 瓶，其中 50 瓶退货了，我首页榜单为啥还显 1000？"

**当前语义**：total_sales = "曾经被售卖过的瓶数"，带退货。老板如果要"净销量"得另加字段或改聚合。

---

## 给智能体的回答模板

**用户问：业务员退货的提成要扣吗？**

> 看订单状态：
> - 如果客户**本月下单本月退货**，业务员的提成还在 pending 阶段，系统会自动 reversed，业务员最终拿不到。
> - 如果客户**跨月退货**（上月订单本月退），业务员的提成上月已经 settled 进工资单，现在系统保留不动 —— 公司承担损失。
> 这个跨月场景老板如果想追溯扣回，需要走工资单"提成调整项"人工操作，或者找开发加一个负数 commission 自动机制（工期 1-2 小时）。

**用户问：为什么上月排行榜的 GMV 变了？**

> 因为退货订单 status 会从 completed 变 refunded，排行榜是实时查的，refunded 被过滤掉了。如果希望排行榜数据发出去就别变，可以加一个月初快照表。

**用户问：某业务员本月退了多少单？**

> 走 MallReturnRequest 表查询：`status='approved' AND reviewed_at >= 月初` + 关联 MallOrder 查 assigned_salesman_id。这不是现成端点，但 MCP `query_mall_returns` 或 SQL 可以直接跑。

---

## 版本历史

- 2026-05-03 首版：列出现行逻辑 + 2 个未决场景 + 1 个相关疑点（销量不回退）
