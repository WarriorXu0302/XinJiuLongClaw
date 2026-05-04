# Agent 剧本：员工怎么说 → Agent 怎么做

**这份文档的角色**：Agent 听到员工一句自然语言时，按这份剧本**一步一步地**翻译成 API 调用序列。

**使用方式**：Agent 先识别意图（关键词匹配 + 语义判断），找到对应场景，然后**严格按照**剧本里的步骤执行。

**公共前置**（所有场景共用）：
1. 拿当前 `open_id` 调 `/api/feishu/exchange-token` 换 JWT（未绑定则推卡片让**员工本人**填 ERP 用户名+密码，调 `/api/feishu/bind` 绑定后再 exchange）
2. 从 JWT payload 拿 `user_id / role / brand_ids / employee_id`
3. 根据角色过滤能做什么（见 `business-rules.md` §一）
4. **身份隔离铁律**：Agent 永远用**当前对话用户**的 JWT 调 ERP，**不复用、不越权、不代别人操作**。详见 `business-rules.md` §零。

---

## 场景 1：建客户

**用户话术**（示例）：
- "帮我建个客户，名字叫张三烟酒店"
- "把李四的店录进来，他在青花郎渠道"
- "新客户王五便利店，联系电话 138xxx"

**Agent 步骤**：

1. **识别并收集必填字段**（缺则问用户）：
   - `name` 客户名（必）
   - `customer_type` channel / group_purchase
   - `settlement_mode` cash / credit
   - `brand_id` **salesman 必传**（从全局品牌拿，没选就问）
   - `contact_name / contact_phone`

2. **推飞书 Form 卡片**让用户确认：
   ```json
   {
     "header": {"title": "新建客户"},
     "elements": [
       {"tag": "form", "name": "new_customer", "elements": [
         {"tag": "input", "name": "name", "placeholder": "客户名称 *"},
         {"tag": "select_static", "name": "customer_type", "options": [
           {"text": "渠道客户", "value": "channel"},
           {"text": "团购客户", "value": "group_purchase"}
         ]},
         {"tag": "select_static", "name": "settlement_mode", "options": [
           {"text": "现结", "value": "cash"},
           {"text": "赊销", "value": "credit"}
         ]},
         {"tag": "select_static", "name": "brand_id", "placeholder": "归属品牌 *",
          "options": "<从 GET /api/products/brands>"},
         {"tag": "input", "name": "contact_name"},
         {"tag": "input", "name": "contact_phone"},
         {"tag": "button", "text": "确认建客户", "action_type": "form_submit"}
       ]}
     ]
   }
   ```

3. **用户提交** → Agent 调：
   ```
   POST /api/customers
   {
     "name": "...",
     "customer_type": "channel",
     "settlement_mode": "cash",
     "brand_id": "...",
     "contact_name": "...",
     "contact_phone": "..."
   }
   ```

4. **后端自动**建 `CustomerBrandSalesman` 把客户绑到当前 salesman 身上。

5. **反馈**：`update_card` 改为"✅ 已建客户 {name}，编号 {code}"。

**常见错误**：
- salesman 不传 brand_id → 400 "业务员创建客户必须指定 brand_id"
- brand_id 不在 salesman 品牌范围 → 400

---

## 场景 2：建订单

**用户话术**：
- "给张三烟酒店下 5 箱青花郎，按指导价"
- "李四这单 10 箱五粮液，业务员垫差"
- "王五订 3 箱汾酒，公司让利模式"

**Agent 步骤**：

### 2.1 收集参数

- `customer_id`（模糊搜 `GET /api/customers?keyword=张三`）
- `brand_id`（从全局品牌或客户的 CBS 绑定拿）
- `settlement_mode`（**必须明确**问用户三选一）
- `items[]`（product_id + quantity + quantity_unit + unit_price + deal_unit_price?）
- `policy_template_id`（可选，优先 match）

### 2.2 政策匹配

```
GET /api/policy-templates/templates/match?brand_id=X&cases=N&unit_price=P
```

- 0 条 → Agent 告诉用户"没有匹配政策，无法下单" **（重要：不要硬建）**
- 1 条 → 自动选用
- 多条 → 推卡片让用户选

### 2.3 预览

