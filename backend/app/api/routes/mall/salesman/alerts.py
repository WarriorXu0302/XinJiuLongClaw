"""
/api/mall/salesman/skip-alerts
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
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
    """业务员看自己被投诉的告警。返回客户昵称 + 手机尾号脱敏，便于申诉时描述"""
    from sqlalchemy import select
    from app.models.mall.user import MallUser

    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = await order_service.list_skip_alerts_for_salesman(
        db, user.id, status_filter=status
    )
    if not rows:
        return {"records": [], "total": 0}

    # 批量取客户昵称
    cust_ids = list({r.customer_user_id for r in rows})
    customers = (await db.execute(
        select(MallUser).where(MallUser.id.in_(cust_ids))
    )).scalars().all()
    cust_map = {c.id: c for c in customers}

    def _mask_phone(p: Optional[str]) -> Optional[str]:
        if not p or len(p) < 7:
            return p
        return f"{p[:3]}****{p[-4:]}"

    records = []
    for r in rows:
        cust = cust_map.get(r.customer_user_id)
        records.append({
            "id": r.id,
            "customer": {
                "nickname": cust.nickname if cust else None,
                "masked_phone": _mask_phone(cust.phone) if cust else None,
            } if cust else None,
            "skip_count": r.skip_count,
            "status": r.status,
            "appeal_reason": r.appeal_reason,
            "appeal_at": r.appeal_at,
            "resolved_at": r.resolved_at,
            "resolution_note": r.resolution_note,
            "created_at": r.created_at,
        })
    return {"records": records, "total": len(rows)}


class _AppealBody(BaseModel):
    # 申诉文本限长 500：足够说明情况又防 DB 污染
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{alert_id}/appeal")
async def appeal(
    alert_id: str,
    body: _AppealBody,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    alert = await order_service.appeal_skip_alert(db, user, alert_id, body.reason, request=request)
    return {"id": alert.id, "appeal_at": alert.appeal_at}
