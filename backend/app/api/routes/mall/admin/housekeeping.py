"""
/api/mall/admin/housekeeping/*

管理员手动触发定时任务（方便调试 + 异常恢复）。
每个端点都不依赖当前请求的 db session，service 内部开 admin_session_factory。
"""
from fastapi import APIRouter

from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.services.mall import housekeeping_service as hk

router = APIRouter()


@router.post("/detect-unclaimed-timeout")
async def detect_unclaimed_timeout(user: CurrentUser):
    require_role(user, "admin", "boss")
    return await hk.job_detect_unclaimed_timeout()


@router.post("/archive-inactive")
async def archive_inactive(user: CurrentUser):
    require_role(user, "admin", "boss")
    return await hk.job_archive_inactive_consumers()


@router.post("/detect-partial-close")
async def detect_partial_close(user: CurrentUser):
    require_role(user, "admin", "boss")
    return await hk.job_detect_partial_close()


@router.post("/purge-login-logs")
async def purge_login_logs(user: CurrentUser):
    require_role(user, "admin", "boss")
    return await hk.job_purge_old_login_logs()