```
POST /api/orders/preview
{
  "customer_id": "...",
  "brand_id": "...",
  "settlement_mode": "customer_pay",  // 或 employee_pay / company_pay
  "items": [...],
  "policy_template_id": "..."
}
```

返回：指导价总额 / 到手价总额 / 公司应收 / 业务员垫付 / 政策差 / 预估提成。

### 2.4 确认卡片

```
【确认建单】
客户：张三烟酒店
品牌：青花郎
结算模式：客户按指导价付（customer_pay）
商品：
  - 青花郎 53度 500ml × 5箱（指导价 ¥900/瓶）
匹配政策：青花郎 VIP 5-10 箱（赠 1 箱 + 返现 ¥500）

指导价总额：¥27,000
客户实付：¥27,000
公司应收：¥27,000
预估提成：¥1,080

[确认建单] [取消]
```

### 2.5 执行

```
POST /api/orders
（同 preview 参数）
```

### 2.6 反馈 + 下一步

"✅ 订单 SO-xxx 已创建，状态 pending。下一步：[提交政策审批]"

**错误处理**：
- 客户未绑定品牌 → 引导用户先建 CBS
- 产品不属于该品牌 → 提示
- 政策匹配 0 条 → 不允许建单
- deal_unit_price 缺失（company_pay / employee_pay）→ 提示必填

---

## 场景 3：提交政策审批

**用户话术**：
- "把 SO-xxx 提交审批"
- "这单该审了"

**Agent 步骤**：

1. 确认订单状态 == `pending`（其他状态 400）
2. 调 `POST /api/orders/{id}/submit-policy`
3. 订单 → `policy_pending_internal`
4. 自动通知 boss

---

## 场景 4：老板审批订单

**用户话术**（boss 说）：
- "看看待审的订单"
- "批了"
- "驳回 SO-xxx，理由：价格太低"

**Agent 步骤**：

1. **列出**：`GET /api/orders?status=policy_pending_internal&brand_id=X`
2. 推卡片展示每条的：客户、金额、政策、业务员
3. boss 点批准 → `POST /api/orders/{id}/approve-policy`（如需外审 `?need_external=true`）
4. boss 点驳回 → 推"输入驳回原因"的 input 卡片 → `POST /api/orders/{id}/reject-policy`

---

## 场景 5：出库

**用户话术**（warehouse 说）：
- "SO-xxx 要出库了"

**Agent 步骤**：

**Agent 一般不代操作出库**（需要扫码枪），提示用户："请到仓库扫码页面 `/orders/{id}/ship` 完成出库。"

如果是非扫码场景：
```
POST /api/orders/{id}/ship
（后端扣库存 + 生成 StockFlow）
```

---

## 场景 6：送达确认

**用户话术**：
- "货送到客户那了"
- "这单送达了，有照片"

**Agent 步骤**：

1. 引导用户发送货照片 → 飞书拿 image_key → 下载 → `POST /api/uploads` 拿 URL
2. 调：
   ```
   POST /api/orders/{id}/upload-delivery
   { "voucher_urls": ["..."] }
   ```
3. 调 `POST /api/orders/{id}/confirm-delivery`
4. 订单 → `delivered`

---

## 场景 7：上传收款凭证（业务员最常用）

**用户话术**：
- "SO-xxx 客户打款了，凭证在我手机上"
- "张三付了 3 万"

**Agent 步骤**：

### 7.1 引导发图

回复文本："请把收款凭证图片直接发给我"。

### 7.2 接收图片

用户发图 → Agent 收 `im.message.receive_v1` 事件 → 提取 `message_id + image_key`。

### 7.3 上传到 ERP

```python
# scripts/feishu_image_to_upload.py
url = feishu_image_to_erp(message_id, image_key, erp_jwt)
# url = "/api/uploads/files/2026-04/uuid.jpg"
```

### 7.4 收集金额

如果用户没说，问"本次收多少？全款还是部分？"

### 7.5 确认卡片

```
【确认登记收款】
订单：SO-xxx 张三烟酒店
应收：¥27,000
本次收款：¥27,000（全款）
凭证：[图片缩略图]

[确认登记] [修改金额] [取消]
```

### 7.6 执行

```
POST /api/orders/{order_id}/upload-payment-voucher
{
  "amount": 27000,
  "voucher_urls": ["/api/uploads/files/..."]
}
```

### 7.7 反馈

