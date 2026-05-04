"""
/api/mall/workspace/my-commissions/*

业务员自己的 commission 流水（G6 透明化）。

核心场景：
  - 业务员 3 月工资少拿 ¥500，点开 commission 流水看到"xxx 订单退货冲销 -¥500"
  - 跨月追回（is_adjustment=True, amount 负数）能看到"对应原订单 / 原 commission / 原因"
  - pending / settled / reversed 三种状态都要能看到

端点：
  GET  /my-commissions?status=all|pending|settled|reversed|adjustment
  GET  /my-commissions/stats?year=YYYY&month=MM  汇总当月 pending/settled/reversed/adjustment
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.order import MallOrder
from app.models.store_sale import StoreSale
from app.models.user import Commission
from app.services.mall import auth_service


router = APIRouter()


async def _require_salesman(current, db: AsyncSession):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="账号未绑定员工记录")
    return user


async def _enrich_commission(db: AsyncSession, com: Commission) -> dict:
    """把 Commission 转成 dict 并注入原订单号 + adjustment 来源。"""
    d = {
        "id": com.id,
        "brand_id": com.brand_id,
        "commission_amount": str(com.commission_amount),
        "status": com.status,
        "is_adjustment": bool(com.is_adjustment),
        "adjustment_source_commission_id": com.adjustment_source_commission_id,
        "notes": com.notes,
        "created_at": com.created_at,
        "settled_at": com.settled_at,
    }

    # 找源订单（mall/store/b2b）
    if com.mall_order_id:
        mo = await db.get(MallOrder, com.mall_order_id)
        d["order_no"] = mo.order_no if mo else None
        d["ref_type"] = "mall_order"
        d["ref_id"] = com.mall_order_id
    elif com.store_sale_id:
        ss = await db.get(StoreSale, com.store_sale_id)
        d["order_no"] = ss.sale_no if ss else None
        d["ref_type"] = "store_sale"
        d["ref_id"] = com.store_sale_id
    elif com.order_id:
        from app.models.order import Order as _Ord
        bo = await db.get(_Ord, com.order_id)
        d["order_no"] = bo.order_no if bo else None
        d["ref_type"] = "b2b_order"
        d["ref_id"] = com.order_id
    else:
        d["order_no"] = None
        d["ref_type"] = "unknown"
        d["ref_id"] = None

    # 追回类的展示原 commission 金额作对照
    if com.is_adjustment and com.adjustment_source_commission_id:
        origin = await db.get(Commission, com.adjustment_source_commission_id)
        if origin:
            d["origin_commission_amount"] = str(origin.commission_amount)
            d["origin_status"] = origin.status
            d["origin_settled_at"] = origin.settled_at
    return d


@router.get("")
async def list_my_commissions(
    current: CurrentMallUser,
    status: str = Query(default="all"),  # all|pending|settled|reversed|adjustment
    year: Optional[int] = None,
    month: Optional[int] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_mall_db),
):
    """业务员查自己的 commission 流水。

    - status=adjustment 仅返追回单（is_adjustment=True）
    - 按 created_at 倒序；year+month 支持按月筛（默认全部）
    """
    user = await _require_salesman(current, db)
    stmt = select(Commission).where(Commission.employee_id == user.linked_employee_id)

    if status == "pending":
        stmt = stmt.where(Commission.status == "pending")
    elif status == "settled":
        stmt = stmt.where(Commission.status == "settled")
    elif status == "reversed":
        stmt = stmt.where(Commission.status == "reversed")
    elif status == "adjustment":
        stmt = stmt.where(Commission.is_adjustment.is_(True))
    # all: 不加状态条件

    if year:
        # 按月筛（按 created_at 落区间）
        from datetime import timezone
        m = month or 1
        start = datetime(year, m, 1, tzinfo=timezone.utc)
        if month:
            if month == 12:
                end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        stmt = stmt.where(Commission.created_at >= start, Commission.created_at < end)

    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)

    rows = (await db.execute(
        stmt.order_by(desc(Commission.created_at)).offset(skip).limit(limit)
    )).scalars().all()

    records = []
    for com in rows:
        records.append(await _enrich_commission(db, com))

    return {"records": records, "total": total}


@router.get("/stats")
async def my_commission_stats(
    current: CurrentMallUser,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    """按 status 汇总当月（或指定年月）commission 金额 + 数量。"""
    user = await _require_salesman(current, db)

    from datetime import timezone
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)

    rows = (await db.execute(
        select(
            Commission.status,
            Commission.is_adjustment,
            func.count(Commission.id),
            func.coalesce(func.sum(Commission.commission_amount), 0),
        )
        .where(Commission.employee_id == user.linked_employee_id)
        .where(Commission.created_at >= start, Commission.created_at < end)
        .group_by(Commission.status, Commission.is_adjustment)
    )).all()

    # 展平为前端友好结构
    by_status = {
        "pending": {"count": 0, "amount": "0"},
        "settled": {"count": 0, "amount": "0"},
        "reversed": {"count": 0, "amount": "0"},
    }
    adjustment = {"count": 0, "amount": "0"}
    for st, is_adj, cnt, amt in rows:
        if is_adj:
            adjustment["count"] += int(cnt)
            adjustment["amount"] = str(
                Decimal(adjustment["amount"]) + Decimal(str(amt or 0))
            )
        else:
            slot = by_status.setdefault(st, {"count": 0, "amount": "0"})
            slot["count"] += int(cnt)
            slot["amount"] = str(
                Decimal(slot["amount"]) + Decimal(str(amt or 0))
            )

    return {
        "year": y,
        "month": m,
        "by_status": by_status,
        "adjustment": adjustment,  # 负数追回
    }
