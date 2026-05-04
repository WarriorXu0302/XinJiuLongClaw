"""
Mall housekeeping 定时任务。

由 APScheduler 调度（app/core/scheduler.py 注册），也可通过 admin 端点手动触发。

每个 `job_*` 函数自己开 admin_session_factory 事务，与 FastAPI 请求上下文隔离。

所有 job 都被 @_with_job_log 装饰器包裹，执行结果写入 mall_job_logs 表：
  - started_at / finished_at / duration_ms
  - status='success' + result (JSON) 或 status='error' + error_message
admin 可通过 GET /api/mall/admin/housekeeping/logs 查执行历史。
"""
import functools
import logging
import traceback
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import admin_session_factory
from app.models.mall.base import MallOrderStatus, MallUserStatus, MallUserType
from app.models.mall.order import MallCartItem, MallOrder
from app.models.mall.user import MallJobLog, MallLoginLog, MallUser

logger = logging.getLogger(__name__)

# 当前触发源：admin 端点调 job 前设置为 'manual'；否则默认 'scheduler'
_job_trigger_ctx: ContextVar[str] = ContextVar("mall_job_trigger", default="scheduler")


def set_job_trigger(trigger: str) -> None:
    """admin 端点调 job 前调：set_job_trigger('manual')。"""
    _job_trigger_ctx.set(trigger)