"✅ 凭证已提交，等待财务审批（预计 1-2 小时内）。审批通过后你会收到通知。"

**重要说明**（Agent 必须告诉业务员）：
- 这**不是**真的"已收款"，只是凭证登记
- 财务审批前订单不会变"已付款"
- 不会生成提成
- 如果有误可以让财务驳回

---

## 场景 8：财务审批收款

**用户话术**（finance/boss 说）：
- "看看待审的收款"
- "张三的 SO-xxx 批了"
- "驳回凭证，金额不对"

**Agent 步骤**：

### 8.1 列出

```
GET /api/orders/pending-receipt-confirmation
```

返回所有 `payment_status='pending_confirmation'` 且有 pending Receipt 的订单。

### 8.2 展示单个订单

推卡片：
```
【收款审批】
订单：SO-xxx 张三烟酒店
应收：¥27,000（customer_pay）
本次上传：3 张凭证，合计 ¥27,000（全款）
上传时间：2026-04-28 10:30
凭证：[图 1] [图 2] [图 3]

[批准全部] [驳回全部]
```

### 8.3 批准

```
POST /api/orders/{id}/confirm-payment
```

**铁律**：all-or-nothing，该订单**所有** pending Receipt 一次性转 confirmed。

**后端自动**：
- master_cash.balance += 每笔 Receipt 金额
- Receipt.status → confirmed
- Receivable 分摊
- 首次 fully_paid → 生成 Commission + 刷新 KPI + 推里程碑

### 8.4 驳回

```
POST /api/orders/{id}/reject-payment-receipts
{ "reason": "凭证金额与订单对不上" }
```

**反馈**：通知业务员重新上传。

---

## 场景 9：查订单状态

**用户话术**：
- "SO-xxx 现在啥状态"
- "这单客户收到了没"
- "这单还欠多少"

**Agent 步骤**：

```
GET /api/orders/{id}
```

展示：订单号 / 客户 / 金额字段（按结算模式展示） / 订单状态 / 付款状态 / 已收/欠款。

**计算"欠款"**：`customer_paid_amount - SUM(confirmed Receipt.amount)`。

---

## 场景 10：查我的月度业绩

**用户话术**（salesman 说）：
- "我本月完成多少了"
- "这个月到手多少"

**Agent 步骤**：

### 10.1 本月回款 + 销售

```
GET /api/performance/me?period=2026-04
```

返回：
- 销售额
- 回款额（仅 confirmed Receipt 合计）
- KPI 考核项完成率
- 预估本月绩效 + 提成

### 10.2 展示

```
【李四 2026-04 业绩】
销售：¥120,000 / 目标 ¥100,000（120% ✅）
回款：¥95,000 / 目标 ¥100,000（95%）
KPI：
  - 回款额：¥95K / ¥100K → 95%
  - 新客户：3 / 5 → 60%
  - 拜访次数：25 / 20 → 125%

预估本月薪资：¥8,500
  - 底薪：¥5,000
  - 浮动：¥1,200（考核完成率 ×）
  - 提成：¥2,100（95% KPI 系数）
  - 全勤：¥200（本月请 0 天）
```

---

## 场景 11：查本月审批队列

**用户话术**（boss 说）：
- "今天有啥要审的"
- "看看待办"

**Agent 步骤**：

并行调：

```python
orders_recv = GET /api/orders/pending-receipt-confirmation
orders_policy = GET /api/orders?status=policy_pending_internal
purchases = GET /api/purchase-orders?status=pending
transfers = GET /api/accounts/pending-transfers
salaries = GET /api/payroll/salary-records?status=pending_approval
leaves = GET /api/attendance/leave-requests?status=pending
advances = GET /api/payment-requests?status=pending
claims = GET /api/expense-claims?status=pending
financing = GET /api/financing-orders/pending-repayments
expenses = GET /api/expenses?status=pending
```

推汇总卡片：

```
【审批中心 4 月 28 日】
📝 收款确认 5 单（¥58,000）
🎯 政策审批 3 单
🛒 采购审批 2 单（¥120,000）
💰 调拨申请 1 笔（¥50,000）
📅 请假 1 条
💸 报销 3 笔（¥3,500）

[按顺序处理] [稍后]
```

---

## 场景 12：生成月度工资

**用户话术**（HR 说）：
- "生成 4 月工资单"

