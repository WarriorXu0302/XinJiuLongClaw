"""
/api/mall/orders/*  （C 端订单）
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.user import MallUser
from app.schemas.mall.order import (
    MallCourierVO,
    MallOrderCancelRequest,
    MallOrderCreateRequest,
    MallOrderDetailVO,
    MallOrderItemVO,
    MallOrderListItemVO,
    MallOrderPreviewRequest,
    MallOrderPreviewResponse,
    MallOrderStatsVO,
)
from app.schemas.mall.product import MallPage
from app.services.mall import auth_service, order_service
from app.services.mall.pricing_service import apply_price_visibility

router = APIRouter()


# =============================================================================
# Preview
# =============================================================================

@router.post("/preview", response_model=MallOrderPreviewResponse)
async def preview(
    body: MallOrderPreviewRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    result = await order_service.preview_order(
        db, user,
        items=[{"sku_id": i.sku_id, "quantity": i.quantity} for i in body.items],
        address_id=body.address_id,
    )
    return MallOrderPreviewResponse.model_validate(result)


# =============================================================================
# Create
# =============================================================================

@router.post("", response_model=MallOrderDetailVO)
async def create(
    body: MallOrderCreateRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.create_order(
        db, user,
        items=[{"sku_id": i.sku_id, "quantity": i.quantity} for i in body.items],
        address_id=body.address_id,
        remarks=body.remarks,
    )
    items = await order_service.get_order_items(db, order.id)
    return await _build_detail_vo(db, order, items)


# =============================================================================
# List / stats / detail
# =============================================================================

@router.get("/stats", response_model=MallOrderStatsVO)
async def stats(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    return MallOrderStatsVO(**await order_service.order_stats(db, user))


@router.get("", response_model=MallPage)
async def list_orders(
    current: CurrentMallUser,
    status: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows, total = await order_service.list_my_orders(db, user, status, skip, limit)
    pages = max((total + limit - 1) // limit, 1)
    return MallPage(
        records=[MallOrderListItemVO.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        pages=pages,
        current=min(skip // limit + 1, pages),
    )


@router.get("/{order_no}", response_model=MallOrderDetailVO)
async def detail(
    order_no: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.get_my_order(db, user, order_no)
    items = await order_service.get_order_items(db, order.id)
    return await _build_detail_vo(db, order, items)


# =============================================================================
# Cancel / Confirm receipt
# =============================================================================

@router.post("/{order_no}/cancel", response_model=MallOrderDetailVO)
async def cancel(
    order_no: str,
    current: CurrentMallUser,
    request: Request,
    body: Optional[MallOrderCancelRequest] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.cancel_order(
        db, user, order_no, reason=body.reason if body else None,
        request=request,
    )
    items = await order_service.get_order_items(db, order.id)
    return await _build_detail_vo(db, order, items)


@router.delete("/{order_no}", status_code=204)
async def delete_order(
    order_no: str,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    """C 端从列表删除（软删）。仅 completed/cancelled/partial_closed 可删。"""
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    await order_service.delete_my_order(db, user, order_no, request=request)


@router.post("/{order_no}/confirm-receipt", response_model=MallOrderDetailVO)
async def confirm_receipt(
    order_no: str,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    await apply_price_visibility(current, db)
    user = await auth_service.verify_token_and_load_user(db, current)
    order = await order_service.confirm_receipt(db, user, order_no, request=request)
    items = await order_service.get_order_items(db, order.id)
    return await _build_detail_vo(db, order, items)


# =============================================================================
# 物流查询（业务员自配送 —— 返回订单当前履约状态 + 配送员信息）
# =============================================================================

@router.get("/{order_no}/logistics")
async def logistics(
    order_no: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """
    返回订单物流/履约轨迹。第一版是业务员自配送，无第三方物流 tracking；
    但小程序"查看物流"按钮必须有响应，所以构造一个规范化的 tracks 时间线：
      下单 → 接单 → 出库 → 送达 → 客户确认
    """
    from sqlalchemy import select
    from app.models.mall.order import MallOrder, MallShipment

    user = await auth_service.verify_token_and_load_user(db, current)
    order = (await db.execute(
        select(MallOrder)
        .where(MallOrder.order_no == order_no)
        .where(MallOrder.user_id == user.id)  # 防越权
    )).scalar_one_or_none()
    if order is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="订单不存在")

    shipment = (await db.execute(
        select(MallShipment).where(MallShipment.order_id == order.id)
    )).scalar_one_or_none()

    # 构造轨迹
    tracks: list[dict] = []
    if order.created_at:
        tracks.append({
            "at": order.created_at, "title": "订单已下单",
            "desc": f"订单 {order.order_no} 提交成功，等待业务员接单",
        })
    if order.claimed_at:
        tracks.append({
            "at": order.claimed_at, "title": "业务员已接单",
            "desc": "业务员已接单，正在备货",
        })
    if order.shipped_at:
        tracks.append({
            "at": order.shipped_at, "title": "已出库",
            "desc": "商品已出库，正在配送",
        })
    if order.delivered_at:
        tracks.append({
            "at": order.delivered_at, "title": "已送达",
            "desc": "商品已送达，请确认收货",
        })
    if order.customer_confirmed_at:
        tracks.append({
            "at": order.customer_confirmed_at, "title": "您已确认收货",
            "desc": "感谢您的购买",
        })
    if order.cancelled_at:
        tracks.append({
            "at": order.cancelled_at, "title": "订单已取消",
            "desc": order.cancellation_reason or "—",
        })

    # 配送员信息（已接单后才暴露）
    courier = None
    if order.assigned_salesman_id:
        salesman = await db.get(MallUser, order.assigned_salesman_id)
        if salesman is not None:
            courier = {
                "nickname": salesman.nickname,
                "mobile": salesman.phone,
                "wechat_qr_url": salesman.wechat_qr_url,
                "alipay_qr_url": salesman.alipay_qr_url,
            }

    return {
        "order_no": order.order_no,
        "status": order.status,
        "carrier_name": shipment.carrier_name if shipment else "业务员自配送",
        "tracking_no": shipment.tracking_no if shipment else None,
        "courier": courier,
        "tracks": sorted(tracks, key=lambda t: t["at"], reverse=True),
    }


# =============================================================================
# 内部工具
# =============================================================================

async def _build_detail_vo(db: AsyncSession, order, items) -> MallOrderDetailVO:
    vo = MallOrderDetailVO.model_validate(order, from_attributes=True)
    vo.items = [
        MallOrderItemVO.model_validate({
            "product_id": it.product_id,
            "sku_id": it.sku_id,
            "prod_name": (it.sku_snapshot or {}).get("product_name"),
            "sku_name": (it.sku_snapshot or {}).get("sku_name"),
            "pic": (it.sku_snapshot or {}).get("pic"),
            "price": it.price,
            "quantity": it.quantity,
            "subtotal": it.subtotal,
        })
        for it in items
    ]
    # 配送员信息：只有被接单后（assigned_salesman_id 非空）才填
    if order.assigned_salesman_id:
        salesman = await db.get(MallUser, order.assigned_salesman_id)
        if salesman is not None:
            vo.courier = MallCourierVO(
                nickname=salesman.nickname,
                mobile=salesman.phone,
                wechat_qr_url=salesman.wechat_qr_url,
                alipay_qr_url=salesman.alipay_qr_url,
            )
    return vo
