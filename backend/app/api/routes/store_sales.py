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
    # 决策 #3 散客支持：customer_id 可选
    customer_id: Optional[str] = None
    customer_walk_in_name: Optional[str] = Field(default=None, max_length=100)
    customer_walk_in_phone: Optional[str] = Field(default=None, max_length=20)
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
        "customer_walk_in_name": s.customer_walk_in_name,
        "customer_walk_in_phone": s.customer_walk_in_phone,
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
    # service 层已 log_audit（actor_id=cashier_employee_id）；
    # 管理端入口额外记一条"管理端代下"审计区分调用路径
    sale = await store_sale_service.create_store_sale(
        db,
        cashier_employee_id=body.cashier_employee_id,
        store_id=body.store_id,
        customer_id=body.customer_id,
        customer_walk_in_name=body.customer_walk_in_name,
        customer_walk_in_phone=body.customer_walk_in_phone,
        line_items=[{"barcode": li.barcode, "sale_price": li.sale_price}
                    for li in body.line_items],
        payment_method=body.payment_method,
        notes=body.notes,
    )
    await log_audit(
        db, action="store_sale.create_by_admin",
        entity_type="StoreSale", entity_id=sale.id,
        user=user, request=request,
        changes={
            "sale_no": sale.sale_no,
            "cashier_employee_id": body.cashier_employee_id,
            "note": "管理端代下（非店员小程序提交）",
        },
    )
    return _sale_to_dict(sale)


# =============================================================================
# 列表 / 详情 / 统计
# =============================================================================


async def _enrich_sale_list(db: AsyncSession, records: list[dict]) -> list[dict]:
    store_ids = list({r["store_id"] for r in records})
    emp_ids = list({r["cashier_employee_id"] for r in records})
    # 散客 customer_id 为 None，过滤掉再查
    cust_ids = list({r["customer_id"] for r in records if r.get("customer_id")})

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
        if r.get("customer_id"):
            r["customer_name"] = cust_map.get(r["customer_id"])
        else:
            # 散客：优先显示 walk_in 快照，都没有则展示"散客"
            r["customer_name"] = (
                r.get("customer_walk_in_name")
                or (f"散客 {r['customer_walk_in_phone'][-4:]}"
                    if r.get("customer_walk_in_phone") else "散客")
            )
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
    group_by: Optional[str] = None,  # G3：传 "store" 返每店一行
    db: AsyncSession = Depends(get_db),
):
    """按店/时间窗口聚合总销售额/成本/利润/提成/瓶数。

    group_by="store" 时返 {by_store: [...], total: {...}}，每店一行 + 合计。
    """
    require_role(user, "boss", "finance", "warehouse", "hr")

    base_filters = []
    if store_id:
        base_filters.append(StoreSale.store_id == store_id)
    if start_date:
        base_filters.append(StoreSale.created_at >= f"{start_date} 00:00:00+00")
    if end_date:
        base_filters.append(StoreSale.created_at < f"{end_date} 23:59:59+00")

    if group_by == "store":
        group_stmt = select(
            StoreSale.store_id,
            func.coalesce(func.sum(StoreSale.total_sale_amount), 0),
            func.coalesce(func.sum(StoreSale.total_cost), 0),
            func.coalesce(func.sum(StoreSale.total_profit), 0),
            func.coalesce(func.sum(StoreSale.total_commission), 0),
            func.coalesce(func.sum(StoreSale.total_bottles), 0),
            func.count(StoreSale.id),
        ).group_by(StoreSale.store_id)
        for f in base_filters:
            group_stmt = group_stmt.where(f)
        rows = (await db.execute(group_stmt)).all()
        store_ids = [r[0] for r in rows]
        stores = {
            w.id: w.name for w in (await db.execute(
                select(Warehouse).where(Warehouse.id.in_(store_ids))
            )).scalars()
        } if store_ids else {}
        by_store = []
        total = {
            "total_sale_amount": Decimal("0"),
            "total_cost": Decimal("0"),
            "total_profit": Decimal("0"),
            "total_commission": Decimal("0"),
            "total_bottles": 0,
            "sale_count": 0,
        }
        for r in rows:
            sid, rev, cost, profit, com, bottles, count = r
            margin = None
            if rev and Decimal(str(rev)) > 0:
                margin = f"{(Decimal(str(profit)) / Decimal(str(rev)) * 100):.1f}"
            by_store.append({
                "store_id": sid,
                "store_name": stores.get(sid, sid[:8]),
                "total_sale_amount": str(rev),
                "total_cost": str(cost),
                "total_profit": str(profit),
                "total_commission": str(com),
                "total_bottles": int(bottles or 0),
                "sale_count": int(count or 0),
                "gross_margin_pct": margin,
            })
            total["total_sale_amount"] += Decimal(str(rev))
            total["total_cost"] += Decimal(str(cost))
            total["total_profit"] += Decimal(str(profit))
            total["total_commission"] += Decimal(str(com))
            total["total_bottles"] += int(bottles or 0)
            total["sale_count"] += int(count or 0)
        by_store.sort(key=lambda x: Decimal(x["total_sale_amount"]), reverse=True)
        total_margin = None
        if total["total_sale_amount"] > 0:
            total_margin = f"{(total['total_profit'] / total['total_sale_amount'] * 100):.1f}"
        return {
            "by_store": by_store,
            "total": {
                **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in total.items()},
                "gross_margin_pct": total_margin,
            },
        }

    # 默认：单行总聚合（向后兼容）
    stmt = select(
        func.coalesce(func.sum(StoreSale.total_sale_amount), 0),
        func.coalesce(func.sum(StoreSale.total_cost), 0),
        func.coalesce(func.sum(StoreSale.total_profit), 0),
        func.coalesce(func.sum(StoreSale.total_commission), 0),
        func.coalesce(func.sum(StoreSale.total_bottles), 0),
        func.count(StoreSale.id),
    )
    for f in base_filters:
        stmt = stmt.where(f)
    row = (await db.execute(stmt)).one()
    return {
        "total_sale_amount": str(row[0]),
        "total_cost": str(row[1]),
        "total_profit": str(row[2]),
        "total_commission": str(row[3]),
        "total_bottles": int(row[4] or 0),
        "sale_count": int(row[5] or 0),
    }


