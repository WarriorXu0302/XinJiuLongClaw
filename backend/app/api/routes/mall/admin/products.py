"""
/api/mall/admin/products/*
/api/mall/admin/skus/*

商品 + SKU 完整 CRUD。

设计要点：
  - 商品有 3 种来源：
      1. 纯商城自建（source_product_id=null，cost_price 必填）
      2. ERP 商品导入（source_product_id 指向 ERP products.id，name/brand/cost 溯源）
      3. 混合：导入后可再加纯商城 SKU
  - 商品列表展示 min_price/max_price 区间（从所有 active SKU 聚合）
  - 改价必写审计
  - 软删：status=off_sale（商品）/ inactive（SKU）不物理删；已卖过的商品不允许物理删
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.product import MallCategory, MallProduct, MallProductSku
from app.models.product import Brand, Product as ErpProduct
from app.services.audit_service import log_audit

router = APIRouter()
sku_router = APIRouter()


# =============================================================================
# 商品列表
# =============================================================================

@router.get("")
async def list_products(
    user: CurrentUser,
    keyword: Optional[str] = Query(default=None, description="商品名 / brief 模糊"),
    category_id: Optional[int] = None,
    brand_id: Optional[str] = None,
    status: Optional[str] = Query(default=None, description="draft / on_sale / off_sale"),
    source: Optional[str] = Query(default=None, description="pure (纯商城) / erp (ERP 导入)"),
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase", "warehouse")
    stmt = select(MallProduct)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where((MallProduct.name.ilike(kw)) | (MallProduct.brief.ilike(kw)))
    if category_id:
        stmt = stmt.where(MallProduct.category_id == category_id)
    if brand_id:
        stmt = stmt.where(MallProduct.brand_id == brand_id)
    if status:
        stmt = stmt.where(MallProduct.status == status)
    if source == "pure":
        stmt = stmt.where(MallProduct.source_product_id.is_(None))
    elif source == "erp":
        stmt = stmt.where(MallProduct.source_product_id.isnot(None))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallProduct.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    # 批量关联 category + brand + sku_count
    cat_ids = [r.category_id for r in rows if r.category_id]
    brand_ids = [r.brand_id for r in rows if r.brand_id]
    prod_ids = [r.id for r in rows]

    cats = (await db.execute(
        select(MallCategory).where(MallCategory.id.in_(cat_ids))
    )).scalars().all() if cat_ids else []
    cat_map = {c.id: c for c in cats}

    brands = (await db.execute(
        select(Brand).where(Brand.id.in_(brand_ids))
    )).scalars().all() if brand_ids else []
    brand_map = {b.id: b for b in brands}

    sku_counts = dict((await db.execute(
        select(MallProductSku.product_id, sa_func.count(MallProductSku.id))
        .where(MallProductSku.product_id.in_(prod_ids))
        .group_by(MallProductSku.product_id)
    )).all())

    records = []
    for r in rows:
        cat = cat_map.get(r.category_id) if r.category_id else None
        brand = brand_map.get(r.brand_id) if r.brand_id else None
        records.append({
            "id": r.id,
            "name": r.name,
            "brief": r.brief,
            "main_image": r.main_image,
            "status": r.status,
            "category_id": r.category_id,
            "category_name": cat.name if cat else None,
            "brand_id": r.brand_id,
            "brand_name": brand.name if brand else None,
            "source_product_id": r.source_product_id,
            "is_pure": r.source_product_id is None,
            "min_price": str(r.min_price) if r.min_price else None,
            "max_price": str(r.max_price) if r.max_price else None,
            "total_sales": r.total_sales,
            "sku_count": sku_counts.get(r.id, 0),
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        })
    return {"records": records, "total": total}


# =============================================================================
# 商品详情
# =============================================================================

@router.get("/{product_id}")
async def get_product(
    product_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase", "warehouse")
    p = await db.get(MallProduct, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="商品不存在")

    cat = await db.get(MallCategory, p.category_id) if p.category_id else None
    brand = await db.get(Brand, p.brand_id) if p.brand_id else None

    skus = (await db.execute(
        select(MallProductSku)
        .where(MallProductSku.product_id == p.id)
        .order_by(MallProductSku.id)
    )).scalars().all()

    return {
        "id": p.id,
        "name": p.name,
        "brief": p.brief,
        "main_image": p.main_image,
        "images": p.images or [],
        "detail_html": p.detail_html,
        "status": p.status,
        "category_id": p.category_id,
        "category_name": cat.name if cat else None,
        "brand_id": p.brand_id,
        "brand_name": brand.name if brand else None,
        "source_product_id": p.source_product_id,
        "is_pure": p.source_product_id is None,
        "min_price": str(p.min_price) if p.min_price else None,
        "max_price": str(p.max_price) if p.max_price else None,
        "total_sales": p.total_sales,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "skus": [
            {
                "id": s.id,
                "spec": s.spec,
                "price": str(s.price),
                "cost_price": str(s.cost_price) if s.cost_price else None,
                "image": s.image,
                "barcode": s.barcode,
                "status": s.status,
            } for s in skus
        ],
    }


# =============================================================================
# 创建 / 从 ERP 导入
# =============================================================================

class _ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    brief: Optional[str] = Field(default=None, max_length=500)
    category_id: Optional[int] = None
    brand_id: Optional[str] = None
    main_image: Optional[str] = None
    images: Optional[list[str]] = None
    detail_html: Optional[str] = None
    source_product_id: Optional[str] = Field(
        default=None,
        description="非空则为 ERP 导入；为空则纯商城",
    )
    status: str = Field(default="draft", pattern="^(draft|on_sale|off_sale)$")


@router.post("", status_code=201)
async def create_product(
    body: _ProductCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")

    if body.category_id:
        c = await db.get(MallCategory, body.category_id)
        if c is None or c.status != "active":
            raise HTTPException(status_code=400, detail="分类不存在或已禁用")
    if body.brand_id:
        b = await db.get(Brand, body.brand_id)
        if b is None:
            raise HTTPException(status_code=400, detail="品牌不存在")

    # ERP 导入：溯源 name/brand，但允许覆盖
    if body.source_product_id:
        erp = await db.get(ErpProduct, body.source_product_id)
        if erp is None:
            raise HTTPException(status_code=400, detail="ERP 商品不存在")
        # 重复导入检查
        dup = (await db.execute(
            select(MallProduct).where(MallProduct.source_product_id == body.source_product_id)
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"该 ERP 商品已导入为 mall_product id={dup.id}",
            )

    p = MallProduct(
        source_product_id=body.source_product_id,
        brand_id=body.brand_id,
        category_id=body.category_id,
        name=body.name,
        brief=body.brief,
        main_image=body.main_image,
        images=body.images,
        detail_html=body.detail_html,
        status=body.status,
        total_sales=0,
    )
    db.add(p)
    await db.flush()
    await log_audit(
        db, action="mall_product.create", entity_type="MallProduct",
        entity_id=str(p.id), user=user, request=request,
        changes={
            "name": p.name, "status": p.status,
            "category_id": p.category_id, "brand_id": p.brand_id,
            "source": "erp" if p.source_product_id else "pure",
        },
    )
    return {"id": p.id, "name": p.name, "status": p.status}


# =============================================================================
# 更新
# =============================================================================

class _ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    brief: Optional[str] = Field(default=None, max_length=500)
    category_id: Optional[int] = None
    brand_id: Optional[str] = None
    main_image: Optional[str] = None
    images: Optional[list[str]] = None
    detail_html: Optional[str] = None


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    body: _ProductUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")
    p = await db.get(MallProduct, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="商品不存在")

    updates = body.model_dump(exclude_unset=True)
    if updates.get("category_id"):
        c = await db.get(MallCategory, updates["category_id"])
        if c is None or c.status != "active":
            raise HTTPException(status_code=400, detail="分类不存在或已禁用")
    if updates.get("brand_id"):
        b = await db.get(Brand, updates["brand_id"])
        if b is None:
            raise HTTPException(status_code=400, detail="品牌不存在")

    for k, v in updates.items():
        setattr(p, k, v)
    p.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_product.update", entity_type="MallProduct",
        entity_id=str(p.id), user=user, request=request, changes=updates,
    )
    return {"id": p.id}


# =============================================================================
# 上架 / 下架
# =============================================================================

class _StatusBody(BaseModel):
    status: str = Field(..., pattern="^(draft|on_sale|off_sale)$")


@router.post("/{product_id}/status")
async def change_status(
    product_id: int,
    body: _StatusBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")
    p = await db.get(MallProduct, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="商品不存在")

    # 上架前强制至少 1 个 active SKU
    if body.status == "on_sale":
        active_skus = int((await db.execute(
            select(sa_func.count()).select_from(MallProductSku)
            .where(MallProductSku.product_id == product_id)
            .where(MallProductSku.status == "active")
        )).scalar() or 0)
        if active_skus == 0:
            raise HTTPException(
                status_code=400,
                detail="上架前必须至少有 1 个 active SKU",
            )

    prev_status = p.status
    p.status = body.status
    p.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action=f"mall_product.{body.status}", entity_type="MallProduct",
        entity_id=str(p.id), user=user, request=request,
        changes={"name": p.name, "from": prev_status, "to": body.status},
    )
    return {"id": p.id, "status": p.status}


# =============================================================================
# 删除（物理删，仅无销售历史 + draft 状态允许）
# =============================================================================

@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """物理删除。只允许 status=draft 且 total_sales=0 的商品；否则走下架。"""
    require_role(user, "admin", "boss")
    p = await db.get(MallProduct, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    if p.status == "on_sale":
        raise HTTPException(
            status_code=400,
            detail="商品在售中，请先下架后再删",
        )
    if (p.total_sales or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail=f"商品已有 {p.total_sales} 笔销售历史，请改为下架（不能物理删除）",
        )

    await log_audit(
        db, action="mall_product.delete", entity_type="MallProduct",
        entity_id=str(p.id), user=user, request=request,
        changes={"name": p.name, "status": p.status},
    )
    await db.delete(p)
    await db.flush()


# =============================================================================
# ERP 商品下拉（导入时用）
# =============================================================================

@router.get("/_helpers/erp-products")
async def list_erp_products(
    user: CurrentUser,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """列出可导入的 ERP 商品（未被任何 mall_product 导入过）。"""
    require_role(user, "admin", "boss", "purchase")
    imported = [
        pid for pid, in (await db.execute(
            select(MallProduct.source_product_id)
            .where(MallProduct.source_product_id.isnot(None))
        )).all()
    ]

    stmt = select(ErpProduct)
    if imported:
        stmt = stmt.where(ErpProduct.id.notin_(imported))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(ErpProduct.name.ilike(kw))
    stmt = stmt.order_by(ErpProduct.name).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "name": r.name,
                "brand_id": r.brand_id,
                "guide_price": str(r.guide_price) if getattr(r, "guide_price", None) else None,
            } for r in rows
        ]
    }


@router.get("/_helpers/brands")
async def list_brands_helper(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")
    rows = (await db.execute(select(Brand).order_by(Brand.name))).scalars().all()
    return {"records": [{"id": b.id, "name": b.name} for b in rows]}


# =============================================================================
# SKU CRUD（挂在 /api/mall/admin/skus 前缀）
# =============================================================================

class _SkuCreate(BaseModel):
    product_id: int
    spec: Optional[str] = Field(default=None, max_length=200)
    price: Decimal = Field(..., ge=0)
    cost_price: Optional[Decimal] = Field(default=None, ge=0)
    image: Optional[str] = None
    barcode: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|inactive)$")


@sku_router.post("", status_code=201)
async def create_sku(
    body: _SkuCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")
    p = await db.get(MallProduct, body.product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    # 纯商城 SKU 必填 cost_price（利润口径依赖）
    if p.source_product_id is None and body.cost_price is None:
        raise HTTPException(
            status_code=400,
            detail="纯商城 SKU 必须填成本价（利润台账依赖）",
        )
    # barcode 唯一
    if body.barcode:
        dup = (await db.execute(
            select(MallProductSku).where(MallProductSku.barcode == body.barcode)
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"条码 {body.barcode} 已存在")

    s = MallProductSku(
        product_id=body.product_id,
        spec=body.spec,
        price=body.price,
        cost_price=body.cost_price,
        image=body.image,
        barcode=body.barcode,
        status=body.status,
    )
    db.add(s)
    await db.flush()
    # 同步 min_price / max_price
    await _refresh_product_price_range(db, body.product_id)
    await log_audit(
        db, action="mall_sku.create", entity_type="MallProductSku",
        entity_id=str(s.id), user=user, request=request,
        changes={"product_id": s.product_id, "spec": s.spec, "price": str(s.price)},
    )
    return {"id": s.id}


class _SkuUpdate(BaseModel):
    spec: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, ge=0)
    cost_price: Optional[Decimal] = Field(default=None, ge=0)
    image: Optional[str] = None
    barcode: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive)$")


@sku_router.put("/{sku_id}")
async def update_sku(
    sku_id: int,
    body: _SkuUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase")
    s = await db.get(MallProductSku, sku_id)
    if s is None:
        raise HTTPException(status_code=404, detail="SKU 不存在")

    updates = body.model_dump(exclude_unset=True)
    # price 改动必审计
    old_price = s.price
    if "barcode" in updates and updates["barcode"]:
        dup = (await db.execute(
            select(MallProductSku)
            .where(MallProductSku.barcode == updates["barcode"])
            .where(MallProductSku.id != sku_id)
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"条码 {updates['barcode']} 已被占用")

    for k, v in updates.items():
        setattr(s, k, v)
    s.updated_at = datetime.now(timezone.utc)
    await db.flush()

    if "price" in updates or "status" in updates:
        await _refresh_product_price_range(db, s.product_id)

    # 改价单独一条审计（敏感操作）
    if "price" in updates and old_price != updates["price"]:
        # 统一用 Decimal 再 str，避免 "199.00" vs "299" 格式不一致
        await log_audit(
            db, action="mall_sku.price_change", entity_type="MallProductSku",
            entity_id=str(s.id), user=user, request=request,
            changes={
                "product_id": s.product_id, "spec": s.spec,
                "from": f"{Decimal(str(old_price)):.2f}",
                "to": f"{Decimal(str(updates['price'])):.2f}",
            },
        )
    else:
        await log_audit(
            db, action="mall_sku.update", entity_type="MallProductSku",
            entity_id=str(s.id), user=user, request=request,
            changes=updates,
        )
    return {"id": s.id}


@sku_router.delete("/{sku_id}", status_code=204)
async def delete_sku(
    sku_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """物理删 SKU。有库存或已卖过时拒绝。"""
    require_role(user, "admin", "boss")
    s = await db.get(MallProductSku, sku_id)
    if s is None:
        raise HTTPException(status_code=404, detail="SKU 不存在")

    from app.models.mall.inventory import MallInventory
    from app.models.mall.order import MallOrderItem

    # 有库存拒绝
    inv_qty = int((await db.execute(
        select(sa_func.coalesce(sa_func.sum(MallInventory.quantity), 0))
        .where(MallInventory.sku_id == sku_id)
    )).scalar() or 0)
    if inv_qty > 0:
        raise HTTPException(
            status_code=400,
            detail=f"SKU 仍有 {inv_qty} 瓶库存，请先清库存",
        )

    # 有销售历史拒绝
    sold_count = int((await db.execute(
        select(sa_func.count()).select_from(MallOrderItem)
        .where(MallOrderItem.sku_id == sku_id)
    )).scalar() or 0)
    if sold_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"SKU 已有 {sold_count} 笔销售记录，不能删除（建议改为 inactive 下架）",
        )

    prod_id = s.product_id
    await log_audit(
        db, action="mall_sku.delete", entity_type="MallProductSku",
        entity_id=str(s.id), user=user, request=request,
        changes={"product_id": s.product_id, "spec": s.spec, "price": str(s.price)},
    )
    await db.delete(s)
    await db.flush()
    await _refresh_product_price_range(db, prod_id)


# =============================================================================
# 辅助：刷新商品的 min_price / max_price
# =============================================================================

async def _refresh_product_price_range(db: AsyncSession, product_id: int) -> None:
    res = (await db.execute(
        select(sa_func.min(MallProductSku.price), sa_func.max(MallProductSku.price))
        .where(MallProductSku.product_id == product_id)
        .where(MallProductSku.status == "active")
    )).one_or_none()
    p = await db.get(MallProduct, product_id)
    if p is None:
        return
    if res is None or res[0] is None:
        p.min_price = None
        p.max_price = None
    else:
        p.min_price = res[0]
        p.max_price = res[1]
    await db.flush()
