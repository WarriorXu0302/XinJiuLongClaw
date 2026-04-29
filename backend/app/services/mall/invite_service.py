"""
Mall 邀请码服务。

核心规则（plan 决策 #1 / #15）：
  - 有效期 MALL_INVITE_CODE_TTL_MINUTES（默认 120 分钟）
  - 每业务员每日上限 MALL_INVITE_CODE_DAILY_LIMIT（默认 20）
  - 8 位短码，排除易混字符 0/O/1/l/I
  - 消费走 SQL FOR UPDATE 原子化，防并发双用
  - 业务员可主动作废未用码（invalidated_at）
"""
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mall.base import MallUserType
from app.models.mall.user import MallInviteCode, MallUser


# 全大写：小程序前端会 toUpperCase，必须签发大写码避免查不到
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


_TZ_BJ = ZoneInfo("Asia/Shanghai")


async def _count_today_codes(db: AsyncSession, issuer_id: str) -> int:
    """统计业务员"当日"（北京时区）已签发的邀请码数。

    业务边界是北京时间 00:00，不是 UTC 00:00，否则北京时间 00–08 点会和前一天合并计数。
    """
    now_bj = datetime.now(_TZ_BJ)
    today_start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    # 存 DB 的 created_at 是 timestamptz，和 aware datetime 比较会自动转成 UTC
    stmt = (
        select(func.count(MallInviteCode.id))
        .where(MallInviteCode.issuer_salesman_id == issuer_id)
        .where(MallInviteCode.created_at >= today_start_bj)
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def generate_invite_code(
    db: AsyncSession, salesman: MallUser
) -> MallInviteCode:
    """业务员签发一张邀请码。超过今日上限抛 429。"""
    if salesman.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅业务员可生成邀请码")

    today_count = await _count_today_codes(db, salesman.id)
    if today_count >= settings.MALL_INVITE_CODE_DAILY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日邀请码已达上限（{settings.MALL_INVITE_CODE_DAILY_LIMIT} 张）",
            headers={"Retry-After": "86400"},
        )

    # 极小概率碰撞，重试几次
    code = _generate_code()
    for _ in range(5):
        existing = await db.execute(
            select(MallInviteCode.id)
            .where(MallInviteCode.code == code)
            .where(MallInviteCode.expires_at > func.now())
            .where(MallInviteCode.used_at.is_(None))
            .where(MallInviteCode.invalidated_at.is_(None))
        )
        if existing.first() is None:
            break
        code = _generate_code()
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邀请码生成失败，请重试",
        )

    now = datetime.now(timezone.utc)
    invite = MallInviteCode(
        code=code,
        issuer_salesman_id=salesman.id,
        expires_at=now + timedelta(minutes=settings.MALL_INVITE_CODE_TTL_MINUTES),
    )
    db.add(invite)
    await db.flush()
    return invite


async def consume_invite_code(db: AsyncSession, code: str) -> MallInviteCode:
    """原子消费邀请码。必须在事务内调用；成功返回 MallInviteCode（未写 used_at）。

    调用方按需再调 mark_invite_used() 把 used_at/used_by_user_id 回填。
    """
    code_norm = (code or "").strip().upper()
    if not code_norm:
        raise HTTPException(status_code=400, detail="邀请码必填")
    stmt = (
        select(MallInviteCode)
        .where(MallInviteCode.code == code_norm)
        .with_for_update()
    )
    row = (await db.execute(stmt)).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=400, detail="邀请码不存在")
    if row.invalidated_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已作废")
    if row.used_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已被使用")
    if row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="邀请码已过期")

    return row


async def mark_invite_used(
    db: AsyncSession, invite: MallInviteCode, used_by_user_id: str
) -> None:
    """消费成功回填。调用前必须已 FOR UPDATE 锁定。"""
    invite.used_at = datetime.now(timezone.utc)
    invite.used_by_user_id = used_by_user_id
    await db.flush()


async def invalidate_invite_code(
    db: AsyncSession, salesman: MallUser, code_id: str, reason: str | None = None
) -> MallInviteCode:
    """业务员主动作废自己签发的未用邀请码。"""
    row = (
        await db.execute(
            select(MallInviteCode)
            .where(MallInviteCode.id == code_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    if row.issuer_salesman_id != salesman.id:
        raise HTTPException(status_code=403, detail="无权作废他人邀请码")
    if row.used_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已被使用，无法作废")
    if row.invalidated_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已作废")

    row.invalidated_at = datetime.now(timezone.utc)
    row.invalidated_reason = reason
    await db.flush()
    return row


async def list_recent_codes(
    db: AsyncSession, salesman: MallUser, limit: int = 10
) -> list[MallInviteCode]:
    stmt = (
        select(MallInviteCode)
        .where(MallInviteCode.issuer_salesman_id == salesman.id)
        .order_by(MallInviteCode.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())