def _with_job_log(func_):
    """装饰器：把 job_* 的执行包成 mall_job_logs 一条记录。"""
    @functools.wraps(func_)
    async def wrapper(*args, **kwargs):
        started_at = datetime.now(timezone.utc)
        start_ts = started_at.timestamp()
        trigger = _job_trigger_ctx.get()
        job_name = func_.__name__
        status = "success"
        error_message = None
        result: dict | None = None
        try:
            result = await func_(*args, **kwargs)
            return result
        except Exception as exc:
            status = "error"
            error_message = (
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )[:2000]
            raise
        finally:
            finished_at = datetime.now(timezone.utc)
            duration_ms = int((finished_at.timestamp() - start_ts) * 1000)
            try:
                async with admin_session_factory() as s:
                    log = MallJobLog(
                        job_name=job_name,
                        trigger=trigger,
                        status=status,
                        result=result if isinstance(result, dict) else None,
                        error_message=error_message,
                        duration_ms=duration_ms,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                    s.add(log)
                    await s.commit()
            except Exception as log_exc:
                # 日志写入失败不影响 job 本身（打个 warn 就行）
                logger.warning("mall_job_log 写入失败: %s", log_exc)
    return wrapper


# =============================================================================
# 1. 超时未接单 → skip_log
# =============================================================================

@_with_job_log
async def job_detect_unclaimed_timeout() -> dict:
    """订单 pending_assignment 且超过独占期 → 给推荐人记 skip_log（幂等）。

    复用 order_service.detect_unclaimed_timeout。
    """
    from app.services.mall.order_service import detect_unclaimed_timeout
    async with admin_session_factory() as s:
        handled = await detect_unclaimed_timeout(s)
        await s.commit()
        return {"handled": handled}


# =============================================================================
# 2. 归档 3 级停用用户
# =============================================================================

async def _count_user_orders(s, user_id: str) -> int:
    """只统计 completed/partial_closed 的已成交订单数（未完成 / 取消不算）。"""
    return int((
        await s.execute(
            select(func.count(MallOrder.id))
            .where(MallOrder.user_id == user_id)
            .where(MallOrder.status.in_([
                MallOrderStatus.COMPLETED.value,
                MallOrderStatus.PARTIAL_CLOSED.value,
            ]))
        )
    ).scalar() or 0)


def _archive_threshold_days(order_count: int) -> int:
    """按 plan 决策 #2：
      - 0 单 → 30 天
      - 1-2 单 → 90 天
      - 3+ 单 → 180 天
    """
    if order_count == 0:
        return settings.MALL_INACTIVE_DAYS_NEW_USER
    if order_count <= 2:
        return settings.MALL_INACTIVE_DAYS_FEW_ORDERS
    return settings.MALL_INACTIVE_DAYS_LOYAL


@_with_job_log
async def job_archive_inactive_consumers() -> dict:
    """按 3 级停用策略归档不活跃消费者。

    归档条件：
      - user_type='consumer'
      - status='active'
      - 注册未下单：created_at 距今 > 30 天 且 last_order_at IS NULL
      - 有成交：last_order_at 距今 > 阈值（90 / 180）
    """
    now = datetime.now(timezone.utc)
    # 最小阈值 = 30 天；SQL 先粗过滤，再在 Python 里按订单数精判（避免全表扫描）
    min_threshold = min(
        settings.MALL_INACTIVE_DAYS_NEW_USER,
        settings.MALL_INACTIVE_DAYS_FEW_ORDERS,
        settings.MALL_INACTIVE_DAYS_LOYAL,
    )
    coarse_cutoff = now - timedelta(days=min_threshold)
    archived = 0
    archived_ids: list[str] = []
    async with admin_session_factory() as s:
        candidates = (await s.execute(
            select(MallUser)
            .where(MallUser.user_type == MallUserType.CONSUMER.value)
            .where(MallUser.status == MallUserStatus.ACTIVE.value)
            # 只挑"最近一次活跃"在最小阈值之前的（last_order_at 或 created_at）
            .where(
                func.coalesce(MallUser.last_order_at, MallUser.created_at) <= coarse_cutoff
            )
        )).scalars().all()

        for user in candidates:
            order_count = await _count_user_orders(s, user.id)
            days_threshold = _archive_threshold_days(order_count)
            reference = user.last_order_at or user.created_at
            if reference is None:
                continue
            elapsed = now - reference
            if elapsed < timedelta(days=days_threshold):
                continue

            # 安全阀：有"在途"订单的用户不归档（pending/assigned/shipped/delivered
            # /pending_payment_confirmation），业务员还在履约 / 财务还在审 → 归档会让业务员
            # 撞到"客户登不上账号"。等订单结清再归档
            in_flight = int((await s.execute(
                select(func.count(MallOrder.id))
                .where(MallOrder.user_id == user.id)
                .where(MallOrder.status.in_([
                    MallOrderStatus.PENDING_ASSIGNMENT.value,
                    MallOrderStatus.ASSIGNED.value,
                    MallOrderStatus.SHIPPED.value,
                    MallOrderStatus.DELIVERED.value,
                    MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
                ]))
            )).scalar() or 0)
            if in_flight > 0:
                continue

            user.status = MallUserStatus.INACTIVE_ARCHIVED.value
            user.archived_at = now
            user.token_version = (user.token_version or 0) + 1
            archived_ids.append(user.id)
            archived += 1

            # 审计：定时任务自动归档，合规追溯（actor=system）
            from app.services.audit_service import log_audit
            await log_audit(
                s, action="mall_user.auto_archive",
                entity_type="MallUser", entity_id=user.id,
                actor_type="system",
                changes={
                    "nickname": user.nickname,
                    "order_count": order_count,
                    "threshold_days": days_threshold,
                    "inactive_days": int(elapsed.days),
                },
            )

        # 批量清购物车（避免循环里每次单独 SQL）
        if archived_ids:
            await s.execute(
                delete(MallCartItem).where(MallCartItem.user_id.in_(archived_ids))
            )

        await s.commit()

    logger.info("[hk] archived %d consumers", archived)
    return {"archived": archived}


@_with_job_log
async def job_notify_archive_pre_notice() -> dict:
    """距归档 7 天给客户发预告通知。每天跑一次；避免重复推送。

    规则：距到期日在 [6.5, 7.5] 天窗口内发一次。
    幂等：查过去 8 天内该用户是否已收到过 title="账号即将停用提醒" 的通知，有则跳过
          （避免定时任务重试或手动触发时重复推送）
    """
    from app.services.notification_service import notify_mall_user
    from app.models.notification_log import NotificationLog

    now = datetime.now(timezone.utc)
    dedupe_cutoff = now - timedelta(days=8)
    notified = 0
    async with admin_session_factory() as s:
        candidates = (await s.execute(
            select(MallUser)
            .where(MallUser.user_type == MallUserType.CONSUMER.value)
            .where(MallUser.status == MallUserStatus.ACTIVE.value)
        )).scalars().all()

        for user in candidates:
            order_count = await _count_user_orders(s, user.id)
            days_threshold = _archive_threshold_days(order_count)
            reference = user.last_order_at or user.created_at
            if reference is None:
                continue
            archive_at = reference + timedelta(days=days_threshold)
            hours_until = (archive_at - now).total_seconds() / 3600
            if not (6 * 24 + 12 <= hours_until <= 7 * 24 + 12):
                continue

            # 幂等查重：8 天内已有同标题通知就跳过
            existing = (await s.execute(
                select(NotificationLog.id)
                .where(NotificationLog.mall_user_id == user.id)
                .where(NotificationLog.title == "账号即将停用提醒")
                .where(NotificationLog.created_at >= dedupe_cutoff)
                .limit(1)
            )).first()
            if existing:
                continue

            await notify_mall_user(
                s, mall_user_id=user.id,
                title="账号即将停用提醒",
                content=(
                    f"您的账号因长期未下单，将于 7 天后自动停用。"
                    "期间下单即可保留账号；需恢复请联系业务员。"
                ),
                entity_type="MallUser",
            )
            notified += 1
        await s.commit()
    logger.info("[hk] pre-archive notified=%d", notified)
    return {"notified": notified}


# =============================================================================
# 3. delivered 60 天未全款 → partial_closed
# =============================================================================

@_with_job_log
async def job_detect_partial_close() -> dict:
    """订单 delivered / pending_payment_confirmation 且 delivered_at 距今 > 60 天且未全款
    → status=partial_closed；若 received_amount > 0 且未生成提成则按已收额计提成。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.MALL_PARTIAL_CLOSE_DAYS
    )
    closed = 0
    with_commission = 0

    async with admin_session_factory() as s:
        # 只折损 delivered 状态的单（pending_payment_confirmation 表示凭证在审，
        # 归财务处理链路；不应被 auto-close 打断）
        candidates = (await s.execute(
            select(MallOrder)
            .where(MallOrder.status == MallOrderStatus.DELIVERED.value)
            .where(MallOrder.delivered_at.is_not(None))
            .where(MallOrder.delivered_at <= cutoff)
        )).scalars().all()

        for order in candidates:
            if (order.received_amount or Decimal("0")) >= order.pay_amount:
                # 实际已全款但状态未推进 → 走正常 confirm 不归 partial_close
                continue

            order.status = MallOrderStatus.PARTIAL_CLOSED.value
            order.payment_status = (
                "partially_paid" if (order.received_amount or 0) > 0 else "unpaid"
            )
            # 不写 order.completed_at —— partial_close 不是真正全款完成。
            # 后续若 admin 补款全款恢复，manual_record 会把 completed_at 设为那时；
            # 若永远没补齐，completed_at 保持 NULL 也符合业务语义（partial_closed_at 查 audit_logs）
            order.profit_ledger_posted = True  # 折损关单也入报表
            closed += 1

            # 审计：坏账折损（资金状态强制切换，必记）
            from app.services.audit_service import log_audit
            await log_audit(
                s, action="mall_order.partial_close",
                entity_type="MallOrder", entity_id=order.id,
                actor_type="system",
                changes={
                    "order_no": order.order_no,
                    "pay_amount": str(order.pay_amount),
                    "received_amount": str(order.received_amount or 0),
                    "bad_debt": str(order.pay_amount - (order.received_amount or Decimal("0"))),
                    "days_since_delivered": int(
                        (datetime.now(timezone.utc) - order.delivered_at).days
                    ) if order.delivered_at else None,
                },
            )

            # 累加商品销量（partial_closed 也算成交，只是没全款）
            from app.models.mall.product import MallProduct
            from app.services.mall import order_service
            items = await order_service.get_order_items(s, order.id)
            qty_by_product: dict[int, int] = {}
            for it in items:
                qty_by_product[it.product_id] = qty_by_product.get(it.product_id, 0) + it.quantity
            for pid, qty in qty_by_product.items():
                prod = await s.get(MallProduct, pid)
                if prod is not None:
                    # 决策 #4：total_sales 累计，net_sales 净销量（退货时扣）
                    prod.total_sales = (prod.total_sales or 0) + qty
                    prod.net_sales = (prod.net_sales or 0) + qty

            # 有已收才生成提成；post_commission_for_order 自身按差额幂等，无需额外 guard
            if (order.received_amount or 0) > 0:
                from app.services.mall.commission_service import (
                    post_commission_for_order,
                )
                rows = await post_commission_for_order(s, order)
                if rows:
                    with_commission += 1

            # 推通知给 assigned + referrer（如果不重复）；坏账关单对业务员有经济影响
            from app.services.notification_service import notify_mall_user
            bad_debt = order.pay_amount - (order.received_amount or Decimal("0"))
            notice_recipients = {x for x in (
                order.assigned_salesman_id,
                order.referrer_salesman_id,
            ) if x}
            for rid in notice_recipients:
                await notify_mall_user(
                    s, mall_user_id=rid,
                    title="订单坏账关单",
                    content=(
                        f"订单 {order.order_no} 送达 {settings.MALL_PARTIAL_CLOSE_DAYS} 天"
                        f"未全款，系统已关单折损，坏账 ¥{bad_debt}。"
                        "如客户补款请联系管理员走补录。"
                    ),
                    entity_type="MallOrder", entity_id=order.id,
                )

        await s.commit()

    logger.info("[hk] partial_closed=%d, with_commission=%d", closed, with_commission)
    return {"partial_closed": closed, "with_commission": with_commission}


# =============================================================================
# 4. 清 90 天前登录日志
# =============================================================================

@_with_job_log
async def job_purge_old_login_logs() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.MALL_LOGIN_LOG_RETENTION_DAYS
    )
    async with admin_session_factory() as s:
        result = await s.execute(
            delete(MallLoginLog).where(MallLoginLog.login_at < cutoff)
        )
        await s.commit()
        deleted = int(result.rowcount or 0)

    logger.info("[hk] purged %d login logs older than %s", deleted, cutoff)
    return {"deleted": deleted}
