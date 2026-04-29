"""
/api/mall/salesman/skip-alerts
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.services.mall import auth_service, order_service

router = APIRouter()


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


@router.get("")
async def list_alerts(
    current: CurrentMallUser,
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = await order_service.list_skip_alerts_for_salesman(
        db, user.id, status_filter=status
    )
    return {
        "records": [
            {
                "id": r.id,
                "customer_user_id": r.customer_user_id,
                "skip_count": r.skip_count,
                "status": r.status,
                "appeal_reason": r.appeal_reason,
                "appeal_at": r.appeal_at,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


class _AppealBody(BaseModel):
    reason: str


@router.post("/{alert_id}/appeal")
async def appeal(
    alert_id: str,
    body: _AppealBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    alert = await order_service.appeal_skip_alert(db, user, alert_id, body.reason)
    return {"id": alert.id, "appeal_at": alert.appeal_at}
