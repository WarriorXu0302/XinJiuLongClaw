"""
/api/store-sales/*

门店零售销售流水（ERP 管理台视角）+ 提成率 CRUD。

端点：
  POST   /api/store-sales                          ERP 端/其他入口创建（通常不用，见小程序端）
  GET    /api/store-sales                          列表（boss/finance/warehouse/hr 可查）
  GET    /api/store-sales/{id}                     详情含明细
  GET    /api/store-sales/stats                    按日期 + 店聚合汇总

  GET    /api/retail-commission-rates              列表（按店员查）
  POST   /api/retail-commission-rates              新增（employee + product + rate）
  PUT    /api/retail-commission-rates/{id}         更新 rate
  DELETE /api/retail-commission-rates/{id}

小程序店员端走 /api/mall/workspace/store-sales/*（另起文件，见 workspace/store_sales.py）
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.user import MallUser
from app.models.product import Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate,
    StoreSale,
    StoreSaleItem,
)
from app.models.user import Employee
from app.services import store_sale_service
from app.services.audit_service import log_audit


router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class StoreSaleLineItem(BaseModel):
    barcode: str
    sale_price: Decimal = Field(gt=0)


class StoreSaleCreateBody(BaseModel):
    store_id: str
    cashier_employee_id: str
    customer_id: str
    line_items: list[StoreSaleLineItem] = Field(min_length=1)
    payment_method: str = Field(pattern="^(cash|wechat|alipay|card)$")
    notes: Optional[str] = Field(default=None, max_length=500)


class RetailCommissionRateCreateBody(BaseModel):
    employee_id: str
    product_id: str
    rate_on_profit: Decimal = Field(ge=0, le=1)
    notes: Optional[str] = Field(default=None, max_length=500)


class RetailCommissionRateUpdateBody(BaseModel):
    rate_on_profit: Decimal = Field(ge=0, le=1)
    notes: Optional[str] = Field(default=None, max_length=500)


# =============================================================================
# store_sales 创建（管理端入口，通常走小程序 workspace）
# =============================================================================


def _sale_to_dict(s: StoreSale) -> dict:
    return {
        "id": s.id,
        "sale_no": s.sale_no,
        "store_id": s.store_id,
        "cashier_employee_id": s.cashier_employee_id,
        "customer_id": s.customer_id,
        "total_sale_amount": str(s.total_sale_amount),
        "total_cost": str(s.total_cost),
        "total_profit": str(s.total_profit),
        "total_commission": str(s.total_commission),
        "total_bottles": s.total_bottles,
        "payment_method": s.payment_method,
        "status": s.status,
        "notes": s.notes,
        "created_at": s.created_at,
    }


@router.post("")
async def create_sale(
    body: StoreSaleCreateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理端创建（不常用；小程序端走 mall workspace）。"""
    require_role(user, "boss", "warehouse")
    sale = await store_sale_service.create_store_sale(
        db,
        cashier_employee_id=body.cashier_employee_id,
        store_id=body.store_id,
        customer_id=body.customer_id,
        line_items=[{"barcode": li.barcode, "sale_price": li.sale_price}
                    for li in body.line_items],
        payment_method=body.payment_method,
        notes=body.notes,
    )
    await log_audit(
        db, action="store_sale.create",
        entity_type="StoreSale", entity_id=sale.id,
        user=user, request=request,
        changes={
            "sale_no": sale.sale_no,
            "store_id": body.store_id,
            "cashier": body.cashier_employee_id,
            "bottles": sale.total_bottles,
            "amount": str(sale.total_sale_amount),
            "profit": str(sale.total_profit),
            "commission": str(sale.total_commission),
            "payment_method": body.payment_method,
        },
    )
    return _sale_to_dict(sale)


# =============================================================================
# 列表 / 详情 / 统计
# =============================================================================


