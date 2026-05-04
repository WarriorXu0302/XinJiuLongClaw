"""
APScheduler 集成 — mall housekeeping 定时任务入口。

设计：
  - 单进程 in-process 调度器（生产单实例部署）
  - FastAPI lifespan 启动/关闭
  - 任务函数走 admin_session_factory，不受 RLS 限制，不依赖 JWT 上下文
  - 任何任务异常都 log + 不拉下其他任务
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# 全局 scheduler 单例
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


async def _safe_run(name: str, coro_func):
    """包一层：任务异常吞掉，防一个任务失败拖垮整个调度器。"""
    try:
        result = await coro_func()
        logger.info("[scheduler] %s 完成，结果=%s", name, result)
    except Exception as e:
        logger.exception("[scheduler] %s 失败：%s", name, e)


def register_mall_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册 mall 相关的全部定时任务。调用一次。"""
    from app.services.mall import housekeeping_service as hk

    # 1. 超时未接单扫描：每 5 分钟一次
    scheduler.add_job(
        lambda: _safe_run("detect_unclaimed_timeout", hk.job_detect_unclaimed_timeout),
        trigger=IntervalTrigger(minutes=5),
        id="mall_detect_unclaimed_timeout",
        replace_existing=True,
    )

    # 2. 用户归档：每天凌晨 2:10 跑
    scheduler.add_job(
        lambda: _safe_run("archive_inactive_consumers", hk.job_archive_inactive_consumers),
        trigger=CronTrigger(hour=2, minute=10),
        id="mall_archive_inactive_consumers",
        replace_existing=True,
    )

    # 3. 订单折损（60 天未全款）：每天凌晨 2:30
    scheduler.add_job(
        lambda: _safe_run("detect_partial_close", hk.job_detect_partial_close),
        trigger=CronTrigger(hour=2, minute=30),
        id="mall_detect_partial_close",
        replace_existing=True,
    )

    # 4. 登录日志清理：每天凌晨 3:00
    scheduler.add_job(
        lambda: _safe_run("purge_old_login_logs", hk.job_purge_old_login_logs),
        trigger=CronTrigger(hour=3, minute=0),
        id="mall_purge_old_login_logs",
        replace_existing=True,
    )

    # 5. 归档 7 天预告：每天凌晨 2:00（在 archive_inactive 之前跑）
    scheduler.add_job(
        lambda: _safe_run("notify_archive_pre_notice", hk.job_notify_archive_pre_notice),
        trigger=CronTrigger(hour=2, minute=0),
        id="mall_notify_archive_pre_notice",
        replace_existing=True,
    )

    # 6. 月度 KPI 快照：每月 1 号凌晨 0:05 冻结上月（决策 #2）
    from app.services.mall import kpi_snapshot_service as kss
    scheduler.add_job(
        lambda: _safe_run("build_last_month_kpi_snapshot", kss.job_build_last_month_snapshot),
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id="mall_kpi_snapshot_last_month",
        replace_existing=True,
    )

    # 7. 凭证超时告警（G15）：每小时扫一次 PENDING_CONFIRMATION > 24h / 48h
    scheduler.add_job(
        lambda: _safe_run("notify_aged_pending_vouchers", hk.job_notify_aged_pending_vouchers),
        trigger=CronTrigger(minute=15),  # 每小时 :15 跑
        id="mall_notify_aged_pending_vouchers",
        replace_existing=True,
    )

    logger.info("[scheduler] mall jobs 已注册: %s", [j.id for j in scheduler.get_jobs()])


def start_scheduler() -> None:
    sch = get_scheduler()
    if sch.running:
        return
    register_mall_jobs(sch)
    sch.start()
    logger.info("[scheduler] started")


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("[scheduler] stopped")


@asynccontextmanager
async def scheduler_lifespan():
    """给 FastAPI lifespan 用的上下文管理器（如果不想手动 start/stop 的话）。"""
    start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()
