"""
/api/mall/admin/skip-alerts/*

运营处理跳单告警：
  GET    /            列表（含客户/业务员昵称、订单数、是否申诉、审计状态）
  GET    /{id}        详情（含触发的 skip_logs + 申诉信息）
  POST   /{id}/resolve  通过（resolved）/ 驳回（dismissed）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.order import (
    MallCustomerSkipLog,
    MallOrder,
    MallSkipAlert,
)
from app.models.mall.user import MallUser
from app.services.mall import order_service

router = APIRouter()


@router.get("")
async def list_alerts(
    user: CurrentUser,
    status: Optional[str] = Query(default=None, description="open / resolved / dismissed"),
    has_appeal: Optional[bool] = Query(default=None, description="True=只看有申诉的"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = select(MallSkipAlert)
    if status:
        stmt = stmt.where(MallSkipAlert.status == status)
    if has_appeal is True:
        stmt = stmt.where(MallSkipAlert.appeal_reason.isnot(None))
    elif has_appeal is False:
        stmt = stmt.where(MallSkipAlert.appeal_reason.is_(None))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallSkipAlert.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    # 批量关联 customer / salesman 昵称
    user_ids = list({u for r in rows for u in [r.customer_user_id, r.salesman_user_id]})
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    def _user(uid: str) -> Optional[dict]:
        u = user_map.get(uid)
        return {
            "id": u.id,
            "nickname": u.nickname,
            "phone": u.phone,
        } if u else None

    records = []
    for r in rows:
        records.append({
            "id": r.id,
            "customer": _user(r.customer_user_id),
            "salesman": _user(r.salesman_user_id),
            "skip_count": r.skip_count,
            "status": r.status,
            "appeal_reason": r.appeal_reason,
            "appeal_at": r.appeal_at,
            "resolved_at": r.resolved_at,
            "resolution_note": r.resolution_note,
            "trigger_log_ids": r.trigger_log_ids or [],
            "created_at": r.created_at,
        })
    return {"records": records, "total": total}


@router.get("/{alert_id}")
async def get_alert_detail(
    alert_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """详情：把 trigger_log_ids 对应的 skip_logs 查出来，附带订单号。"""
    require_role(user, "admin", "boss")
    alert = await db.get(MallSkipAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在")

    # 参与方
    customer = await db.get(MallUser, alert.customer_user_id)
    salesman = await db.get(MallUser, alert.salesman_user_id)

    # 触发的 skip_logs
    log_ids = alert.trigger_log_ids or []
    logs = (await db.execute(
        select(MallCustomerSkipLog)
        .where(MallCustomerSkipLog.id.in_(log_ids))
        .order_by(desc(MallCustomerSkipLog.created_at))
    )).scalars().all() if log_ids else []

    # 每条 skip_log 关联的订单号
    order_ids = list({l.order_id for l in logs if l.order_id})
    orders = (await db.execute(
        select(MallOrder).where(MallOrder.id.in_(order_ids))
    )).scalars().all() if order_ids else []
    order_map = {o.id: o for o in orders}

    return {
        "id": alert.id,
        "customer": ({
            "id": customer.id,
            "nickname": customer.nickname,
            "phone": customer.phone,
        } if customer else None),
        "salesman": ({
            "id": salesman.id,
            "nickname": salesman.nickname,
            "phone": salesman.phone,
        } if salesman else None),
        "skip_count": alert.skip_count,
        "status": alert.status,
        "appeal_reason": alert.appeal_reason,
        "appeal_at": alert.appeal_at,
        "resolved_at": alert.resolved_at,
        "resolution_note": alert.resolution_note,
        "resolved_by_user_id": alert.resolved_by_user_id,
        "resolved_by_type": alert.resolved_by_type,
        "created_at": alert.created_at,
        "skip_logs": [
            {
                "id": l.id,
                "order_id": l.order_id,
                "order_no": order_map.get(l.order_id).order_no if order_map.get(l.order_id) else None,
                "order_status": order_map.get(l.order_id).status if order_map.get(l.order_id) else None,
                "skip_type": l.skip_type,
                "dismissed": l.dismissed,
                "created_at": l.created_at,
            }
            for l in logs
        ],
    }


class _ResolveBody(BaseModel):
    resolution_status: str = Field(pattern="^(resolved|dismissed)$")
    note: Optional[str] = None


@router.post("/{alert_id}/resolve")
async def resolve(
    alert_id: str,
    body: _ResolveBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """处理告警：
    - resolved：确认跳单成立，业务员需承担后果（跳单计数保留，未来触发新告警）
    - dismissed：驳回（业务员申诉有理），对应 skip_logs 标 dismissed，不计入下次阈值
    """
    require_role(user, "admin", "boss")
    alert = await order_service.resolve_skip_alert(
        db, alert_id,
        operator_id=user["sub"],
        operator_type="erp_user",
        resolution_status=body.resolution_status,
        note=body.note,
        request=request,
        actor_employee_id=user.get("employee_id"),
    )
    return {
        "id": alert.id,
        "status": alert.status,
        "resolved_at": alert.resolved_at,
        "resolution_note": alert.resolution_note,
    }
