"""
Mall 通知服务（封装 ERP notification_service）。

规则：
  - notification_logs 表加 recipient_type ('erp_user' | 'mall_user') + mall_user_id
  - mall 端：notify_mall_user(db, mall_user_id, title, content, entity_type, entity_id)
  - ERP 端：现有 notify/notify_roles 不动，隐式过滤 recipient_type='erp_user'
  - 跳单告警等跨系统通知：两边各 insert 一条
"""
# TODO(M4c):
# async def notify_mall_user(db, mall_user_id, title, content, entity_type=None, entity_id=None) -> None: ...
# async def notify_mall_role(db, user_type, title, content, ...) -> None:
#     """给所有 user_type='salesman' 或 'consumer' 群发。"""
# async def list_mall_notifications(db, mall_user, status=None, page, size) -> dict: ...
# async def mark_mall_notification_read(db, mall_user, notification_id) -> None: ...
# async def mall_unread_count(db, mall_user) -> int: ...
