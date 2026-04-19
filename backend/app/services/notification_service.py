"""
Notification service — creates in-app notifications for order lifecycle events.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import NotificationLog
from app.models.user import Role, User, UserRole


async def notify(
    db: AsyncSession,
    *,
    recipient_id: str,
    title: str,
    content: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Create a single in-app notification."""
    n = NotificationLog(
        id=str(uuid.uuid4()),
        channel="in_app",
        recipient=recipient_id,
        title=title,
        content=content,
        related_entity_type=entity_type,
        related_entity_id=entity_id,
        status="unread",
    )
    db.add(n)


async def notify_roles(
    db: AsyncSession,
    *,
    role_codes: list[str],
    title: str,
    content: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Create notifications for all users with the given role codes."""
    stmt = (
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.code.in_(role_codes), User.is_active == True)
        .distinct()
    )
    rows = (await db.execute(stmt)).scalars().all()
    for uid in rows:
        await notify(
            db,
            recipient_id=uid,
            title=title,
            content=content,
            entity_type=entity_type,
            entity_id=entity_id,
        )
