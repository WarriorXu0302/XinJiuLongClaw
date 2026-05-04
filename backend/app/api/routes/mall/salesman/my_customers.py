"""
/api/mall/salesman/my-customers

列出 referrer_salesman_id == 当前业务员的 consumer。
G16 隐私加固：列表默认返回脱敏手机号（138****1234），需要拨号时调 /{id}/phone 再获取完整号
并写审计日志，防批量导出。
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.base import MallOrderStatus, MallUserStatus
from app.models.mall.order import MallOrder
from app.models.mall.user import MallAddress, MallUser
from app.services.audit_service import log_audit
from app.services.mall import auth_service

router = APIRouter()


def _mask_phone(phone: str | None) -> str | None:
    """11 位手机号脱敏：138****1234。其他号码兜底保留末 4。"""
    if not phone:
        return None
    p = phone.strip()
    if len(p) == 11 and p.isdigit():
        return f"{p[:3]}****{p[-4:]}"
    if len(p) > 4:
        return f"{'*' * (len(p) - 4)}{p[-4:]}"
    return "***" + p[-1:]


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
        # G16：列表中手机号脱敏防批量导出；真要拨号调 /{id}/phone
        phone_full = c.contact_phone or c.phone
        addr = default_addr_map.get(c.id)
        records.append({
            "id": c.id,
            "nickname": c.nickname,
            "real_name": c.real_name,
            "phone": _mask_phone(phone_full),
            "status": c.status,
            "archived": c.status == MallUserStatus.INACTIVE_ARCHIVED.value,
            "bound_at": c.referrer_bound_at,
            "last_order_at": c.last_order_at,
            "total_orders": s["cnt"],
            "total_gmv": str(s["gmv"]),
            "default_address": (
                {
                    "receiver": addr.receiver,
                    # 地址里的手机号同样脱敏
                    "mobile": _mask_phone(addr.mobile),
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


@router.get("/{customer_id}/phone")
async def reveal_customer_phone(
    customer_id: str,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    """G16：业务员点"拨号"才揭开完整号 + 写审计防滥用。

    只允许查自己推荐的 consumer 的手机号，其他人 403。
    每次调用写 audit_log（action=mall_customer.reveal_phone），admin 可回查"谁看了谁电话"。
    """
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    user = await auth_service.verify_token_and_load_user(db, current)

    c = await db.get(MallUser, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    if c.referrer_salesman_id != user.id:
        raise HTTPException(status_code=403, detail="只能查看自己推荐的客户")

    phone_full = c.contact_phone or c.phone

    await log_audit(
        db,
        action="mall_customer.reveal_phone",
        entity_type="MallUser",
        entity_id=customer_id,
        mall_user_id=user.id,
        actor_type="mall_user",
        request=request,
        changes={
            "customer_id": customer_id,
            "customer_nickname": c.nickname,
        },
    )

    return {"phone": phone_full}
