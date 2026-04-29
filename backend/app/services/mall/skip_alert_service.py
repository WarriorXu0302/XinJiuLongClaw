"""
跳单告警服务。

两层：
  - mall_customer_skip_logs：每次跳单一条原子记录（timeout/release/reassign）
  - mall_skip_alerts：达阈值（同 customer+salesman 在 30 天内 >= 3 次，且无 open alert）创建聚合告警

告警可申诉：
  - 业务员提交申诉 → 管理员审核
  - 通过 → alert.status='dismissed' 且对应 skip_logs 标 dismissed（不计入下次阈值）
"""
# TODO(M4):
# async def record_skip_log(db, order, salesman_user, skip_type) -> None:
#     """同事务内调 aggregate_alert 判定是否触发告警。"""
# async def aggregate_alert(db, customer_user_id, salesman_user_id) -> None:
#     """如果 30 天窗口内 count >= 阈值且无 open alert，创建 alert + 发通知（ERP + mall）。"""
# async def appeal_alert(db, salesman, alert_id, reason) -> None: ...
# async def resolve_alert(db, admin, alert_id, status, note) -> None:
#     """admin 审核申诉，或直接处理 alert。status in ('resolved', 'dismissed')。"""