**Agent 步骤**：

1. 确认卡片：
   ```
   【确认生成 2026-04 工资单】
   覆盖员工：15 人（所有在职）
   底薪来源：主属品牌 × 岗位的薪酬方案
   提成基数：本月新全款订单
   KPI 系数：按品牌 kpi_coefficient_rules 当前规则
   本月 pay_cutoff_date：2026-04-30
   
   [确认生成] [取消]
   ```

2. 执行：
   ```
   POST /api/payroll/salary-records/generate
   {
     "period": "2026-04",
     "pay_cutoff_date": "2026-04-30",
     "overwrite": false
   }
   ```

3. 返回 `{created: 15, skipped: [...]}`。

4. 展示 skipped 列表（一般是"未设主属品牌"）。

---

## 场景 13：提成规则（KPI 系数）配置

**用户话术**（boss 说）：
- "把青花郎的 KPI 规则改一下"
- "完成 100% 以上的要加倍"

**Agent 步骤**：

1. 查当前规则：`GET /api/payroll/kpi-coefficient-rules?brand_id=X`
2. 理解用户要改什么：
   - 改现有规则的 min_rate / max_rate / mode / fixed_value
   - 新增规则覆盖新的区间
   - 停用规则
3. 如果有区间冲突，引导用户先编辑现有规则缩小范围

典型对话：

```
用户："青花郎完成 120% 以上的系数改成 1.5"

Agent 步骤：
1. 查现有规则 → 发现 [50%, +∞) linear 覆盖 120%
2. 告诉用户："当前规则是 ≥50% 按完成率线性（完成 150% 系数就是 1.5）。
              你是想 ≥120% 统一系数 1.5（而不是按完成率）吗？"
3. 确认后：
   - 编辑现有 [0.5, +∞) → 缩到 [0.5, 1.2)
   - 新增 [1.2, +∞) mode=fixed fixed_value=1.5
4. 显示新的规则组合
```

**权限**：仅 boss + admin。

---

## 场景 14：工资单重算

**用户话术**（boss 说）：
- "KPI 规则变了，4 月工资重算一下"

**Agent 步骤**：

1. 确认只对 `draft / rejected` 状态的工资单有效
2. 查询本期 draft 工资单列表
3. 批量调：
   ```
   POST /api/payroll/salary-records/{id}/recompute
   ```
4. 展示变化：
   ```
   【重算完成】
   共刷新 12 份工资单
   提成总额：¥23,400 → ¥28,100（+¥4,700）
   已归档工资单不受影响（需走反向凭证）
   ```

---

## 场景 15：政策兑付物料出库

**用户话术**（业务员说）：
- "SO-xxx 的政策赠品给客户了"

**Agent 步骤**：

1. 查政策 request + item
2. 收集出库明细：`request_item_id / product_id / quantity / quantity_unit / warehouse_id`
3. 确认卡片展示库存影响
4. 调：
   ```
   POST /api/policies/requests/{request_id}/fulfill-materials
   { "items": [{...}] }
   ```
5. item.fulfilled_qty 递增，达到 quantity 时 fulfill_status → fulfilled

---

## 场景 16：提交政策兑付凭证

**用户话术**：
- "把政策兑付的照片传一下"
- "实际花了 ¥450"

**Agent 步骤**：

1. 引导发图 → uploads
2. 收集 `actual_cost`（实际花费）
3. 调：
   ```
   POST /api/policies/requests/{id}/submit-voucher
   {
     "item_id": "...",
     "voucher_urls": ["..."],
     "actual_cost": 450
   }
   ```
4. 后端算 `profit_loss = standard_total - total_value - actual_cost`

---

## 场景 17：财务确认政策到账

**用户话术**（finance 说）：
- "厂家政策款到了 ¥500"

**Agent 步骤**：

### 17a. 单条确认

```
POST /api/policies/requests/confirm-arrival
{
  "items": [{"item_id": "...", "arrived_amount": 500, "billcode": "银行单号"}]
}
```

### 17b. Excel 批量对账

用户发 Excel → `POST /api/policies/requests/match-arrival?brand_id=X`（multipart）

后端两轮匹配，返回未匹配行让用户手工处理。

**幂等**：已 `arrived` 的跳过（重要）。

---

## 场景 18：厂家工资补贴到账

