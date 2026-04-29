"""
/api/mall/workspace/notifications/*

Mall-side 通知：查 recipient_type='mall_user' + mall_user_id=me。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.notification_log import NotificationLog
from app.services.mall import auth_service

router = APIRouter()


@router.get("")
async def list_notifications(
    current: CurrentMallUser,
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    base = select(NotificationLog).where(
        NotificationLog.recipient_type == "mall_user",
        NotificationLog.mall_user_id == user.id,
        NotificationLog.channel == "in_app",
    )
    total = int((
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0)
    rows = (await db.execute(
        base.order_by(NotificationLog.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return {
        "records": [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "status": n.status,
                "related_entity_type": n.related_entity_type,
                "related_entity_id": n.related_entity_id,
                "read_at": n.read_at,
                "created_at": n.created_at,
            }
            for n in rows
        ],
        "total": total,
    }


@router.get("/unread-count")
async def unread_count(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    count = int((await db.execute(
        select(func.count(NotificationLog.id))
        .where(NotificationLog.recipient_type == "mall_user")
        .where(NotificationLog.mall_user_id == user.id)
        .where(NotificationLog.channel == "in_app")
        .where(NotificationLog.status == "unread")
    )).scalar() or 0)
    return {"count": count}


@router.post("/{notification_id}/mark-read")
async def mark_read(
    notification_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    n = await db.get(NotificationLog, notification_id)
    if n is None or n.recipient_type != "mall_user" or n.mall_user_id != user.id:
        raise HTTPException(status_code=404, detail="通知不存在")
    n.status = "read"
    n.read_at = datetime.now(timezone.utc)
    await db.flush()
    return {"success": True}


@router.post("/mark-all-read")
async def mark_all_read(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    await db.execute(
        update(NotificationLog)
        .where(NotificationLog.recipient_type == "mall_user")
        .where(NotificationLog.mall_user_id == user.id)
        .where(NotificationLog.channel == "in_app")
        .where(NotificationLog.status == "unread")
        .values(status="read", read_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return {"success": True}
