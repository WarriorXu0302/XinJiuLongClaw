"""
Inventory API routes — batch query, stock-out, stock-flow list, barcode binding.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.base import InventoryBarcodeStatus, InventoryBarcodeType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.product import Product, Warehouse
from app.schemas.inventory import (
    InventoryBarcodeResponse,
    InventoryResponse,
    StockFlowResponse,
)
from app.services.inventory_service import process_stock_out

router = APIRouter()


# ── Warehouse list (for dropdowns) ──────────────────────────────────


@router.get("/warehouses")
async def list_warehouses(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Warehouse).where(Warehouse.is_active == True)
    if brand_id:
        stmt = stmt.where(Warehouse.brand_id == brand_id)
    rows = (await db.execute(stmt.order_by(Warehouse.code))).scalars().all()
    return [{"id": w.id, "name": w.name, "code": w.code, "warehouse_type": w.warehouse_type, "brand_id": w.brand_id, "brand_name": w.brand.name if w.brand else None} for w in rows]


# ── Batch query (PRD §6.1: GET /api/inventory/batches) ──────────────


@router.get("/batches")
async def list_batches(
    user: CurrentUser,
    product_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    base = select(Inventory).where(Inventory.quantity > 0)
    if brand_id:
        base = base.join(Product, Inventory.product_id == Product.id).where(Product.brand_id == brand_id)
    if product_id:
        base = base.where(Inventory.product_id == product_id)
    if warehouse_id:
        base = base.where(Inventory.warehouse_id == warehouse_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.order_by(Inventory.stock_in_date.asc(), Inventory.created_at.asc())
        .offset(skip).limit(limit)
    )).scalars().all()
    return {
        "items": [
            {
                "product_id": r.product_id,
                "warehouse_id": r.warehouse_id,
                "batch_no": r.batch_no,
                "quantity": r.quantity,
                "cost_price": float(r.cost_price),
                "stock_in_date": str(r.stock_in_date) if r.stock_in_date else None,
                "product_name": r.product.name if r.product else None,
                "warehouse_name": r.warehouse.name if r.warehouse else None,
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
    }


# ── Stock-out (PRD §3.4.3) ──────────────────────────────────────────


class StockOutRequest(BaseModel):
    order_item_id: str
    product_id: str
    required_quantity: int
    warehouse_id: str
    barcode: Optional[str] = None


class StockOutAllocationItem(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    batch_no: str
    allocated_quantity: int
    allocated_cost_price: float
    cost_allocation_mode: str


@router.post("/stock-out", response_model=list[StockOutAllocationItem], status_code=201)
async def stock_out(body: StockOutRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    try:
        allocations = await process_stock_out(
            db,
            order_item_id=body.order_item_id,
            product_id=body.product_id,
            required_quantity=body.required_quantity,
            warehouse_id=body.warehouse_id,
            barcode=body.barcode,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return allocations


# ── Direct inbound (backup warehouse — manual stock-in with price) ──


class DirectInboundRequest(BaseModel):
    product_id: str
    warehouse_id: str
    quantity: int
    quantity_unit: str = "瓶"  # 箱 或 瓶
    cost_price: float  # 每瓶成本价（始终按瓶计）
    cost_price_unit: str = "bottle"  # "bottle" 或 "case"
    supplier_id: Optional[str] = None
    batch_no: Optional[str] = None
    notes: Optional[str] = None


@router.post("/direct-inbound", status_code=201)
async def direct_inbound(body: DirectInboundRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Direct stock-in to backup/main warehouse with cost price. Inventory is stored in bottles."""
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz
    from decimal import Decimal as _D
    from app.models.product import Product

    wh = await db.get(Warehouse, body.warehouse_id)
    if wh is None:
        raise HTTPException(404, "仓库不存在")
    if wh.warehouse_type not in ('backup', 'main'):
        raise HTTPException(400, f"直接入库仅限主仓和备用仓，当前仓库类型: {wh.warehouse_type}")

    # 单位换算：统一转成瓶
    bpc = 1
    if body.quantity_unit == '箱' or body.cost_price_unit == 'case':
        prod = await db.get(Product, body.product_id)
        bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
    bottles = body.quantity * (bpc if body.quantity_unit == '箱' else 1)
    # cost_price 单位：bottle=每瓶价（直接用），case=箱价（需除以 bpc）
    per_bottle_cost = _D(str(body.cost_price)) / bpc if body.cost_price_unit == 'case' and bpc > 1 else _D(str(body.cost_price))

    now = _dt.now(_tz.utc)
    batch = body.batch_no or f"BK-{now.strftime('%Y%m%d%H%M%S')}-{_uuid.uuid4().hex[:4]}"

    # Create or update inventory record
    inv = (await db.execute(
        select(Inventory).where(
            Inventory.product_id == body.product_id,
            Inventory.warehouse_id == body.warehouse_id,
            Inventory.batch_no == batch,
        )
    )).scalar_one_or_none()
    if inv:
        inv.quantity += bottles
    else:
        db.add(Inventory(
            product_id=body.product_id, warehouse_id=body.warehouse_id,
            batch_no=batch, quantity=bottles, cost_price=per_bottle_cost,
            stock_in_date=now,
        ))

    # Create stock flow (stored in bottles)
    flow = StockFlow(
        id=str(_uuid.uuid4()),
        flow_no=f"SF-{now.strftime('%Y%m%d%H%M%S')}-{_uuid.uuid4().hex[:6]}",
        flow_type="inbound",
        product_id=body.product_id,
        warehouse_id=body.warehouse_id,
        batch_no=batch,
        cost_price=per_bottle_cost,
        quantity=bottles,
        notes=(body.notes or "直接入库") + f" ({body.quantity}{body.quantity_unit}={bottles}瓶)",
    )
    db.add(flow)
    await db.flush()
    from app.services.audit_service import log_audit
    await log_audit(db, action="direct_inbound", entity_type="StockFlow", entity_id=flow.id,
                    changes={"warehouse": wh.name, "product_id": body.product_id, "bottles": bottles, "per_bottle_cost": float(per_bottle_cost)}, user=user)
    return {"detail": f"入库成功 {body.quantity}{body.quantity_unit}（共{bottles}瓶），批次 {batch}", "flow_id": flow.id, "batch_no": batch}