@router.get("/export")
async def export_sales(
    user: CurrentUser,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    store_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """G3：导出门店销售流水 CSV（boss/finance）。

    返回 text/csv 附带 Content-Disposition。
    字段：日期 / 单号 / 门店 / 店员 / 客户 / 瓶数 / 销售额 / 成本 / 利润 / 提成 / 付款方式 / 状态
    """
    require_role(user, "boss", "finance")
    stmt = select(StoreSale).order_by(desc(StoreSale.created_at))
    if store_id:
        stmt = stmt.where(StoreSale.store_id == store_id)
    if start_date:
        stmt = stmt.where(StoreSale.created_at >= f"{start_date} 00:00:00+00")
    if end_date:
        stmt = stmt.where(StoreSale.created_at < f"{end_date} 23:59:59+00")

    rows = (await db.execute(stmt)).scalars().all()

    # 注入 store / cashier / customer 名字
    store_ids = list({r.store_id for r in rows})
    emp_ids = list({r.cashier_employee_id for r in rows})
    cust_ids = list({r.customer_id for r in rows if r.customer_id})
    stores = {w.id: w.name for w in (await db.execute(
        select(Warehouse).where(Warehouse.id.in_(store_ids))
    )).scalars()} if store_ids else {}
    emps = {e.id: e.name for e in (await db.execute(
        select(Employee).where(Employee.id.in_(emp_ids))
    )).scalars()} if emp_ids else {}
    custs = {
        c.id: (c.real_name or c.nickname or c.username or c.id[:8])
        for c in (await db.execute(
            select(MallUser).where(MallUser.id.in_(cust_ids))
        )).scalars()
    } if cust_ids else {}

    # 组装 CSV
    import csv
    import io
    from fastapi.responses import StreamingResponse

    buf = io.StringIO()
    # UTF-8 BOM 让 Excel 识别中文
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow([
        "日期", "单号", "门店", "店员", "客户", "瓶数",
        "销售额", "成本", "利润", "提成", "毛利率%",
        "付款方式", "状态",
    ])

    def _fmt_customer(r: StoreSale) -> str:
        if r.customer_id:
            return custs.get(r.customer_id, r.customer_id[:8])
        if r.customer_walk_in_name:
            return f"散客·{r.customer_walk_in_name}"
        if r.customer_walk_in_phone:
            return f"散客·{r.customer_walk_in_phone[-4:]}"
        return "散客"

    for r in rows:
        margin = ""
        if r.total_sale_amount and Decimal(str(r.total_sale_amount)) > 0:
            m = Decimal(str(r.total_profit)) / Decimal(str(r.total_sale_amount)) * 100
            margin = f"{m:.1f}"
        writer.writerow([
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            r.sale_no,
            stores.get(r.store_id, r.store_id[:8]),
            emps.get(r.cashier_employee_id, r.cashier_employee_id[:8]),
            _fmt_customer(r),
            r.total_bottles,
            str(r.total_sale_amount),
            str(r.total_cost),
            str(r.total_profit),
            str(r.total_commission),
            margin,
            r.payment_method,
            r.status,
        ])

    buf.seek(0)
    period = f"{start_date or 'all'}_{end_date or 'all'}"
    filename = f"store_sales_{period}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
