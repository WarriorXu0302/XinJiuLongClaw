"""
利润台账回写服务。

规则：
  - 触发时机：订单 completed 或 partial_closed 时
  - 收入 = pay_amount（**实收金额**，不是 total_amount）
  - 成本 = SUM(order_items.cost_price_snapshot × quantity)
  - 运费成本 = shipping_fee（单列扣项）
  - 提成 = 同 order 的 commissions 总额（commission_service 先算）
  - 净利润 = 收入 - 成本 - 运费 - 提成
  - partial_closed 单：pay_amount 走 mall_sales_profit；未收额走 mall_bad_debt 科目
  - 按 items.brand_id 分组，每品牌一行 profit_ledger
  - 幂等：profit_ledger_posted 标志

**执行顺序**：commission_service 先 → profit_service 后（profit 读 commission 合计）
"""
# TODO(M4):
# async def post_order_to_profit_ledger(db, order: MallOrder) -> None: ...