# ── Direct outbound (tasting/backup warehouse, no policy required) ──


class DirectOutboundRequest(BaseModel):
    product_id: str
    warehouse_id: str
    quantity: int
    quantity_unit: str = "瓶"
    notes: Optional[str] = None
    barcode: Optional[str] = None


@router.post("/direct-outbound", status_code=201)
async def direct_outbound(body: DirectOutboundRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Direct stock-out from tasting or backup warehouse. Inventory stored in bottles."""
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz
    from app.models.product import Product

    wh = await db.get(Warehouse, body.warehouse_id)
    if wh is None:
        raise HTTPException(404, "仓库不存在")
    if wh.warehouse_type not in ('tasting', 'backup', 'retail', 'wholesale'):
        raise HTTPException(400, f"直接出库仅限品鉴酒仓、备用仓、零售仓和批发仓，当前仓库类型: {wh.warehouse_type}")

    # 单位换算：统一转成瓶
    bpc = 1
    if body.quantity_unit == '箱':
        prod = await db.get(Product, body.product_id)
        bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
    bottles = body.quantity * bpc

    # Find inventory (FIFO)
    inv_rows = (await db.execute(
        select(Inventory)
        .where(Inventory.product_id == body.product_id, Inventory.warehouse_id == body.warehouse_id, Inventory.quantity > 0)
        .order_by(Inventory.stock_in_date.asc())
    )).scalars().all()

    remaining = bottles
    for inv in inv_rows:
        if remaining <= 0:
            break
        deduct = min(remaining, inv.quantity)
        inv.quantity -= deduct
        remaining -= deduct

    if remaining > 0:
        raise HTTPException(400, f"库存不足，缺少 {remaining} 瓶")

    # Create stock flow
    flow = StockFlow(
        id=str(_uuid.uuid4()),
        flow_no=f"SF-{_dt.now(_tz.utc).strftime('%Y%m%d%H%M%S')}-{_uuid.uuid4().hex[:6]}",
        flow_type="outbound",
        product_id=body.product_id,
        warehouse_id=body.warehouse_id,
        batch_no=inv_rows[0].batch_no if inv_rows else "direct",
        quantity=bottles,
        notes=(body.notes or f"直接出库（{wh.warehouse_type}）") + f" ({body.quantity}{body.quantity_unit}={bottles}瓶)",
    )
    db.add(flow)
    await db.flush()
    from app.services.audit_service import log_audit
    await log_audit(db, action="direct_outbound", entity_type="StockFlow", entity_id=flow.id,
                    changes={"warehouse": wh.name, "product_id": body.product_id, "bottles": bottles}, user=user)
    return {"detail": f"出库成功 {body.quantity}{body.quantity_unit}（共{bottles}瓶）", "flow_id": flow.id}


# ── Stock-flow list (GET /api/inventory/stock-flow) ─────────────────


@router.get("/stock-flow")
async def list_stock_flow(
    product_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    brand_id: Optional[str] = Query(None),
    flow_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    base = select(StockFlow)
    if brand_id:
        base = base.join(Warehouse, StockFlow.warehouse_id == Warehouse.id).where(Warehouse.brand_id == brand_id)
    if product_id:
        base = base.where(StockFlow.product_id == product_id)
    if warehouse_id:
        base = base.where(StockFlow.warehouse_id == warehouse_id)
    if flow_type:
        base = base.where(StockFlow.flow_type == flow_type)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(StockFlow.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


# ── Barcode binding (PRD §6.1: POST /api/inventory/stock-ins/{id}/bind-barcodes)


class BarcodeBind(BaseModel):
    barcode: str
    barcode_type: str = "case"
    parent_barcode: Optional[str] = None


class BindBarcodesRequest(BaseModel):
    barcodes: list[BarcodeBind]


@router.post(
    "/stock-ins/{flow_id}/bind-barcodes",
    response_model=list[InventoryBarcodeResponse],
    status_code=201,
)
async def bind_barcodes(
    flow_id: str,
    body: BindBarcodesRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bind barcodes to a stock-in flow record's batch."""
    flow = await db.get(StockFlow, flow_id)
    if flow is None:
        raise HTTPException(404, "StockFlow not found")
    if flow.flow_type != "in":
        raise HTTPException(400, "Can only bind barcodes to inbound stock flow")

    results = []
    for bc in body.barcodes:
        obj = InventoryBarcode(
            id=str(uuid.uuid4()),
            barcode=bc.barcode,
            barcode_type=bc.barcode_type,
            product_id=flow.product_id,
            warehouse_id=flow.warehouse_id,
            batch_no=flow.batch_no,
            stock_in_id=flow.id,
            parent_barcode=bc.parent_barcode,
            status=InventoryBarcodeStatus.IN_STOCK,
        )
        db.add(obj)
        results.append(obj)
    await db.flush()
    return results


# ── Inventory value summary ────────────────────────────────────────


@router.get("/value-summary")
async def inventory_value_summary(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Inventory value by brand -> warehouse -> product."""
    from sqlalchemy import func

    stmt = (
        select(
            Product.brand_id,
            Warehouse.name.label("warehouse_name"),
            Warehouse.id.label("warehouse_id"),
            Warehouse.warehouse_type.label("warehouse_type"),
            Product.name.label("product_name"),
            Product.id.label("product_id"),
            Product.bottles_per_case,
            Inventory.batch_no,
            Inventory.quantity,
            Inventory.cost_price,
            (Inventory.quantity * Inventory.cost_price).label("total_value"),
        )
        .join(Product, Inventory.product_id == Product.id)
        .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
        .where(Inventory.quantity > 0)
    )
    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)
    stmt = stmt.order_by(Product.brand_id, Warehouse.name, Product.name)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "brand_id": r.brand_id,
            "warehouse_name": r.warehouse_name,
            "warehouse_id": r.warehouse_id,
            "warehouse_type": r.warehouse_type,
            "product_name": r.product_name,
            "product_id": r.product_id,
            "bottles_per_case": r.bottles_per_case or 1,
            "batch_no": r.batch_no,
            "quantity": r.quantity,
            "cost_price": float(r.cost_price) if r.cost_price else 0,
            "total_value": float(r.total_value) if r.total_value else 0,
        }
        for r in rows
    ]


# ── Barcode tracing (PRD §3.4.4) ────────────────────────────────────


class BarcodeTraceResult(BaseModel):
    barcode: str
    found: bool = False
    barcode_type: Optional[str] = None
    product_name: Optional[str] = None
    batch_no: Optional[str] = None
    warehouse_name: Optional[str] = None
    status: Optional[str] = None
    # Tracing chain
    stock_in_flow_no: Optional[str] = None
    stock_in_date: Optional[str] = None
    stock_out_flow_no: Optional[str] = None
    order_no: Optional[str] = None
    customer_name: Optional[str] = None
    salesman_name: Optional[str] = None
    # Policy info
    policy_status: Optional[str] = None
    scheme_no: Optional[str] = None


@router.get("/barcode-trace/{barcode}", response_model=BarcodeTraceResult)
async def trace_barcode(barcode: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Trace a barcode through the full supply chain for inspection."""
    from app.models.order import Order
    from app.models.policy import PolicyRequest

    bc = (
        await db.execute(
            select(InventoryBarcode).where(InventoryBarcode.barcode == barcode)
        )
    ).scalar_one_or_none()

    if bc is None:
        return BarcodeTraceResult(barcode=barcode, found=False)

    result = BarcodeTraceResult(
        barcode=bc.barcode,
        found=True,
        barcode_type=bc.barcode_type,
        product_name=bc.product.name if bc.product else None,
        batch_no=bc.batch_no,
        warehouse_name=bc.warehouse.name if bc.warehouse else None,
        status=bc.status,
    )

    # Stock-in
    if bc.stock_in_id:
        in_flow = await db.get(StockFlow, bc.stock_in_id)
        if in_flow:
            result.stock_in_flow_no = in_flow.flow_no
            result.stock_in_date = str(in_flow.created_at)[:19] if in_flow.created_at else None

    # Stock-out → order → customer → salesman → policy
    if bc.outbound_stock_flow_id:
        out_flow = await db.get(StockFlow, bc.outbound_stock_flow_id)
        if out_flow:
            result.stock_out_flow_no = out_flow.flow_no
            if out_flow.source_order_id:
                order = await db.get(Order, out_flow.source_order_id)
                if order:
                    result.order_no = order.order_no
                    if order.customer:
                        result.customer_name = order.customer.name
                    if order.salesman:
                        result.salesman_name = order.salesman.name
                    # Find policy
                    pr = (
                        await db.execute(
                            select(PolicyRequest).where(PolicyRequest.order_id == order.id).limit(1)
                        )
                    ).scalar_one_or_none()
                    if pr:
                        result.policy_status = pr.status
                        result.scheme_no = pr.scheme_no

    return result


# ── Batch barcode import (for Excel data) ───────────────────────────


class BatchBarcodeImport(BaseModel):
    product_id: str
    warehouse_id: str
    batch_no: str
    barcodes: list[str]


class BatchImportResult(BaseModel):
    total: int
    imported: int
    duplicates: int
    duplicate_codes: list[str]


@router.post("/barcodes/batch-import", response_model=BatchImportResult, status_code=201)
async def batch_import_barcodes(
    body: BatchBarcodeImport, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Import barcodes in batch (from Excel/scanner). Auto-dedup."""
    imported = 0
    duplicates = 0
    dup_codes: list[str] = []

    for code in body.barcodes:
        code = code.strip()
        if not code:
            continue
        existing = (
            await db.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode == code)
            )
        ).scalar_one_or_none()
        if existing:
            duplicates += 1
            dup_codes.append(code)
            continue
        obj = InventoryBarcode(
            id=str(uuid.uuid4()),
            barcode=code,
            barcode_type=InventoryBarcodeType.CASE,
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            batch_no=body.batch_no,
            status=InventoryBarcodeStatus.IN_STOCK,
        )
        db.add(obj)
        imported += 1

    await db.flush()
    return BatchImportResult(
        total=len(body.barcodes),
        imported=imported,
        duplicates=duplicates,
        duplicate_codes=dup_codes[:20],
    )


# ═══════════════════════════════════════════════════════════════════
# 低库存查询 + 通知推送
# ═══════════════════════════════════════════════════════════════════

@router.get("/low-stock")
async def list_low_stock(
    user: CurrentUser,
    brand_id: Optional[str] = Query(None),
    threshold_cases: int = Query(5, description="按箱计算的预警阈值"),
    db: AsyncSession = Depends(get_db),
):
    """列出所有库存 ≤ 阈值 箱 的 SKU（按瓶×bpc 换算）"""
    stmt = (
        select(
            Inventory.product_id, Inventory.warehouse_id, Inventory.batch_no,
            Inventory.quantity, Inventory.cost_price,
            Product.name.label("product_name"), Product.bottles_per_case,
            Warehouse.name.label("warehouse_name"), Warehouse.warehouse_type,
            Warehouse.brand_id.label("warehouse_brand_id"),
        )
        .select_from(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .where(Inventory.quantity > 0)
    )
    if brand_id:
        stmt = stmt.where(Warehouse.brand_id == brand_id)

    rows = (await db.execute(stmt)).all()
    result = []
    for r in rows:
        bpc = r.bottles_per_case or 1
        cases = r.quantity / bpc
        if cases <= threshold_cases:
            result.append({
                "product_id": r.product_id,
                "product_name": r.product_name,
                "warehouse_id": r.warehouse_id,
                "warehouse_name": r.warehouse_name,
                "warehouse_type": r.warehouse_type,
                "batch_no": r.batch_no,
                "bottles": r.quantity,
                "cases": round(cases, 2),
                "threshold_cases": threshold_cases,
            })
    result.sort(key=lambda x: x["cases"])
    return result


@router.post("/low-stock/notify")
async def notify_low_stock(
    user: CurrentUser,
    threshold_cases: int = Query(5),
    db: AsyncSession = Depends(get_db),
):
    """扫描低库存 → 推送给所有 warehouse/admin/boss 角色用户"""
    from app.services.notification_service import notify_roles

    low = await list_low_stock(user=user, brand_id=None, threshold_cases=threshold_cases, db=db)
    if not low:
        return {"detail": "无低库存", "count": 0}

    # 分仓汇总
    by_wh = {}
    for x in low:
        by_wh.setdefault(x["warehouse_name"], []).append(x)
    lines = []
    for wh, items in by_wh.items():
        lines.append(f"【{wh}】{len(items)} 个 SKU 低于 {threshold_cases} 箱")
        for it in items[:5]:
            lines.append(f"  - {it['product_name']} 批次{it['batch_no']}: 仅剩 {it['cases']:.1f} 箱")
    content = "\n".join(lines)

    await notify_roles(
        db, role_codes=["warehouse", "admin", "boss"],
        title=f"低库存预警：{len(low)} 个 SKU",
        content=content[:500],
        entity_type="Inventory",
    )
    await db.flush()
    return {"detail": f"已通知，涉及 {len(low)} 个 SKU", "count": len(low)}
