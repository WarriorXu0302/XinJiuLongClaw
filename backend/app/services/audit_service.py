"""
Audit logging utility — records sensitive operations to audit_logs.

调用约定：
- 所有状态变更类端点（审批、执行、撤销、删除、入库、出库、资金流动等）
  应在 db.flush 之前调用 log_audit。
- actor_id 从 CurrentUser 的 employee_id 自动取（传 user dict 即可）。
- changes 是 dict，尽量记录关键字段的前后值或金额，不必全量。
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: str | None = None,
    actor_type: str = "employee",
    changes: dict | None = None,
    ip_address: str | None = None,
    user: dict[str, Any] | None = None,  # 传 CurrentUser dict，自动提取 employee_id
) -> None:
    """在当前事务里插入一条审计日志。

    用法一（老代码兼容）：
        await log_audit(db, action="create_order", entity_type="Order", entity_id=o.id)
    用法二（推荐）：
        await log_audit(db, action="approve_order", entity_type="Order",
                        entity_id=o.id, user=user, changes={"from": "pending", "to": "approved"})
    """
    if user and not actor_id:
        actor_id = user.get("employee_id")
    entry = AuditLog(
        id=str(uuid.uuid4()),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_type=actor_type,
        changes=changes,
        ip_address=ip_address,
    )
    db.add(entry)
