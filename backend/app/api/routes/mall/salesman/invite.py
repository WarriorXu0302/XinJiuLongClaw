"""
/api/mall/salesman/invite-codes

POST /                 签发邀请码
GET  /history?limit=   最近邀请码（含已用/已过期）
POST /{id}/invalidate  业务员作废未用邀请码
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.services.mall import auth_service, invite_service

router = APIRouter()


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


def _invite_to_dict(row) -> dict:
    if row.invalidated_at is not None:
        status = "invalidated"
    elif row.used_at is not None:
        status = "used"
    else:
        status = "expired" if row.expires_at <= datetime.now(timezone.utc) else "pending"
    return {
        "id": row.id,
        "code": row.code,
        "expires_at": row.expires_at,
        "used_at": row.used_at,
        "used_by_user_id": row.used_by_user_id,
        "invalidated_at": row.invalidated_at,
        "created_at": row.created_at,
        "status": status,
    }


@router.post("")
async def create(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    invite = await invite_service.generate_invite_code(db, user)
    return _invite_to_dict(invite)


@router.get("/history")
async def history(
    current: CurrentMallUser,
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = await invite_service.list_recent_codes(db, user, limit=limit)
    return {"records": [_invite_to_dict(r) for r in rows]}


class _InvalidateBody(BaseModel):
    reason: Optional[str] = None


@router.post("/{code_id}/invalidate")
async def invalidate(
    code_id: str,
    current: CurrentMallUser,
    request: Request,
    body: Optional[_InvalidateBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    row = await invite_service.invalidate_invite_code(
        db, user, code_id, reason=body.reason if body else None,
        request=request,
    )
    return _invite_to_dict(row)
