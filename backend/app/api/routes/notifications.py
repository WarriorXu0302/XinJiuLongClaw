"""
Notification API routes — in-app notifications for the current user.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.notification_log import NotificationLog

router = APIRouter()


@router.get("/unread-count")
async def get_unread_count(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Lightweight endpoint for badge polling."""
    user_id = user["sub"]
    count = (
        await db.execute(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.recipient == user_id,
                NotificationLog.recipient_type == "erp_user",
                NotificationLog.channel == "in_app",
                NotificationLog.status == "unread",
            )
        )
    ).scalar_one()
    return {"count": count}


@router.get("")
async def list_notifications(
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for the current user, newest first."""
    user_id = user["sub"]
    base = select(NotificationLog).where(
        NotificationLog.recipient == user_id,
        NotificationLog.recipient_type == "erp_user",
        NotificationLog.channel == "in_app",
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.order_by(NotificationLog.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return {
        "items": [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "status": n.status,
                "related_entity_type": n.related_entity_type,
                "related_entity_id": n.related_entity_id,
                "read_at": str(n.read_at) if n.read_at else None,
                "created_at": str(n.created_at) if n.created_at else None,
            }
            for n in rows
        ],
        "total": total,
    }


@router.post("/{notification_id}/mark-read")
async def mark_read(
    notification_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    n = await db.get(NotificationLog, notification_id)
    if n is None or n.recipient != user["sub"] or n.recipient_type != "erp_user":
        raise HTTPException(404, "通知不存在")
    n.status = "read"
    n.read_at = datetime.now(timezone.utc)
    await db.flush()
    return {"detail": "已读"}


@router.post("/mark-all-read")
async def mark_all_read(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    await db.execute(
        update(NotificationLog)
        .where(
            NotificationLog.recipient == user["sub"],
            NotificationLog.channel == "in_app",
            NotificationLog.status == "unread",
        )
        .values(status="read", read_at=now)
    )
    await db.flush()
    return {"detail": "全部已读"}