**用户话术**（finance 说）：
- "青花郎 4 月厂家补贴到账 ¥5,000"

**Agent 步骤**：

1. 先查应收：`GET /api/payroll/manufacturer-subsidies?brand_id=X&period=2026-04&status=pending`
2. 算合计是否等于 ¥5,000
3. 不相等 → 告诉用户"金额不符，应收 ¥X，实到 ¥Y，需手工调整"
4. 相等 → 确认卡片 → 调：
   ```
   POST /api/payroll/manufacturer-subsidies/confirm-arrival
   {
     "brand_id": "...",
     "period": "2026-04",
     "arrived_amount": 5000,
     "billcode": "..."
   }
   ```
5. 后端：品牌 cash += 5000，所有相关 subsidy status → reimbursed

---

## 场景 19：稽查建案

**用户话术**：
- "我在云南发现窜货，条码 ABC123，2 箱"
- "客户李四恶意外流"

**Agent 步骤**：

1. 追溯：`GET /api/inventory/barcode-trace/ABC123` → 拿 original_order_id / customer / sale_price / deal_price
2. 问用户是 A1 还是 A2（恶意 / 非恶意）
3. 收集 `recovery_price / penalty_amount / voucher_urls`
4. 确认卡片展示预估盈亏
5. 调：
   ```
   POST /api/inspection-cases
   {
     "case_type": "outflow_malicious",
     "direction": "outflow",
     "brand_id": "...",
     "product_id": "...",
     "barcode": "ABC123",
     ...
   }
   ```
6. 告诉用户"案件 IC-xxx 已建，等 boss 审批"

---

## 场景 20：稽查案件执行

**用户话术**（boss 说）：
- "IC-xxx 案件执行"

**Agent 步骤**：

1. 查案件详情 + profit_loss
2. 确认卡片：
   ```
   【确认执行稽查案件】
   IC-xxx A1 恶意外流
   品牌：青花郎 / 客户：李四 / 数量：2 箱（20 瓶）
   动账：
   - 品牌现金 -¥14,000（回收款 ¥700 × 20 瓶）
   - 品牌现金 -¥10,000（罚款）
   - 不回仓（恶意窜货产品视为市场流失）
   预估亏损：-¥25,000（含回收成本和罚款）
   
   [确认执行] [取消]
   ```
3. 调：`POST /api/inspection-cases/{id}/execute`
4. 如余额不足会 400，告诉用户"先调拨再执行"

---

## 场景 21：建采购单

**用户话术**（purchase/boss 说）：
- "向郎酒集团采购青花郎 100 瓶"

**Agent 步骤**：

1. 收集：supplier_id / warehouse_id / items / 支付方式（cash/f_class/financing 金额）
2. 校验 `cash + f_class + financing == SUM(qty × unit_price)`
3. 确认卡片 → 调 `POST /api/purchase-orders`
4. 告诉用户"PO-xxx 已建，等 boss/finance 审批付款"

---

## 场景 22：调拨

**用户话术**：
- "从 master 调 10 万到青花郎现金"

**Agent 步骤**：

1. 查余额
2. 确认卡片（展示 from/to 账户、金额）
3. 调 `POST /api/accounts/transfer`
4. 提醒"需要 boss 批准，已生成申请"

---

## 场景 23：请假

**用户话术**（salesman 说）：
- "我 4/27-4/29 病假"

**Agent 步骤**：

1. 推 Form 卡片收集 `leave_type / reason / voucher_url?`
2. 校验 start/end/days
3. 调 `POST /api/attendance/leave-requests`
4. 告诉用户"已提交，等 HR 审批"

---

## 场景 24：查库存

**用户话术**：
- "青花郎还有多少库存"
- "主仓库的五粮液"

**Agent 步骤**：

```
GET /api/inventory/batches?brand_id=X&warehouse_id=Y&product_id=Z
```

展示：产品 × 仓库 × 批次 × 数量。

---

## 场景 25：查账户余额

**用户话术**：
- "青花郎现在有多少钱"
- "看看账户"

**Agent 步骤**：

```
GET /api/accounts/summary
```

展示各品牌现金 / F 类 / 融资 + master 现金池。**注意 salesman 看不到 master**。

---

## 场景 26：查某员工工资单

**用户话术**（HR 说）：
- "看李四 4 月工资"

