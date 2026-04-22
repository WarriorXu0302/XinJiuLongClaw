"""
Audit log API — query endpoint for admin visibility.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.audit_log import AuditLog
from app.models.user import Employee

router = APIRouter()


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str
    changes: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime


@router.get("")
async def list_audit_logs(
    user: CurrentUser,
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    keyword: Optional[str] = Query(None, description="在 action 或 entity_type 中模糊搜索"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    base = select(AuditLog)
    if entity_type:
        base = base.where(AuditLog.entity_type == entity_type)
    if action:
        base = base.where(AuditLog.action == action)
    if actor_id:
        base = base.where(AuditLog.actor_id == actor_id)
    if keyword:
        from sqlalchemy import or_
        kw = f"%{keyword}%"
        base = base.where(or_(AuditLog.action.ilike(kw), AuditLog.entity_type.ilike(kw)))
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            base = base.where(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            base = base.where(AuditLog.created_at <= dt_to)
        except ValueError:
            pass
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit))).scalars().all()

    # Batch fetch actor names
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    name_map: dict[str, str] = {}
    if actor_ids:
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(actor_ids))
        )).scalars().all()
        name_map = {e.id: e.name for e in emps}

    return {
        "items": [
            AuditLogResponse(
                id=r.id, action=r.action, entity_type=r.entity_type,
                entity_id=r.entity_id, actor_id=r.actor_id,
                actor_name=name_map.get(r.actor_id) if r.actor_id else None,
                actor_type=r.actor_type, changes=r.changes,
                ip_address=r.ip_address, created_at=r.created_at,
            )
            for r in rows
        ],
        "total": total,
    }


@router.get("/entity-types")
async def list_entity_types(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """返回系统里已记录过的所有 entity_type（供前端下拉筛选）"""
    from sqlalchemy import distinct
    rows = (await db.execute(select(distinct(AuditLog.entity_type)))).scalars().all()
    return sorted([r for r in rows if r])


@router.get("/actions")
async def list_actions(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """返回系统里已记录过的所有 action（供前端下拉筛选）"""
    from sqlalchemy import distinct
    rows = (await db.execute(select(distinct(AuditLog.action)))).scalars().all()
    return sorted([r for r in rows if r])
