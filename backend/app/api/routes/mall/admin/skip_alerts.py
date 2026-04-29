"""
/api/mall/admin/skip-alerts/*
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.order import MallSkipAlert
from app.services.mall import order_service

router = APIRouter()


@router.get("")
async def list_alerts(
    user: CurrentUser,
    status: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = select(MallSkipAlert)
    if status:
        stmt = stmt.where(MallSkipAlert.status == status)
    stmt = stmt.order_by(desc(MallSkipAlert.created_at))
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "customer_user_id": r.customer_user_id,
                "salesman_user_id": r.salesman_user_id,
                "skip_count": r.skip_count,
                "status": r.status,
                "appeal_reason": r.appeal_reason,
                "appeal_at": r.appeal_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }


class _ResolveBody(BaseModel):
    resolution_status: str = Field(pattern="^(resolved|dismissed)$")
    note: Optional[str] = None


@router.post("/{alert_id}/resolve")
async def resolve(
    alert_id: str,
    body: _ResolveBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    alert = await order_service.resolve_skip_alert(
        db, alert_id,
        operator_id=user["sub"],
        operator_type="erp_user",
        resolution_status=body.resolution_status,
        note=body.note,
    )
    return {
        "id": alert.id,
        "status": alert.status,
        "resolved_at": alert.resolved_at,
        "resolution_note": alert.resolution_note,
    }
