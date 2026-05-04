"""
Product API routes — CRUD.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.product import Brand, Product
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter()


@router.get("/brands")
async def list_brands(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Brand).order_by(Brand.code))).scalars().all()
    return [{"id": b.id, "code": b.code, "name": b.name, "manufacturer_id": b.manufacturer_id, "status": b.status} for b in rows]


from pydantic import BaseModel as _BM

class BrandCreate(_BM):
    code: str
    name: str
    manufacturer_id: str | None = None
    status: str = "active"

class BrandUpdate(_BM):
    code: str | None = None
    name: str | None = None
    manufacturer_id: str | None = None
    status: str | None = None


@router.post("/brands", status_code=201)
async def create_brand(body: BrandCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    from app.models.product import Account, Warehouse

    obj = Brand(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()

    # Auto-create project accounts (cash + f_class + financing)
    code = obj.code.upper()
    for acc_type, acc_name in [('cash', '现金'), ('f_class', 'F类'), ('financing', '融资')]:
        db.add(Account(
            id=str(uuid.uuid4()),
            code=f'{code}-{acc_type.upper().replace("_", "")}',
            name=f'{obj.name}-{acc_name}',
            account_type=acc_type,
            level='project',
            brand_id=obj.id,
        ))

    # Auto-create warehouses (main + backup + tasting)
    for wh_type, wh_name in [('main', '主仓'), ('backup', '备用仓'), ('tasting', '品鉴酒仓')]:
        db.add(Warehouse(
            id=str(uuid.uuid4()),
            code=f'{code}-WH-{wh_type.upper()}',
            name=f'{obj.name}-{wh_name}',
            warehouse_type=wh_type,
            brand_id=obj.id,
        ))

    await db.flush()
    return {"id": obj.id, "code": obj.code, "name": obj.name, "status": obj.status}


@router.put("/brands/{brand_id}")
async def update_brand(brand_id: str, body: BrandUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    obj = await db.get(Brand, brand_id)
    if obj is None:
        raise HTTPException(404, "Brand not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return {"id": obj.id, "code": obj.code, "name": obj.name, "status": obj.status}


@router.delete("/brands/{brand_id}", status_code=204)
async def delete_brand(brand_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    obj = await db.get(Brand, brand_id)
    if obj is None:
        raise HTTPException(404, "Brand not found")
    await db.delete(obj)
    await db.flush()


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(body: ProductCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss", "warehouse")
    obj = Product(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("")
async def list_products(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=1000),  # 管理端下拉页面需要全量（如提成率配置）
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(Product)
    if brand_id:
        base = base.where(Product.brand_id == brand_id)
    if status:
        base = base.where(Product.status == status)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Product.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Product, product_id)
    if obj is None:
        raise HTTPException(404, "Product not found")
    return obj


@router.get("/{product_id}/mall-cascade-impact")
async def get_mall_cascade_impact(
    product_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """下架 ERP 商品前预览 mall 侧挂靠商品数，让前端弹确认框。"""
    from app.models.mall.product import MallProduct
    obj = await db.get(Product, product_id)
    if obj is None:
        raise HTTPException(404, "Product not found")
    rows = (await db.execute(
        select(MallProduct)
        .where(MallProduct.source_product_id == product_id)
    )).scalars().all()
    on_sale = [m for m in rows if m.status == "on_sale"]
    return {
        "product_id": product_id,
        "mall_total": len(rows),
        "mall_on_sale": len(on_sale),
        "mall_on_sale_items": [
            {"id": m.id, "name": m.name} for m in on_sale
        ],
    }


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    cascade_mall: bool = Query(False, description="下架时是否同步把 mall_products 也置为 off_sale"),
):
    from app.core.permissions import require_role
    require_role(user, "boss", "warehouse")
    obj = await db.get(Product, product_id)
    if obj is None:
        raise HTTPException(404, "Product not found")
    prev_status = obj.status
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()

    # ERP active → inactive 时，如果 cascade_mall=True 把挂靠的 MallProduct 一起下架
    if cascade_mall and prev_status == "active" and obj.status != "active":
        from app.models.mall.product import MallProduct
        affected = (await db.execute(
            select(MallProduct)
            .where(MallProduct.source_product_id == product_id)
            .where(MallProduct.status == "on_sale")
        )).scalars().all()
        for m in affected:
            m.status = "off_sale"
        await db.flush()
    return obj


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_role
    require_role(user, "boss")
    obj = await db.get(Product, product_id)
    if obj is None:
        raise HTTPException(404, "Product not found")
    await db.delete(obj)
    await db.flush()
