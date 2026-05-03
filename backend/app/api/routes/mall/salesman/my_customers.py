"""
/api/mall/salesman/my-customers

列出 referrer_salesman_id == 当前业务员的 consumer。
业务员看自己开发的客户：返回完整 phone（含注册时的 contact_phone）+ 默认地址（供一键导航）
非业务员或被推荐的上级看不到这个端点（_require_salesman 挡掉）
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.base import MallOrderStatus, MallUserStatus
from app.models.mall.order import MallOrder
from app.models.mall.user import MallAddress, MallUser
from app.services.mall import auth_service

router = APIRouter()


@router.get("")
async def my_customers(
    current: CurrentMallUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_mall_db),
):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    user = await auth_service.verify_token_and_load_user(db, current)

    base = select(MallUser).where(MallUser.referrer_salesman_id == user.id)
    total = int((
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0)

    customers = (await db.execute(
        base.order_by(desc(MallUser.referrer_bound_at)).offset(skip).limit(limit)
    )).scalars().all()

    # 一次查全部 customer 的订单统计（避免 N+1）
    customer_ids = [c.id for c in customers]
    stats_map: dict[str, dict] = {}
    total_gmv_server = Decimal("0")
    # 默认地址（或第一个地址）用于一键导航
    default_addr_map: dict[str, MallAddress] = {}
    if customer_ids:
        rows = (await db.execute(
            select(
                MallOrder.user_id,
                func.count(MallOrder.id).label("cnt"),
                func.coalesce(func.sum(MallOrder.received_amount), 0).label("gmv"),
            )
            .where(MallOrder.user_id.in_(customer_ids))
            .where(MallOrder.status.in_([
                MallOrderStatus.COMPLETED.value,
                MallOrderStatus.PARTIAL_CLOSED.value,
            ]))
            .group_by(MallOrder.user_id)
        )).all()
        for user_id, cnt, gmv in rows:
            stats_map[user_id] = {"cnt": int(cnt), "gmv": Decimal(str(gmv or 0))}
            total_gmv_server += Decimal(str(gmv or 0))

        addr_rows = (await db.execute(
            select(MallAddress)
            .where(MallAddress.user_id.in_(customer_ids))
            .order_by(desc(MallAddress.is_default), desc(MallAddress.created_at))
        )).scalars().all()
        for a in addr_rows:
            # 只保留第一个（按 is_default desc + created_at desc 后的首条）
            default_addr_map.setdefault(a.user_id, a)

    records = []
    for c in customers:
        s = stats_map.get(c.id, {"cnt": 0, "gmv": Decimal("0")})
        # 业务员看自己开发的客户，电话放完整值方便一键拨号
        # 优先 contact_phone（注册审批填的）—— phone 是微信拉回的手机号，可能为空
        phone_full = c.contact_phone or c.phone
        addr = default_addr_map.get(c.id)
        records.append({
            "id": c.id,
            "nickname": c.nickname,
            "real_name": c.real_name,
            "phone": phone_full,
            "status": c.status,
            "archived": c.status == MallUserStatus.INACTIVE_ARCHIVED.value,
            "bound_at": c.referrer_bound_at,
            "last_order_at": c.last_order_at,
            "total_orders": s["cnt"],
            "total_gmv": str(s["gmv"]),
            "default_address": (
                {
                    "receiver": addr.receiver,
                    "mobile": addr.mobile,
                    "province": addr.province,
                    "city": addr.city,
                    "area": addr.area,
                    "addr": addr.addr,
                } if addr else None
            ),
        })

    return {
        "records": records,
        "total": total,
        "total_gmv": str(total_gmv_server),
    }