**Agent 步骤**：

```
GET /api/payroll/salary-records?employee_id=X&period=2026-04
GET /api/payroll/salary-records/{id}/detail
```

展示完整明细（底薪 / 提成 / 奖金 / 扣款 / 实发 + 关联订单列表）。

---

## 场景 27：报销申请

**用户话术**（salesman 说）：
- "我这次出差花了 ¥500，报销"

**Agent 步骤**：

1. 推 Form 卡片：title / amount / category / reason / voucher_urls
2. 调 `POST /api/expense-claims`
3. 告诉用户"已提交，等审批"

---

## 场景 28：通知推送（Agent 主动找人）

**后端事件 → Agent 主动推送**：

| 事件 | 推给谁 | 卡片 |
|---|---|---|
| 上传收款凭证 | finance/boss | "有新凭证待审：SO-xxx ¥3000" |
| 订单提交政策审批 | boss | "有订单待批政策：SO-xxx" |
| KPI 达成里程碑 | 业务员本人 + sales_manager | "🎯 你已完成 50% 目标" |
| 低库存预警 | warehouse/boss | "产品 X 库存不足 5 箱" |
| 大额采购 | boss 二审 | "大额采购待审：PO-xxx ¥200K" |
| 请假被批/驳 | 申请人 | "你的请假被批/驳" |
| 工资发放 | 员工本人 | "4 月工资 ¥8500 已发放" |

---

## 场景 29：多轮对话处理（Agent 状态机）

**典型多轮交互**（建单为例）：

```
Turn 1:
 U: 给张三下 5 箱青花郎
 A: [查客户找到张三] [确认品牌] [问 settlement_mode]
    "请选择结算模式：客户按指导价付 / 业务员垫差 / 公司让利？"

Turn 2:
 U: 客户按指导价付
 A: [调 preview] [推确认卡片]
    "【确认建单】5 箱青花郎 ¥27,000 ... 确认？"

Turn 3:
 U: 点"确认建单"按钮 → 飞书回调 card.action.trigger
 A: [调 POST /api/orders] [update_card 结果]
    "✅ 订单已建 SO-xxx，下一步：[提交政策审批]"

Turn 4:
 U: 点"提交政策审批"按钮
 A: [调 POST /api/orders/{id}/submit-policy] [通知 boss]
    "✅ 已提交，等 boss 审批"
```

**ctx_id 机制**：每个卡片生成唯一 UUID，参数存内存 / Redis，卡片 button value 只带 ctx_id。点击时用 ctx_id 取回完整参数再调 API。

---

## 场景 30：Agent 不确定时的兜底

用户说话模糊或 Agent 识别不出意图时：

**标准回复**：
```
没太明白你要做什么。你可以说：
- 建客户 / 改客户
- 建订单 / 查订单 / 改订单
- 上传凭证 / 查我的收款
- 查库存 / 查账户余额
- 查我的业绩 / 查工资
- 稽查 / 请假 / 报销

你想做哪一个？
```

**禁止**：猜测用户意图直接调接口。宁可多问一轮也不要错动账。

---

## 场景 31：业务员问"我本月工资为啥少钱"（决策 #1 追回）

**用户话术**：
- "我工资条 5000，怎么到账只有 4700？"
- "上月已经发的钱这月又扣回去了？"

**Agent 步骤**：

1. **拿 employee_id**（从 JWT）
2. **定位最近一期 SalaryRecord**：
   - `GET /api/payroll/salary-records?employee_id=X&period=当前月`
   - 或从 JWT 的 role 推断（salesman 只能查自己）
3. **查明细** `GET /api/payroll/salary-records/{id}/detail`
4. **看 `clawback_details[]` 非空 →** 逐条翻译：
   ```
   原订单 {origin_order_no}（{origin_ref_type}）
   上月已发 ¥{origin_amount} 提成
   客户退货，本月扣回 ¥{abs(amount)}
   ```
5. **看 `clawback_settled_history[]` 非空 →** 说明本月扣了历史挂账：
   ```
   历史挂账 ¥{pending_amount}（{reason}）本月已扣清
   ```
6. **看 `clawback_new_pending[]` 非空 →** 本月工资不足挂账：
   ```
   本月 ¥{pending_amount} 没扣完，下月工资发放时自动先扣
   ```

