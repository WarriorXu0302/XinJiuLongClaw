"""
Tasting wine usage API routes — CRUD + inventory linkage (PRD §3.2.3).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.inventory import Inventory, StockFlow
from app.models.product import Product
from app.models.tasting import TastingWineUsage
from app.schemas.tasting import (
    TastingWineUsageCreate,
    TastingWineUsageResponse,
    TastingWineUsageUpdate,
)
from app.services.audit_service import log_audit

router = APIRouter()


def _generate_flow_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"SF-{ts}-{short}"


# ═══════════════════════════════════════════════════════════════════
# CREATE — with auto stock-flow generation
# ═══════════════════════════════════════════════════════════════════


@router.post("/tasting-wine-usage", response_model=TastingWineUsageResponse, status_code=201)
async def create_tasting_wine_usage(
    body: TastingWineUsageCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    record = TastingWineUsage(
        id=str(uuid.uuid4()),
        **body.model_dump(),
    )
    db.add(record)
    await db.flush()

    # ── Auto-generate StockFlow based on usage_type ──────────────────
    if body.product_id and body.quantity and body.quantity > 0:
        if body.usage_type in ("entertainment", "customer_use", "resale"):
            # Simple outbound: deduct from inventory, create one outbound flow
            await _create_outbound_flow(db, record, user)

        elif body.usage_type == "transfer_backup":
            # Transfer: outbound from source warehouse + inbound to target warehouse
            if not body.target_warehouse_id:
                raise HTTPException(
                    400,
                    "target_warehouse_id is required for transfer_backup usage_type",
                )
            await _create_transfer_flows(db, record, user)

    await db.flush()
    await log_audit(
        db,
        action="create_tasting_wine_usage",
        entity_type="TastingWineUsage",
        entity_id=record.id, user=user)
    return record


async def _create_outbound_flow(
    db: AsyncSession,
    record: TastingWineUsage,
    user: dict,
) -> None:
    """Create a single outbound StockFlow and deduct Inventory."""
    # Find inventory batch to deduct from
    stmt = select(Inventory).where(
        Inventory.product_id == record.product_id,
        Inventory.quantity > 0,
    )
    if record.batch_no:
        stmt = stmt.where(Inventory.batch_no == record.batch_no)
    stmt = stmt.order_by(Inventory.stock_in_date.asc(), Inventory.created_at.asc())
    inv_rows = (await db.execute(stmt)).scalars().all()

    total_available = sum(r.quantity for r in inv_rows)
    if total_available < record.quantity:
        raise HTTPException(
            400,
            f"Insufficient inventory for product {record.product_id}: "
            f"need {record.quantity}, available {total_available}",
        )

    remaining = record.quantity
    last_flow_id: str | None = None

    for inv in inv_rows:
        if remaining <= 0:
            break
        take = min(inv.quantity, remaining)
        inv.quantity -= take
        remaining -= take

        flow = StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_generate_flow_no(),
            product_id=record.product_id,
            warehouse_id=inv.warehouse_id,
            batch_no=inv.batch_no,
            flow_type="outbound",
            quantity=-take,
            cost_price=inv.cost_price,
            reference_no=f"tasting:{record.id}",
            operator_id=user.get("sub"),
            notes=f"Tasting wine usage - {record.usage_type}",
        )
        db.add(flow)
        last_flow_id = flow.id

    # Link the last flow id back to the record
    if last_flow_id:
        record.stock_flow_id = last_flow_id


async def _create_transfer_flows(
    db: AsyncSession,
    record: TastingWineUsage,
    user: dict,
) -> None:
    """Create outbound + inbound StockFlow pair for warehouse transfer."""
    # Find inventory batch to deduct from
    stmt = select(Inventory).where(
        Inventory.product_id == record.product_id,
        Inventory.quantity > 0,
    )
    if record.batch_no:
        stmt = stmt.where(Inventory.batch_no == record.batch_no)
    stmt = stmt.order_by(Inventory.stock_in_date.asc(), Inventory.created_at.asc())
    inv_rows = (await db.execute(stmt)).scalars().all()

    total_available = sum(r.quantity for r in inv_rows)
    if total_available < record.quantity:
        raise HTTPException(
            400,
            f"Insufficient inventory for product {record.product_id}: "
            f"need {record.quantity}, available {total_available}",
        )

    remaining = record.quantity
    last_outbound_flow_id: str | None = None

    for inv in inv_rows:
        if remaining <= 0:
            break
        take = min(inv.quantity, remaining)
        inv.quantity -= take
        remaining -= take

        # Outbound from source warehouse
        outbound_flow = StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_generate_flow_no(),
            product_id=record.product_id,
            warehouse_id=inv.warehouse_id,
            batch_no=inv.batch_no,
            flow_type="outbound",
            quantity=-take,
            cost_price=inv.cost_price,
            reference_no=f"tasting_transfer:{record.id}",
            operator_id=user.get("sub"),
            notes=f"Tasting wine transfer out - {record.usage_type}",
        )
        db.add(outbound_flow)
        last_outbound_flow_id = outbound_flow.id

        # Inbound to target warehouse
        inbound_flow = StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_generate_flow_no(),
            product_id=record.product_id,
            warehouse_id=record.target_warehouse_id,
            batch_no=inv.batch_no,
            flow_type="inbound",
            quantity=take,
            cost_price=inv.cost_price,
            reference_no=f"tasting_transfer:{record.id}",
            operator_id=user.get("sub"),
            notes=f"Tasting wine transfer in - {record.usage_type}",
        )
        db.add(inbound_flow)

        # Add to target warehouse inventory
        target_inv = (
            await db.execute(
                select(Inventory).where(
                    Inventory.product_id == record.product_id,
                    Inventory.warehouse_id == record.target_warehouse_id,
                    Inventory.batch_no == inv.batch_no,
                )
            )
        ).scalar_one_or_none()

        if target_inv:
            target_inv.quantity += take
        else:
            new_inv = Inventory(
                product_id=record.product_id,
                warehouse_id=record.target_warehouse_id,
                batch_no=inv.batch_no,
                quantity=take,
                cost_price=inv.cost_price,
            )
            db.add(new_inv)

    # Link the outbound flow id back to the record
    if last_outbound_flow_id:
        record.stock_flow_id = last_outbound_flow_id


# ═══════════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════════


@router.get("/tasting-wine-usage")
async def list_tasting_wine_usage(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(TastingWineUsage)
    if brand_id:
        base = base.join(Product, TastingWineUsage.product_id == Product.id).where(Product.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(TastingWineUsage.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


# ═══════════════════════════════════════════════════════════════════
# GET SINGLE
# ═══════════════════════════════════════════════════════════════════


@router.get("/tasting-wine-usage/{record_id}", response_model=TastingWineUsageResponse)
async def get_tasting_wine_usage(
    record_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(TastingWineUsage, record_id)
    if record is None:
        raise HTTPException(404, "TastingWineUsage not found")
    return record


# ═══════════════════════════════════════════════════════════════════
# UPDATE
# ═══════════════════════════════════════════════════════════════════


@router.put("/tasting-wine-usage/{record_id}", response_model=TastingWineUsageResponse)
async def update_tasting_wine_usage(
    record_id: str,
    body: TastingWineUsageUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(TastingWineUsage, record_id)
    if record is None:
        raise HTTPException(404, "TastingWineUsage not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(record, k, v)
    await db.flush()
    return record


# ═══════════════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════════════


@router.delete("/tasting-wine-usage/{record_id}", status_code=204)
async def delete_tasting_wine_usage(
    record_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse")
    record = await db.get(TastingWineUsage, record_id)
    if record is None:
        raise HTTPException(404, "TastingWineUsage not found")
    await db.delete(record)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Bottle Destruction CRUD + Reconciliation
# ═══════════════════════════════════════════════════════════════════


from pydantic import BaseModel as PydanticBase
from app.models.tasting import BottleDestruction
from datetime import date


class BottleDestructionCreate(PydanticBase):
    brand_id: str
    product_id: str | None = None
    destroyed_count: int
    destruction_date: date
    period: str
    manufacturer_witness: str | None = None
    witness_by: str | None = None
    notes: str | None = None


class BottleDestructionResponse(PydanticBase):
    model_config = {"from_attributes": True}
    id: str
    record_no: str
    brand_id: str
    product_id: str | None = None
    destroyed_count: int
    destruction_date: date
    period: str
    manufacturer_witness: str | None = None
    notes: str | None = None
    created_at: datetime


class BottleReconciliation(PydanticBase):
    brand_id: str
    brand_name: str | None = None
    period: str
    tasting_outbound_count: int
    destroyed_count: int
    difference: int
    is_matched: bool


def _gen_bd_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"BD-{ts}-{short}"


@router.post("/bottle-destructions", response_model=BottleDestructionResponse, status_code=201)
async def create_bottle_destruction(
    body: BottleDestructionCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = BottleDestruction(
        id=str(uuid.uuid4()),
        record_no=_gen_bd_no(),
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()
    from app.services.audit_service import log_audit
    await log_audit(db, action="create_bottle_destruction", entity_type="BottleDestruction", entity_id=obj.id, user=user)
    return obj


@router.get("/bottle-destructions")
async def list_bottle_destructions(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    period: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    base = select(BottleDestruction)
    if brand_id:
        base = base.where(BottleDestruction.brand_id == brand_id)
    if period:
        base = base.where(BottleDestruction.period == period)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(BottleDestruction.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/bottle-reconciliation", response_model=list[BottleReconciliation])
async def bottle_reconciliation(
    user: CurrentUser,
    period: str = Query(..., description="对账周期，如 2025-01"),
    brand_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Compare tasting wine outbound vs bottle destruction for a period.

    tasting_outbound_count: sum of tasting_wine_usage.quantity where usage creates outbound stock flow
    destroyed_count: sum of bottle_destructions.destroyed_count
    If they don't match → is_matched = False (alert)
    """
    from sqlalchemy import func
    from app.models.product import Brand

    brands_stmt = select(Brand)
    if brand_id:
        brands_stmt = brands_stmt.where(Brand.id == brand_id)
    brands = (await db.execute(brands_stmt)).scalars().all()

    from app.models.product import Warehouse

    results = []
    for brand in brands:
        # 品鉴酒出库：统计该品牌 tasting 类型仓库下所有 outbound StockFlow 的 quantity 总和
        # （包括政策兑付、手工出库、TastingWineUsage 等所有来源）
        tasting_count = (await db.execute(
            select(func.coalesce(func.sum(StockFlow.quantity), 0))
            .join(Warehouse, StockFlow.warehouse_id == Warehouse.id)
            .where(
                Warehouse.brand_id == brand.id,
                Warehouse.warehouse_type == 'tasting',
                StockFlow.flow_type == 'outbound',
                func.to_char(StockFlow.created_at, 'YYYY-MM') == period,
            )
        )).scalar_one()

        # Destroyed: sum from bottle_destructions
        destroyed = (await db.execute(
            select(func.coalesce(func.sum(BottleDestruction.destroyed_count), 0))
            .where(
                BottleDestruction.brand_id == brand.id,
                BottleDestruction.period == period,
            )
        )).scalar_one()

        diff = int(tasting_count) - int(destroyed)
        results.append(BottleReconciliation(
            brand_id=brand.id,
            brand_name=brand.name,
            period=period,
            tasting_outbound_count=int(tasting_count),
            destroyed_count=int(destroyed),
            difference=diff,
            is_matched=(diff == 0),
        ))

    return results
