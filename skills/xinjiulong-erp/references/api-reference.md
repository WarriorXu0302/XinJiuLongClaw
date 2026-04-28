# API 端点速查（按模块分组）

共 250+ 个端点。Agent 按当前业务意图只看对应小节。

**全部端点**都要 `Authorization: Bearer <JWT>`（除了 `/api/auth/login` 和 `/api/feishu/*`）。

**约定**：
- `{id}` 是路径参数
- 查询参数如 `brand_id` / `status` / `skip` / `limit` 大多可选
- 所有列表 GET 返回 `{items: [...], total: N}`

## 目录

1. [认证 Auth](#认证)
2. [飞书集成 Feishu](#飞书集成)
3. [订单 Orders](#订单)
4. [收款 Receipts](#收款)
5. [客户 Customers](#客户)
6. [政策 Policies](#政策)
7. [政策模板 Policy Templates](#政策模板)
8. [库存 Inventory](#库存)
9. [采购 Purchase](#采购)
10. [账户资金 Accounts](#账户资金)
11. [财务 Finance](#财务)
12. [稽查 Inspections](#稽查)
13. [清理案件 Cleanup](#清理案件)
14. [工资 Payroll](#工资)
15. [人事 HR](#人事)
16. [考勤 Attendance](#考勤)
17. [销售目标 Sales Targets](#销售目标)
18. [绩效 Performance](#绩效)
19. [融资 Financing](#融资)
20. [政策兑付核销 Manufacturer Settlements](#政策兑付核销)
21. [报销申请 Expense Claims](#报销申请)
22. [通知 Notifications](#通知)
23. [仪表盘 Dashboard](#仪表盘)
24. [品鉴 Tasting](#品鉴)
25. [上传下载 Uploads](#上传下载)
26. [审计日志 Audit](#审计日志)

## 认证

```
POST   /api/auth/login                      用户名密码登录拿 JWT
POST   /api/auth/refresh                    用 refresh_token 换新 access_token
GET    /api/auth/me                         当前用户信息
GET    /api/auth/users                      用户列表（admin/boss/hr）
POST   /api/auth/users                      创建用户账号（admin/boss/hr）
PUT    /api/auth/users/{user_id}            更新用户（改密码/状态）
PUT    /api/auth/users/{user_id}/roles      改角色（admin）
POST   /api/auth/users/{user_id}/reset-password 重置密码
GET    /api/auth/roles                      角色列表
```

## 飞书集成

```
POST   /api/feishu/bind                     绑定 open_id → ERP 账号（需 X-Agent-Service-Key）
POST   /api/feishu/exchange-token           open_id → 短期 JWT（需 X-Agent-Service-Key）
POST   /api/feishu/unbind                   解绑
```

## 订单

```
GET    /api/orders                                         列表（筛选：brand_id/status/payment_status/customer_id/salesman_id/keyword/date_from/date_to/skip/limit）
POST   /api/orders/preview                                 建单预览（算金额/匹配政策，不写库）
POST   /api/orders                                         建单（salesman/sales_manager/boss）
GET    /api/orders/{id}                                    订单详情
PUT    /api/orders/{id}                                    改订单（仅 pending 状态可改）
DELETE /api/orders/{id}                                    删订单（仅 pending 可删）
POST   /api/orders/{id}/submit-policy                      提交政策审批
POST   /api/orders/{id}/approve-policy                     boss 批准政策
POST   /api/orders/{id}/reject-policy                      boss 驳回政策
POST   /api/orders/{id}/confirm-external                   厂家政策确认（外审）
POST   /api/orders/{id}/resubmit                           被驳回后重新提交
POST   /api/orders/{id}/ship                               出库（warehouse/boss）
POST   /api/orders/{id}/upload-delivery                    上传送货照片（warehouse）
POST   /api/orders/{id}/confirm-delivery                   送达确认
POST   /api/orders/{id}/upload-payment-voucher             上传收款凭证（P2c 核心，状态=pending_confirmation 不动账）
POST   /api/orders/{id}/confirm-payment                    财务批准全部 pending Receipt（boss/finance）
POST   /api/orders/{id}/reject-payment-receipts            财务拒绝 pending Receipt
POST   /api/orders/{id}/complete                           标记完成（兜底）
GET    /api/orders/{id}/profit                             订单利润
GET    /api/orders/pending-receipt-confirmation            审批中心列表：有 pending Receipt 的订单
```

## 收款

```
GET    /api/receipts                        列表
POST   /api/receipts                        建 Receipt（finance/boss/admin，立即动账，status=confirmed）
GET    /api/receipts/{id}                   详情
PUT    /api/receipts/{id}                   改 Receipt
DELETE /api/receipts/{id}                   删 Receipt（已 confirmed 的拒绝删）
```

## 客户

```
GET    /api/customers                                      列表（含 brand_id/keyword/settlement_mode 筛选）
POST   /api/customers                                      建客户（自动建 CBS 绑定）
GET    /api/customers/{id}                                 详情
PUT    /api/customers/{id}                                 改客户
DELETE /api/customers/{id}                                 删客户（有未完结订单拒绝删）
GET    /api/customers/{id}/orders                          客户订单
GET    /api/customers/{id}/360                             客户 360 视图（订单+应收+政策）
GET    /api/customers/{id}/brand-salesman                  客户的品牌×业务员绑定
POST   /api/customers/{id}/brand-salesman                  新增绑定
DELETE /api/customers/{id}/brand-salesman/{brand_id}       解绑
```

## 政策

```
GET    /api/policies/requests                                      政策申请列表
POST   /api/policies/requests                                      建政策申请
GET    /api/policies/requests/{id}                                 详情
PUT    /api/policies/requests/{id}                                 改
DELETE /api/policies/requests/{id}                                 删
POST   /api/policies/requests/{id}/fulfill-materials               兑付物料（出库）
POST   /api/policies/requests/{id}/fulfill-item-status             改条目兑付状态
POST   /api/policies/requests/{id}/submit-voucher                  提交兑付凭证
POST   /api/policies/requests/{id}/confirm-fulfill                 财务确认归档（幂等）
POST   /api/policies/requests/confirm-arrival                      确认到账（F 类账户加钱，幂等）
POST   /api/policies/requests/match-arrival                        Excel 到账对账匹配
GET    /api/policies/usage-records                                 使用记录列表
POST   /api/policies/usage-records                                 建使用记录
GET    /api/policies/usage-records/{id}                            详情
PUT    /api/policies/usage-records/{id}                            改
GET    /api/policies/claims                                        政策兑付 Claim 列表
POST   /api/policies/claims                                        建 Claim
GET    /api/policies/claims/{id}                                   详情
PUT    /api/policies/claims/{id}                                   改
DELETE /api/policies/claims/{id}                                   删
GET    /api/policies/request-items/{id}/expenses                   某条目的费用明细
POST   /api/policies/request-items/{id}/expenses                   加费用
PUT    /api/policies/expenses/{id}                                 改
DELETE /api/policies/expenses/{id}                                 删
```

## 政策模板

```
GET    /api/policy-templates/templates                     列表
POST   /api/policy-templates/templates                     建（仅 boss/finance）
GET    /api/policy-templates/templates/{id}                详情
PUT    /api/policy-templates/templates/{id}                改
DELETE /api/policy-templates/templates/{id}                删（有关联申请时拒绝）
GET    /api/policy-templates/templates/match               自动匹配（brand_id/cases/unit_price）
POST   /api/policy-templates/templates/{id}/extend         续期
GET    /api/policy-templates/adjustments                   调整记录列表
POST   /api/policy-templates/adjustments                   加调整
GET    /api/policy-templates/adjustments/{id}              详情
```

## 库存

```
GET    /api/inventory/warehouses                           仓库列表
GET    /api/inventory/batches                              批次列表
GET    /api/inventory/low-stock                            低库存
POST   /api/inventory/low-stock/notify                     推低库存通知
GET    /api/inventory/stock-flow                           出入库流水
GET    /api/inventory/value-summary                        库存总价值
GET    /api/inventory/barcode-trace/{barcode}              条码溯源
POST   /api/inventory/direct-inbound                       直接入库（调整）
POST   /api/inventory/direct-outbound                      直接出库（调整）
POST   /api/inventory/stock-out                            订单出库（扫码）
POST   /api/inventory/stock-ins/{flow_id}/bind-barcodes    补绑条码
POST   /api/inventory/barcodes/batch-import                批量导入条码
GET    /api/bottle-reconciliation                          空瓶对账
POST   /api/bottle-destructions                            空瓶销毁
GET    /api/bottle-destructions                            销毁记录
```

## 采购

```
GET    /api/purchase-orders                                列表
POST   /api/purchase-orders                                建采购单
GET    /api/purchase-orders/{id}                           详情
POST   /api/purchase-orders/{id}/approve                   审批（finance/boss）
POST   /api/purchase-orders/{id}/reject                    驳回
POST   /api/purchase-orders/{id}/cancel                    撤销已付款的（有 FOR UPDATE + 余额校验）
POST   /api/purchase-orders/{id}/receive                   收货（warehouse）
GET    /api/suppliers                                      供应商列表
POST   /api/suppliers                                      建
GET    /api/suppliers/{id}                                 详情
PUT    /api/suppliers/{id}                                 改
DELETE /api/suppliers/{id}                                 删
```

## 账户资金

```
GET    /api/accounts                                       账户列表（按 RLS 过滤：salesman 看不到 master）
GET    /api/accounts/summary                               账户总览（按品牌聚合）
GET    /api/accounts/fund-flows                            资金流水
POST   /api/accounts/fund-flows                            手工加流水（反向凭证等，boss/finance）
POST   /api/accounts/transfer                              品牌间调拨申请
GET    /api/accounts/pending-transfers                     待审批调拨
POST   /api/accounts/transfers/{id}/approve                批准调拨（boss）
POST   /api/accounts/transfers/{id}/reject                 驳回调拨
```

## 财务

```
GET    /api/payments                                       付款流水
POST   /api/payments                                       建付款
GET    /api/payments/{id}                                  详情
PUT    /api/payments/{id}                                  改
DELETE /api/payments/{id}                                  删（仅 admin）
GET    /api/expenses                                       费用列表
POST   /api/expenses                                       建费用
GET    /api/expenses/{id}                                  详情
PUT    /api/expenses/{id}                                  改
DELETE /api/expenses/{id}                                  删（已 paid 拒绝）
POST   /api/expenses/{id}/approve                          审批
POST   /api/expenses/{id}/reject                           驳回
POST   /api/expenses/{id}/pay                              付款
GET    /api/payment-requests                               垫付返还申请
POST   /api/payment-requests                               建申请
GET    /api/payment-requests/{id}                          详情
PUT    /api/payment-requests/{id}                          改
POST   /api/payment-requests/{id}/confirm-payment          确认已付
GET    /api/receivables                                    应收账款
GET    /api/receivables/aging                              应收账龄
```

## 稽查

```
GET    /api/inspection-cases                               案件列表
POST   /api/inspection-cases                               建案件（A1/A2/A3/B1/B2）
GET    /api/inspection-cases/{id}                          详情
PUT    /api/inspection-cases/{id}                          改
DELETE /api/inspection-cases/{id}                          删（已执行的拒绝删）
POST   /api/inspection-cases/{id}/execute                  执行（动账+库存）
POST   /api/inspection-cases/{id}/recover-to-stock         回仓（A1/A2 恶意/非恶意）
```

## 清理案件

```
GET    /api/cleanup-cases
POST   /api/cleanup-cases
GET    /api/cleanup-cases/{id}
PUT    /api/cleanup-cases/{id}
DELETE /api/cleanup-cases/{id}
POST   /api/cleanup-cases/{id}/stock-in                    入库
```

## 工资

```
GET    /api/payroll/positions                              岗位列表
GET    /api/payroll/salary-schemes                         薪酬方案
POST   /api/payroll/salary-schemes                         建方案
PUT    /api/payroll/salary-schemes/{id}                    改
DELETE /api/payroll/salary-schemes/{id}                    删
GET    /api/payroll/employees/{id}/brand-positions         员工的品牌×岗位绑定
POST   /api/payroll/employees/{id}/brand-positions         建绑定
PUT    /api/payroll/brand-positions/{id}                   改
DELETE /api/payroll/brand-positions/{id}                   删
GET    /api/payroll/salary-records                         工资单列表
POST   /api/payroll/salary-records/generate                批量生成本月工资（按员工）
POST   /api/payroll/salary-records                         手工建单条
GET    /api/payroll/salary-records/{id}/detail             详情
GET    /api/payroll/salary-records/{id}/order-links        工资单关联订单
PUT    /api/payroll/salary-records/{id}                    改
DELETE /api/payroll/salary-records/{id}                    删
POST   /api/payroll/salary-records/{id}/submit             提交审批
POST   /api/payroll/salary-records/{id}/approve            批准
POST   /api/payroll/salary-records/{id}/pay                发放
POST   /api/payroll/salary-records/batch-submit            批量提交
POST   /api/payroll/salary-records/batch-confirm           批量确认
POST   /api/payroll/salary-records/batch-pay               批量发放
GET    /api/payroll/manufacturer-subsidies                 厂家补贴列表
POST   /api/payroll/manufacturer-subsidies/generate-expected       生成本月应收
POST   /api/payroll/manufacturer-subsidies/confirm-arrival         确认到账（财务批量）
POST   /api/payroll/manufacturer-subsidies/manual-mark-arrived     手动标记到账
GET    /api/payroll/assessment-items                       KPI 考核项
POST   /api/payroll/assessment-items                       建
PUT    /api/payroll/assessment-items/{id}                  改
DELETE /api/payroll/assessment-items/{id}                  删
```

## 人事

```
GET    /api/hr/employees                                   员工列表
POST   /api/hr/employees                                   建员工
GET    /api/hr/employees/{id}                              详情
PUT    /api/hr/employees/{id}                              改
DELETE /api/hr/employees/{id}                              删
GET    /api/hr/kpis                                        KPI 列表
POST   /api/hr/kpis                                        建 KPI
GET    /api/hr/kpis/{id}                                   详情
PUT    /api/hr/kpis/{id}                                   改
DELETE /api/hr/kpis/{id}                                   删
GET    /api/hr/commissions                                 提成列表
POST   /api/hr/commissions                                 建提成
GET    /api/hr/commissions/{id}                            详情
PUT    /api/hr/commissions/{id}                            改
DELETE /api/hr/commissions/{id}                            删
POST   /api/hr/commissions/{id}/settle                     结算（挂到工资单）
```

## 考勤

```
GET    /api/attendance/rules                               打卡规则
POST   /api/attendance/rules                               建/改规则
GET    /api/attendance/checkin                             打卡记录
POST   /api/attendance/checkin                             打卡（上班/下班）
GET    /api/attendance/visits                              客户拜访
POST   /api/attendance/visits/enter                        进店
POST   /api/attendance/visits/leave                        出店
GET    /api/attendance/leave-requests                      请假申请
POST   /api/attendance/leave-requests                      建请假
POST   /api/attendance/leave-requests/{id}/approve         审批请假
GET    /api/attendance/monthly-summary                     月度考勤汇总
```

## 销售目标

```
GET    /api/sales-targets                                  目标列表
POST   /api/sales-targets                                  建目标（三级：company/brand/employee）
PUT    /api/sales-targets/{id}                             改
DELETE /api/sales-targets/{id}                             删
POST   /api/sales-targets/{id}/approve                     审批目标
GET    /api/sales-targets/my-dashboard                     我的目标仪表
```

## 绩效

```
GET    /api/performance/me                                 我的绩效
GET    /api/performance/employee-monthly                   员工月度绩效
GET    /api/performance/employee-trend                     趋势
POST   /api/performance/init-assessment-items              初始化考核项
POST   /api/performance/refresh-assessment-actual          刷实际值
```

## 融资

```
GET    /api/financing-orders                               融资单列表
POST   /api/financing-orders                               建融资
GET    /api/financing-orders/{id}                          详情
GET    /api/financing-orders/{id}/calc-interest            算利息
GET    /api/financing-orders/{id}/repayments               还款记录
POST   /api/financing-orders/{id}/submit-repayment         提交还款
POST   /api/financing-orders/{id}/submit-return            提交退仓（退货还款）
GET    /api/financing-orders/pending-repayments            待审批还款
POST   /api/financing-orders/repayments/{id}/approve       批准还款
POST   /api/financing-orders/repayments/{id}/reject        驳回还款
```

## 政策兑付核销

```
GET    /api/manufacturer-settlements                       厂家结算列表
POST   /api/manufacturer-settlements                       建结算
POST   /api/manufacturer-settlements/import-excel          Excel 导入
GET    /api/manufacturer-settlements/{id}                  详情
PUT    /api/manufacturer-settlements/{id}                  改
POST   /api/manufacturer-settlements/{id}/allocation-preview  分配预览
POST   /api/manufacturer-settlements/{id}/allocation-confirm  确认分配
```

## 报销申请

```
GET    /api/expense-claims                                 报销列表
POST   /api/expense-claims                                 建报销
GET    /api/expense-claims/{id}                            详情
PUT    /api/expense-claims/{id}                            改
DELETE /api/expense-claims/{id}                            删
POST   /api/expense-claims/{id}/approve                    批准
POST   /api/expense-claims/{id}/reject                     驳回
POST   /api/expense-claims/{id}/apply                      申请（提交厂家）
POST   /api/expense-claims/{id}/confirm-arrival            确认到账
POST   /api/expense-claims/{id}/fulfill                    兑付
POST   /api/expense-claims/{id}/pay                        付款
POST   /api/expense-claims/{id}/settle                     结算归档
```

## 通知

```
GET    /api/notifications                                  通知列表
GET    /api/notifications/unread-count                     未读数
POST   /api/notifications/{id}/mark-read                   标已读
POST   /api/notifications/mark-all-read                    全部已读
```

## 仪表盘

```
GET    /api/dashboard/summary                              总览（订单数/应收/库存价值）
GET    /api/dashboard/trend                                趋势
GET    /api/dashboard/profit-summary                       利润台账（11 科目）
GET    /api/dashboard/profit-detail                        某科目明细
```

## 品鉴

```
GET    /api/tasting-wine-usage                             品鉴酒用量
POST   /api/tasting-wine-usage                             记录用量
GET    /api/tasting-wine-usage/{id}                        详情
PUT    /api/tasting-wine-usage/{id}                        改
DELETE /api/tasting-wine-usage/{id}                        删
```

## 产品品牌

```
GET    /api/products                                       商品列表
POST   /api/products                                       建商品
GET    /api/products/{id}                                  详情
PUT    /api/products/{id}                                  改
DELETE /api/products/{id}                                  删
GET    /api/products/brands                                品牌列表
POST   /api/products/brands                                建品牌
PUT    /api/products/brands/{id}                           改
DELETE /api/products/brands/{id}                           删
```

## 上传下载

```
POST   /api/uploads                                        上传文件（multipart/form-data，10MB 以内图片）
GET    /api/uploads/files/{path:path}                      下载文件（不鉴权，靠 UUID 不可枚举）
```

## 审计日志

```
GET    /api/audit-logs                                     审计日志列表（admin）
GET    /api/audit-logs/actions                             所有 action 类型
GET    /api/audit-logs/entity-types                        所有 entity 类型
```
