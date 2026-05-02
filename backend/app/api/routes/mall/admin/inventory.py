"""
/api/mall/admin/inventory/*

GET  /                        库存查询（按仓库 / SKU 过滤）
GET  /flows                   库存流水
POST /inbound                 入库（生成条码）
POST /barcodes/import         批量导入预印条码
GET  /barcodes                条码查询（按 SKU / 仓库 / 状态）
POST /barcodes/{barcode}/damage  单瓶损耗
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryBarcode,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.services.audit_service import log_audit
from app.services.mall import inventory_service

router = APIRouter()


# =============================================================================
# 库存查询
# =============================================================================

@router.get("")
async def list_inventory(
    user: CurrentUser,
    warehouse_id: Optional[str] = None,
    sku_id: Optional[int] = None,
    low_stock: Optional[bool] = Query(default=None, description="只看低于阈值"),
    threshold: int = Query(default=10, ge=0),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "warehouse")
    stmt = select(MallInventory)
    if warehouse_id:
        stmt = stmt.where(MallInventory.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(MallInventory.sku_id == sku_id)
    if low_stock:
        stmt = stmt.where(MallInventory.quantity <= threshold)
    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(MallInventory.quantity.asc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    sku_ids = [r.sku_id for r in rows]
    wh_ids = list({r.warehouse_id for r in rows})
    skus = (await db.execute(
        select(MallProductSku).where(MallProductSku.id.in_(sku_ids))
    )).scalars().all()
    sku_map = {s.id: s for s in skus}
    prod_ids = [s.product_id for s in skus]
    prods = (await db.execute(
        select(MallProduct).where(MallProduct.id.in_(prod_ids))
    )).scalars().all()
    prod_map = {p.id: p for p in prods}
    whs = (await db.execute(
        select(MallWarehouse).where(MallWarehouse.id.in_(wh_ids))
    )).scalars().all()
    wh_map = {w.id: w for w in whs}

    records = []
    for r in rows:
        sku = sku_map.get(r.sku_id)
        prod = prod_map.get(sku.product_id) if sku else None
        wh = wh_map.get(r.warehouse_id)
        records.append({
            "id": r.id,
            "warehouse_id": r.warehouse_id,
            "warehouse_name": wh.name if wh else None,
            "sku_id": r.sku_id,
            "product_id": sku.product_id if sku else None,
            "product_name": prod.name if prod else None,
            "sku_name": sku.spec if sku else None,
            "quantity": r.quantity,
            "avg_cost_price": str(r.avg_cost_price) if r.avg_cost_price else None,
            "updated_at": r.updated_at,
        })
    return {"records": records, "total": total}


# =============================================================================
# 库存流水
# =============================================================================

@router.get("/flows")
async def list_flows(
    user: CurrentUser,
    warehouse_id: Optional[str] = None,
    sku_id: Optional[int] = None,
    flow_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "warehouse")
    stmt = select(MallInventoryFlow, MallInventory).join(
        MallInventory, MallInventoryFlow.inventory_id == MallInventory.id
    )
    if warehouse_id:
        stmt = stmt.where(MallInventory.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(MallInventory.sku_id == sku_id)
    if flow_type:
        stmt = stmt.where(MallInventoryFlow.flow_type == flow_type)

    total = int((await db.execute(
        select(sa_func.count(MallInventoryFlow.id)).select_from(
            MallInventoryFlow.__table__.join(
                MallInventory.__table__,
                MallInventoryFlow.inventory_id == MallInventory.id,
            )
        ).where(*_flow_filters(warehouse_id, sku_id, flow_type))
    )).scalar() or 0)

    stmt = stmt.order_by(desc(MallInventoryFlow.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).all()

    return {
        "records": [
            {
                "id": f.id,
                "warehouse_id": inv.warehouse_id,
                "sku_id": inv.sku_id,
                "flow_type": f.flow_type,
                "quantity": f.quantity,
                "cost_price": str(f.cost_price) if f.cost_price else None,
                "ref_type": f.ref_type,
                "ref_id": f.ref_id,
                "notes": f.notes,
                "created_at": f.created_at,
            }
            for f, inv in rows
        ],
        "total": total,
    }


def _flow_filters(warehouse_id, sku_id, flow_type):
    from sqlalchemy import true
    conds = [true()]
    if warehouse_id:
        conds.append(MallInventory.warehouse_id == warehouse_id)
    if sku_id:
        conds.append(MallInventory.sku_id == sku_id)
    if flow_type:
        conds.append(MallInventoryFlow.flow_type == flow_type)
    return conds


# =============================================================================
# 入库（生成条码）
# =============================================================================

class _InboundBody(BaseModel):
    warehouse_id: str
    sku_id: int
    quantity: int = Field(..., gt=0, le=10000)
    unit_cost: Decimal = Field(..., ge=0)
    batch_no: str = Field(..., min_length=1, max_length=100, description="生产批次号")
    barcode_prefix: Optional[str] = Field(
        default=None,
        description="条码前缀，空则自动 MBC-{sku:03d}-{8位uuid}",
    )
    ref_id: Optional[str] = Field(default=None, description="关联采购单号（可选）")


@router.post("/inbound", status_code=201)
async def inbound(
    body: _InboundBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """入库 + 按数量自动生成单瓶条码。"""
    require_role(user, "admin", "boss", "warehouse", "purchase")
    inv, codes = await inventory_service.inbound_with_barcodes(
        db,
        warehouse_id=body.warehouse_id,
        sku_id=body.sku_id,
        quantity=body.quantity,
        unit_cost=body.unit_cost,
        batch_no=body.batch_no,
        barcode_prefix=body.barcode_prefix,
        ref_type="admin_inbound",
        ref_id=body.ref_id,
    )
    await log_audit(
        db, action="mall_inbound", entity_type="MallInventory",
        entity_id=inv.id,
        changes={
            "warehouse_id": body.warehouse_id,
            "sku_id": body.sku_id,
            "quantity": body.quantity,
            "unit_cost": str(body.unit_cost),
            "batch_no": body.batch_no,
            "barcode_count": len(codes),
            "first_barcode": codes[0].barcode if codes else None,
            "last_barcode": codes[-1].barcode if codes else None,
        },
        user=user, request=request,
    )
    return {
        "inventory_id": inv.id,
        "new_quantity": inv.quantity,
        "avg_cost_price": str(inv.avg_cost_price) if inv.avg_cost_price else None,
        "barcode_count": len(codes),
        "barcodes": [b.barcode for b in codes],  # 前端可打印
    }


# =============================================================================
# 批量导入预印条码（厂家贴码场景）
# =============================================================================

class _ImportBarcodesBody(BaseModel):
    warehouse_id: str
    sku_id: int
    batch_no: str = Field(..., min_length=1, max_length=100)
    unit_cost: Decimal = Field(..., ge=0)
    barcodes: list[str] = Field(..., min_length=1, max_length=5000)


@router.post("/barcodes/import", status_code=201)
async def import_barcodes(
    body: _ImportBarcodesBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """上传已印好的条码清单入库（厂家贴码 / 批量粘贴场景）。
    条码全局唯一；任一已存在则整笔拒绝。
    """
    require_role(user, "admin", "boss", "warehouse", "purchase")
    inv, codes = await inventory_service.inbound_with_barcodes(
        db,
        warehouse_id=body.warehouse_id,
        sku_id=body.sku_id,
        quantity=len(body.barcodes),
        unit_cost=body.unit_cost,
        batch_no=body.batch_no,
        custom_barcodes=body.barcodes,
        ref_type="admin_inbound_import",
    )
    await log_audit(
        db, action="mall_inbound_import", entity_type="MallInventory",
        entity_id=inv.id,
        changes={
            "warehouse_id": body.warehouse_id,
            "sku_id": body.sku_id,
            "quantity": len(body.barcodes),
            "batch_no": body.batch_no,
            "first_barcode": body.barcodes[0],
        },
        user=user, request=request,
    )
    return {
        "inventory_id": inv.id,
        "new_quantity": inv.quantity,
        "imported_count": len(codes),
    }


# =============================================================================
# 条码查询
# =============================================================================

@router.get("/barcodes")
async def list_barcodes(
    user: CurrentUser,
    sku_id: Optional[int] = None,
    warehouse_id: Optional[str] = None,
    status: Optional[str] = None,
    batch_no: Optional[str] = None,
    barcode: Optional[str] = Query(default=None, description="精确查找单个条码"),
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "warehouse")
    stmt = select(MallInventoryBarcode)
    if barcode:
        stmt = stmt.where(MallInventoryBarcode.barcode == barcode)
    if sku_id:
        stmt = stmt.where(MallInventoryBarcode.sku_id == sku_id)
    if warehouse_id:
        stmt = stmt.where(MallInventoryBarcode.warehouse_id == warehouse_id)
    if status:
        stmt = stmt.where(MallInventoryBarcode.status == status)
    if batch_no:
        stmt = stmt.where(MallInventoryBarcode.batch_no == batch_no)

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallInventoryBarcode.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "records": [
            {
                "id": b.id,
                "barcode": b.barcode,
                "barcode_type": b.barcode_type,
                "sku_id": b.sku_id,
                "product_id": b.product_id,
                "warehouse_id": b.warehouse_id,
                "batch_no": b.batch_no,
                "status": b.status,
                "outbound_order_id": b.outbound_order_id,
                "outbound_at": b.outbound_at,
                "cost_price": str(b.cost_price) if b.cost_price else None,
                "created_at": b.created_at,
            }
            for b in rows
        ],
        "total": total,
    }


# =============================================================================
# 单瓶损耗
# =============================================================================

class _DamageBody(BaseModel):
    reason: Optional[str] = None


@router.post("/barcodes/{barcode}/damage")
async def damage_barcode(
    barcode: str,
    body: _DamageBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """标记单瓶损耗 / 盘亏。条码 → damaged；库存 -1；不改 avg_cost。"""
    require_role(user, "admin", "boss", "warehouse")
    b = await inventory_service.adjust_barcode_damaged(db, barcode=barcode, reason=body.reason)
    await log_audit(
        db, action="mall_barcode_damaged", entity_type="MallInventoryBarcode",
        entity_id=b.id, changes={"reason": body.reason}, user=user, request=request,
    )
    return {"barcode": b.barcode, "status": b.status}
