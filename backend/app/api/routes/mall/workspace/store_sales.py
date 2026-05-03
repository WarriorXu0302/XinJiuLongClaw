"""
/api/mall/workspace/store-sales/*

小程序店员端收银。

流程：
  1. 店员扫码前先调 /verify-barcode 预校验一瓶（返回商品信息 + 售价区间），可选步骤
  2. 填客户 + 扫完所有瓶 + 输入售价 + 选付款方式 → POST /  提交
  3. 成功后获得 sale_no，小程序端展示完成页
  4. /my/sales 查自己的销售流水；/my/summary 查本月业绩

权限：mall_user.user_type='salesman' AND mall_user.assigned_store_id 非空
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import InventoryBarcode
from app.models.mall.base import MallUserType
from app.models.mall.user import MallUser
from app.models.product import Product, Warehouse
from app.models.store_sale import StoreSale, StoreSaleItem
from app.services import store_sale_service
from app.services.mall import auth_service


router = APIRouter()


# =============================================================================
# 权限工具
# =============================================================================


async def _require_cashier(current, db: AsyncSession) -> MallUser:
    """仅店员可访问：user_type='salesman' + assigned_store_id 非空 + linked_employee 在职"""
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅店员可访问")
    if not user.assigned_store_id:
        raise HTTPException(status_code=403, detail="您不是门店店员")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="账号未绑定员工记录")

    # 校验 store 仓是 store 类型且 active
    store = await db.get(Warehouse, user.assigned_store_id)
    if store is None or store.warehouse_type != WarehouseType.STORE.value:
        raise HTTPException(status_code=400, detail="归属门店仓非法")
    if not store.is_active:
        raise HTTPException(status_code=400, detail=f"门店 {store.name} 已停用")

    return user


# =============================================================================
# 扫码预校验（可选）
# =============================================================================


@router.get("/verify-barcode")
async def verify_barcode(
    barcode: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """店员扫一瓶时实时预校验：条码在本店 + 状态 + 商品信息 + 售价区间"""
    user = await _require_cashier(current, db)

    bc = (await db.execute(
        select(InventoryBarcode).where(InventoryBarcode.barcode == barcode)
    )).scalar_one_or_none()
    if bc is None:
        return {"ok": False, "message": "条码不存在"}
    if bc.warehouse_id != user.assigned_store_id:
        return {"ok": False, "message": "条码不在本门店"}
    if bc.status != InventoryBarcodeStatus.IN_STOCK.value:
        return {"ok": False, "message": f"条码状态 {bc.status}，不可销售"}

    prod = await db.get(Product, bc.product_id)
    if prod is None:
        return {"ok": False, "message": "商品不存在"}
    if prod.min_sale_price is None or prod.max_sale_price is None:
        return {
            "ok": False,
            "message": f"商品「{prod.name}」未配置售价区间，请联系管理员",
            "product_id": prod.id,
            "product_name": prod.name,
        }
    return {
        "ok": True,
        "barcode": barcode,
        "product_id": prod.id,
        "product_name": prod.name,
        "spec": prod.spec,
        "min_sale_price": str(prod.min_sale_price),
        "max_sale_price": str(prod.max_sale_price),
    }


# =============================================================================
# 提交收银
# =============================================================================


class _LineItem(BaseModel):
    barcode: str
    sale_price: Decimal = Field(gt=0)


class _CreateBody(BaseModel):
    customer_id: str
    line_items: list[_LineItem] = Field(min_length=1)
    payment_method: str = Field(pattern="^(cash|wechat|alipay|card)$")
    notes: Optional[str] = Field(default=None, max_length=500)


@router.post("")
async def create_sale(
    body: _CreateBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_cashier(current, db)
    sale = await store_sale_service.create_store_sale(
        db,
        cashier_employee_id=user.linked_employee_id,
        store_id=user.assigned_store_id,
        customer_id=body.customer_id,
        line_items=[{"barcode": li.barcode, "sale_price": li.sale_price}
                    for li in body.line_items],
        payment_method=body.payment_method,
        notes=body.notes,
    )
    return {
        "sale_no": sale.sale_no,
        "total_sale_amount": str(sale.total_sale_amount),
        "total_profit": str(sale.total_profit),
        "total_commission": str(sale.total_commission),
        "total_bottles": sale.total_bottles,
        "payment_method": sale.payment_method,
    }


# =============================================================================
# 我的销售流水 + 本月汇总
# =============================================================================


@router.get("/my/sales")
async def list_my_sales(
    current: CurrentMallUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_cashier(current, db)
    stmt = (
        select(StoreSale)
        .where(StoreSale.cashier_employee_id == user.linked_employee_id)
        .order_by(desc(StoreSale.created_at))
    )
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()

    # 客户姓名注入
    cust_ids = list({r.customer_id for r in rows})
    cust_map = {}
    if cust_ids:
        for c in (await db.execute(
            select(MallUser).where(MallUser.id.in_(cust_ids))
        )).scalars():
            cust_map[c.id] = c.real_name or c.nickname or c.username or c.id[:8]

    return {
        "records": [
            {
                "id": r.id,
                "sale_no": r.sale_no,
                "customer_name": cust_map.get(r.customer_id),
                "total_sale_amount": str(r.total_sale_amount),
                "total_profit": str(r.total_profit),
                "total_commission": str(r.total_commission),
                "total_bottles": r.total_bottles,
                "payment_method": r.payment_method,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/my/summary")
async def my_summary(
    current: CurrentMallUser,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    """本月销售/利润/提成汇总（默认当月）。"""
    user = await _require_cashier(current, db)
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    # 下个月的 1 号
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)

    stmt = select(
        func.coalesce(func.sum(StoreSale.total_sale_amount), 0),
        func.coalesce(func.sum(StoreSale.total_profit), 0),
        func.coalesce(func.sum(StoreSale.total_commission), 0),
        func.coalesce(func.sum(StoreSale.total_bottles), 0),
        func.count(StoreSale.id),
    ).where(
        StoreSale.cashier_employee_id == user.linked_employee_id,
        StoreSale.created_at >= start,
        StoreSale.created_at < end,
    )
    row = (await db.execute(stmt)).one()
    return {
        "year": y,
        "month": m,
        "total_sale_amount": str(row[0]),
        "total_profit": str(row[1]),
        "total_commission": str(row[2]),
        "total_bottles": int(row[3] or 0),
        "sale_count": int(row[4] or 0),
    }


# =============================================================================
# 客户搜索（按手机 / 姓名，便于店员填客户）
# =============================================================================


@router.get("/customers/search")
async def search_customer(
    keyword: str = Query(..., min_length=2),
    current: CurrentMallUser = None,
    db: AsyncSession = Depends(get_mall_db),
):
    await _require_cashier(current, db)
    kw = f"%{keyword}%"
    rows = (await db.execute(
        select(MallUser)
        .where(MallUser.user_type == MallUserType.CONSUMER.value)
        .where(
            (MallUser.phone.ilike(kw))
            | (MallUser.real_name.ilike(kw))
            | (MallUser.nickname.ilike(kw))
            | (MallUser.contact_phone.ilike(kw))
        )
        .limit(20)
    )).scalars().all()
    return {
        "records": [
            {
                "id": c.id,
                "name": c.real_name or c.nickname or c.username,
                "phone": c.phone or c.contact_phone,
            }
            for c in rows
        ]
    }
