"""
/api/mall/admin/housekeeping/*

管理员手动触发定时任务（方便调试 + 异常恢复） + 查执行历史。
每个 POST 端点都把 ContextVar 设为 'manual'，让 job_log 正确标记触发源。
每个端点都不依赖当前请求的 db session，service 内部开 admin_session_factory。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.user import MallJobLog
from app.services.mall import housekeeping_service as hk

router = APIRouter()


def _mark_manual():
    hk.set_job_trigger("manual")


@router.post("/detect-unclaimed-timeout")
async def detect_unclaimed_timeout(user: CurrentUser):
    require_role(user, "admin", "boss")
    _mark_manual()
    return await hk.job_detect_unclaimed_timeout()


@router.post("/archive-inactive")
async def archive_inactive(user: CurrentUser):
    require_role(user, "admin", "boss")
    _mark_manual()
    return await hk.job_archive_inactive_consumers()


@router.post("/notify-archive-pre-notice")
async def notify_archive_pre_notice(user: CurrentUser):
    require_role(user, "admin", "boss")
    _mark_manual()
    return await hk.job_notify_archive_pre_notice()


@router.post("/detect-partial-close")
async def detect_partial_close(user: CurrentUser):
    require_role(user, "admin", "boss")
    _mark_manual()
    return await hk.job_detect_partial_close()


@router.post("/purge-login-logs")
async def purge_login_logs(user: CurrentUser):
    require_role(user, "admin", "boss")
    _mark_manual()
    return await hk.job_purge_old_login_logs()


# =============================================================================
# 执行历史查询（admin 能看到每个定时任务什么时候跑了、耗时、结果）
# =============================================================================

@router.get("/logs")
async def list_job_logs(
    user: CurrentUser,
    job_name: Optional[str] = Query(default=None, description="按 job_name 过滤"),
    status: Optional[str] = Query(default=None, pattern="^(success|error)$"),
    trigger: Optional[str] = Query(default=None, pattern="^(scheduler|manual)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """定时任务执行历史，按 started_at desc 排序。"""
    require_role(user, "admin", "boss")
    stmt = select(MallJobLog)
    if job_name:
        stmt = stmt.where(MallJobLog.job_name == job_name)
    if status:
        stmt = stmt.where(MallJobLog.status == status)
    if trigger:
        stmt = stmt.where(MallJobLog.trigger == trigger)

    total = int((
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(MallJobLog.started_at)).offset(skip).limit(limit)
    )).scalars().all()

    return {
        "records": [
            {
                "id": r.id,
                "job_name": r.job_name,
                "trigger": r.trigger,
                "status": r.status,
                "result": r.result,
                "error_message": r.error_message,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/logs/summary")
async def job_logs_summary(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """各 job 的最近一次执行状态（看板用）。"""
    require_role(user, "admin", "boss")
    # 相关子查询：每个 job_name 取 max(started_at)
    from sqlalchemy import and_
    latest_subq = (
        select(
            MallJobLog.job_name,
            func.max(MallJobLog.started_at).label("latest"),
        )
        .group_by(MallJobLog.job_name)
        .subquery()
    )
    stmt = (
        select(MallJobLog)
        .join(
            latest_subq,
            and_(
                MallJobLog.job_name == latest_subq.c.job_name,
                MallJobLog.started_at == latest_subq.c.latest,
            ),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {
                "job_name": r.job_name,
                "trigger": r.trigger,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "result": r.result,
                "error_message": r.error_message,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ],
    }