async def _enrich_sale_list(db: AsyncSession, records: list[dict]) -> list[dict]:
    store_ids = list({r["store_id"] for r in records})
    emp_ids = list({r["cashier_employee_id"] for r in records})
    cust_ids = list({r["customer_id"] for r in records})

    store_map = {}
    if store_ids:
        for w in (await db.execute(
            select(Warehouse).where(Warehouse.id.in_(store_ids))
        )).scalars():
            store_map[w.id] = w.name
    emp_map = {}
    if emp_ids:
        for e in (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars():
            emp_map[e.id] = e.name
    cust_map = {}
    if cust_ids:
        for c in (await db.execute(
            select(MallUser).where(MallUser.id.in_(cust_ids))
        )).scalars():
            cust_map[c.id] = c.real_name or c.nickname or c.username or c.id[:8]

    for r in records:
        r["store_name"] = store_map.get(r["store_id"])
        r["cashier_name"] = emp_map.get(r["cashier_employee_id"])
        r["customer_name"] = cust_map.get(r["customer_id"])
    return records


@router.get("")
async def list_sales(
    user: CurrentUser,
    store_id: Optional[str] = None,
    cashier_employee_id: Optional[str] = None,
    start_date: Optional[str] = None,  # YYYY-MM-DD
    end_date: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "warehouse", "hr")
    stmt = select(StoreSale)
    if store_id:
        stmt = stmt.where(StoreSale.store_id == store_id)
    if cashier_employee_id:
        stmt = stmt.where(StoreSale.cashier_employee_id == cashier_employee_id)
    if start_date:
        stmt = stmt.where(StoreSale.created_at >= f"{start_date} 00:00:00+00")
    if end_date:
        stmt = stmt.where(StoreSale.created_at < f"{end_date} 23:59:59+00")
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(StoreSale.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    records = [_sale_to_dict(r) for r in rows]
    records = await _enrich_sale_list(db, records)
    return {"records": records, "total": total}


@router.get("/stats")
async def stats(
    user: CurrentUser,
    store_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """按店/时间窗口聚合总销售额/成本/利润/提成/瓶数。"""
    require_role(user, "boss", "finance", "warehouse", "hr")
    stmt = select(
        func.coalesce(func.sum(StoreSale.total_sale_amount), 0),
        func.coalesce(func.sum(StoreSale.total_cost), 0),
        func.coalesce(func.sum(StoreSale.total_profit), 0),
        func.coalesce(func.sum(StoreSale.total_commission), 0),
        func.coalesce(func.sum(StoreSale.total_bottles), 0),
        func.count(StoreSale.id),
    )
    if store_id:
        stmt = stmt.where(StoreSale.store_id == store_id)
    if start_date:
        stmt = stmt.where(StoreSale.created_at >= f"{start_date} 00:00:00+00")
    if end_date:
        stmt = stmt.where(StoreSale.created_at < f"{end_date} 23:59:59+00")
    row = (await db.execute(stmt)).one()
    return {
        "total_sale_amount": str(row[0]),
        "total_cost": str(row[1]),
        "total_profit": str(row[2]),
        "total_commission": str(row[3]),
        "total_bottles": int(row[4] or 0),
        "sale_count": int(row[5] or 0),
    }


@router.get("/{sale_id}")
async def get_sale(
    sale_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "warehouse", "hr")
    s = await db.get(StoreSale, sale_id)
    if s is None:
        raise HTTPException(status_code=404, detail="销售单不存在")
    items = (await db.execute(
        select(StoreSaleItem).where(StoreSaleItem.sale_id == sale_id)
    )).scalars().all()
    d = _sale_to_dict(s)
    d["items"] = [
        {
            "id": it.id,
            "barcode": it.barcode,
            "product_id": it.product_id,
            "batch_no_snapshot": it.batch_no_snapshot,
            "sale_price": str(it.sale_price),
            "cost_price_snapshot": str(it.cost_price_snapshot),
            "profit": str(it.profit),
            "rate_on_profit_snapshot": str(it.rate_on_profit_snapshot) if it.rate_on_profit_snapshot else None,
            "commission_amount": str(it.commission_amount),
        }
        for it in items
    ]
    (await _enrich_sale_list(db, [d]))
    return d


# =============================================================================
# retail_commission_rates：独立 router 挂 /api/retail-commission-rates
# =============================================================================


rate_router = APIRouter()


def _rate_to_dict(r: RetailCommissionRate) -> dict:
    return {
        "id": r.id,
        "employee_id": r.employee_id,
        "product_id": r.product_id,
        "rate_on_profit": str(r.rate_on_profit),
        "notes": r.notes,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@rate_router.get("")
async def list_rates(
    user: CurrentUser,
    employee_id: Optional[str] = None,
    product_id: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "hr")
    stmt = select(RetailCommissionRate)
    if employee_id:
        stmt = stmt.where(RetailCommissionRate.employee_id == employee_id)
    if product_id:
        stmt = stmt.where(RetailCommissionRate.product_id == product_id)
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.offset(skip).limit(limit)
    )).scalars().all()
    return {
        "records": [_rate_to_dict(r) for r in rows],
        "total": total,
    }


@rate_router.post("")
async def create_rate(
    body: RetailCommissionRateCreateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "hr")
    # 校验员工/商品存在
    emp = await db.get(Employee, body.employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    prod = await db.get(Product, body.product_id)
    if prod is None:
        raise HTTPException(status_code=404, detail="商品不存在")

    import uuid
    obj = RetailCommissionRate(
        id=str(uuid.uuid4()),
        employee_id=body.employee_id,
        product_id=body.product_id,
        rate_on_profit=body.rate_on_profit,
        notes=body.notes,
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(
            status_code=409,
            detail=f"员工 {emp.name} 已配置商品 {prod.name} 的提成率，请改用 PUT",
        ) from e
    await log_audit(
        db, action="retail_commission_rate.create",
        entity_type="RetailCommissionRate", entity_id=obj.id,
        user=user, request=request,
        changes={
            "employee_id": body.employee_id,
            "employee_name": emp.name,
            "product_id": body.product_id,
            "product_name": prod.name,
            "rate_on_profit": str(body.rate_on_profit),
        },
    )
    return _rate_to_dict(obj)


@rate_router.put("/{rate_id}")
async def update_rate(
    rate_id: str,
    body: RetailCommissionRateUpdateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "hr")
    obj = await db.get(RetailCommissionRate, rate_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="提成率不存在")
    old_rate = obj.rate_on_profit
    obj.rate_on_profit = body.rate_on_profit
    obj.notes = body.notes
    obj.updated_at = datetime.now()
    await db.flush()
    await log_audit(
        db, action="retail_commission_rate.update",
        entity_type="RetailCommissionRate", entity_id=obj.id,
        user=user, request=request,
        changes={"old": str(old_rate), "new": str(body.rate_on_profit)},
    )
    return _rate_to_dict(obj)


@rate_router.delete("/{rate_id}", status_code=204)
async def delete_rate(
    rate_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "hr")
    obj = await db.get(RetailCommissionRate, rate_id)
    if obj is None:
        return
    await log_audit(
        db, action="retail_commission_rate.delete",
        entity_type="RetailCommissionRate", entity_id=obj.id,
        user=user, request=request,
        changes={
            "employee_id": obj.employee_id,
            "product_id": obj.product_id,
            "rate_on_profit": str(obj.rate_on_profit),
        },
    )
    await db.delete(obj)
    await db.flush()
