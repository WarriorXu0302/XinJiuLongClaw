"""
业务员 ERP 复用模块（薄层，基于 ActorContext 调 ERP service）。

规则：
  - 必须 CurrentMallUser + user_type='salesman' + linked_employee_id NOT NULL
  - 路由内部构造 ActorContext 后调 ERP 对应 service
  - 不走 ERP 路由本身（避免 JWT type 冲突）

模块：
  attendance.py    打卡 + 拜访
  leave.py         请假
  expense.py       报销
  inspection.py    稽查（扫码查真伪 + 创建 pending case，执行仍在 ERP 财务）
  kpi.py           我的销售目标 / KPI
  notifications.py 通知中心（recipient_type='mall_user'）
"""
