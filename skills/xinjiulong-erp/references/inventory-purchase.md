# 库存与采购

## 库存双轨制

- **数量账**（`inventory` 表）：按 product × warehouse × batch_no 聚合，记瓶数
- **条码追溯**（`inventory_barcodes` 表）：每瓶酒一条，附带追溯历史

**一般场景**库存增减走数量账；**高端酒/产品**可启用条码追溯（销售出库时扫码）。

## 仓库类型

| type | 含义 | 典型用途 |
|---|---|---|
| main | 主仓 | 正常销售出库 |
| backup | 备用仓 | 周转备用 |
| retail | 零售仓 | 小批零售 |
| wholesale | 批发仓 | 大宗批发 |
| tasting | 品鉴仓 | 品鉴酒、营销试饮 |

## Agent 场景 1：查库存

```
GET /api/inventory/batches?brand_id=X&product_id=Y&warehouse_id=Z
```

Agent 展示：`青花郎53度500ml — 主仓库 120 瓶`。

### 低库存预警

```
GET /api/inventory/low-stock?threshold=5    // 小于 5 箱（默认）
```

返回低于阈值的 SKU。Agent 主动告诉相关品牌的 warehouse / boss。

### 条码追溯

```
GET /api/inventory/barcode-trace/{barcode}
```

返回一瓶酒从入库到当前位置的完整历史（采购入库 → 政策出库 → 客户 → 稽查回收 → ...）。用户扫码后 Agent 展示历史链。

## Agent 场景 2：直接出入库（手工调整）

**手工直接入库**（比如老板转赠、非标来源）：

```
POST /api/inventory/direct-inbound
{
  "product_id": "...",
  "warehouse_id": "...",
  "quantity": 10,
  "quantity_unit": "箱",
  "batch_no": "...",      // 可选
  "notes": "原因"
}
```

**手工出库**（非订单/非稽查的出库，如损耗）：

```
POST /api/inventory/direct-outbound
{
  "product_id": "...",
  "warehouse_id": "...",
  "quantity": 1,
  "quantity_unit": "瓶",
  "notes": "破损"
}
```

Agent 在让用户操作之前**强烈提醒**："直接出入库不走正常业务流，会影响利润台账，请确认有授权"。只对 warehouse/boss 开放。

## Agent 场景 3：出入库流水

```
GET /api/inventory/stock-flow?type=policy_out&warehouse_id=X&date_from=...
```

`type`（StockFlow 类别）：
- `purchase_in` 采购入库
- `order_out` 订单出库
- `policy_out` 政策物料出库
- `return_in` 退货入库
- `transfer_in/out` 转仓
- `direct_in/out` 手工调整
- `inspection_in/out` 稽查回收/出库
- `tasting_out` 品鉴酒消耗

## 采购单流程

```
建单 (pending) 
  → boss/finance 审批 (approved)  
  → 扣账户（cash_amount + f_class + financing）
  → paid
  → warehouse 收货（/receive）
  → received
  → 扣销售 brand 的 payment_to_mfr（代表应付已结）
```

## Agent 场景 4：建采购单

```
POST /api/purchase-orders
{
  "po_no": "自动生成",
  "brand_id": "...",                    // 可为 null=跨品牌总公司采购
  "supplier_id": "<厂家 supplier id>",
  "warehouse_id": "<目标仓>",
  "cash_amount": 50000,                 // 用现金付
  "f_class_amount": 0,                  // 用 F 类付
  "financing_amount": 0,                // 融资付
  "cash_account_id": "...",             // 对应账户
  "items": [
    { "product_id": "...", "quantity": 100, "unit_cost": 500 }
  ]
}
```

**关键**：`cash_amount + f_class_amount + financing_amount` 要和 `SUM(items.quantity * unit_cost)` 对得上，前端会校验（浮点精度容错 0.01）。

Agent 收集参数后**卡片展示完整摘要**，用户确认再调。

## Agent 场景 5：采购审批

```
POST /api/purchase-orders/{id}/approve
```

boss/finance 调。后端：
- cash_account.balance -= cash_amount + 写 fund_flow
- f_class_account.balance -= f_class_amount + 写 fund_flow
- financing_account.balance -= financing_amount + 写 fund_flow
- status → `paid`
- payment_to_mfr 账户 += cash_amount + financing_amount（代表"已付给厂家"）

如果某账户余额不足 → 400，告诉用户"XXX 账户余额不足 ¥YYY"。

## Agent 场景 6：采购撤销（关键安全点）

```
POST /api/purchase-orders/{id}/cancel
```

**Bug #4 修复后**：后端用 `SELECT FOR UPDATE` 锁 `payment_to_mfr` 账户 + 校验余额足够。余额不足时 400（用户确认已结算过部分 → 需联系财务）。

Agent 告诉用户："撤销采购会退钱到原账户。如果期间有其他操作导致余额不足，系统会拦截。"

## Agent 场景 7：收货

```
POST /api/purchase-orders/{po_id}/receive
{
  "received_items": [
    { "po_item_id": "...", "actual_quantity": 100, "batch_no": "...", "barcodes": ["..."] }
  ]
}
```

warehouse 扫码或手工录入。后端：
- 增库存（StockFlow 类型=`purchase_in`）
- 如果启用条码追溯，批量导入 `inventory_barcodes`
- PO.status → `received`

Agent 一般不主动做收货（需要扫码器），提示用户"请在仓库扫码页面完成"。

## 常见错误

| detail | 解释 |
|---|---|
| "库存不足" | 出库数 > 库存，检查 warehouse/product/batch |
| "回款账户 XXX 余额不足 ¥YYY，无法撤销" | 采购撤销余额校验（Bug #4 修复） |
| "采购单状态为 'X'，只有 paid（已付款未收货）可撤销" | 已收货的走退货流程 |
| 404 "PurchaseOrder not found" | RLS 挡 / id 错 |