**不要说**："系统扣你工资"。应说："是 X 月 MO-xxx 单客户退货冲减，参见你的退货流水"

---

## 场景 32：业务员查自己 commission 流水（G6）

**用户话术**：
- "我本月接了多少单提成？"
- "哪些订单提成被冲掉了？"

**Agent 步骤**：

1. `GET /api/mall/workspace/my-commissions/stats?year=2026&month=5`
   - 返回 `by_status.pending / settled / reversed` 金额 + 数量
   - 返回 `adjustment` 追回数量 + 金额
2. 用户追问"哪几单冲掉了" →
   - `GET /api/mall/workspace/my-commissions?status=reversed&year=2026&month=5`
3. 用户追问"追回具体哪单" →
   - `GET /api/mall/workspace/my-commissions?status=adjustment&year=2026&month=5`
   - 每条带 `origin_commission_amount` + `origin_status` 方便理解
4. 绝对不要代用户点"申诉"（第一版没开放申诉端点）

---

## 场景 33：老板问月度业务员排行（决策 #2 快照/实时双模式）

**用户话术**：
- "5 月 Top3 业务员是谁"
- "上月业绩排名出来了吗"

**Agent 步骤**：

1. **先问用户**："您要看哪个口径？"
   - **快照**：月初冻结，发完奖金后数据不变
   - **实时**：剔除退货，能看到"真实贡献"
2. 默认推快照（发奖金场景更稳）
3. `GET /api/mall/admin/dashboard/salesman-ranking?mode=snapshot&year_month=2026-05&limit=10`
4. 如果返回 `records=[]` 且 `snapshot_count=0` → 告诉用户"该月快照尚未生成，5 月 1 号 00:05 会自动冻结；需要现在冻结可调 build-snapshot"
5. **始终注明数据口径**，让老板明确"这是 5/1 冻结的历史快照"还是"实时剔退货"

---

## 场景 34：门店收银（散客 vs 会员，决策 #3）

**用户话术**（店员）：
- "那个客户没注册，给我扫了单"
- "他说他是会员，手机尾号 1234"

**Agent 步骤**：

1. **识别模式**：
   - "没注册" → 散客模式
   - "会员" → 按手机号/姓名搜（`min_length=5`）
2. **会员模式**：
   - `GET /api/mall/workspace/store-sales/customers/search?keyword=张三1234`
   - 返回 phone 已脱敏（`138****1234`）+ `is_local_customer` 标
   - 若无命中 → 问用户"改散客模式？还是先帮客户注册？"
3. **散客模式**：
   - 直接走 `POST /api/mall/workspace/store-sales`，body 里 `customer_id=null`
   - 如果客户愿意留手机号：加 `customer_walk_in_name` + `customer_walk_in_phone`
4. 提交时走扫码 `verify-barcode` → 填 `line_items` → `POST /store-sales`

---

## 场景 35：Agent 执行退货 approve 遇到并发错误（G12）

**场景**：
- 财务点"批准"按钮，后台返 500 或 UNIQUE violation
- `UniqueViolation on uq_commission_adjustment_source`

**Agent 步骤**：

1. **绝对不要重试**（可能是前端双击已成功建过 adjustment）
2. 查 `GET /api/mall/admin/returns/{id}` 看 status：
   - `approved / refunded` → 告诉用户"已审批完成，不需重复操作"
   - `pending` → 汇报错误让用户再试一次（但概率很低）
3. 如果用户坚持"我刚按的没生效" → 提示他先刷新列表

---

## 通用原则（Agent 每次都必须遵守）

1. **写入前必须用卡片按钮确认**（不依赖打字"确认"）
2. **金额永远用 preview 接口返回**（不自己算）
3. **动账失败不自动重试**（可能重复动账）
4. **错误消息原样展示**（不自己改写 detail）
5. **不泄露 master 账户余额给 salesman**
6. **涉及用户个人数据（工资/身份证等）要脱敏**
7. **多图上传时等 30 秒静默判定传完**，或用卡片按钮"完成上传"明确结束
8. **不主动替用户审批**（哪怕用户是 boss 本人，也必须卡片点按钮）
9. **所有时间按东八区展示**（后端返 UTC，前端格式化）
10. **Agent 对话记忆 ≤ 10 轮**，超过引导用户重新说明
