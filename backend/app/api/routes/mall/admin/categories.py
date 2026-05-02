"""
/api/mall/admin/categories/*
/api/mall/admin/tags/*

分类（树状，软删）+ 首页标签 CRUD + 商品-标签关联管理。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import asc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.product import (
    MallCategory,
    MallProduct,
    MallProductTag,
    MallProductTagRel,
)
from app.services.audit_service import log_audit

router = APIRouter()
tag_router = APIRouter()


# =============================================================================
# 分类
# =============================================================================

def _cat_dict(c: MallCategory) -> dict:
    return {
        "id": c.id,
        "parent_id": c.parent_id,
        "name": c.name,
        "icon": c.icon,
        "sort_order": c.sort_order,
        "status": c.status,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("")
async def list_categories(
    user: CurrentUser,
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """返回树状 + flat 两份（前端 TreeSelect 用 flat，Tree 用 tree）。"""
    require_role(user, "admin", "boss", "warehouse", "purchase")
    stmt = select(MallCategory)
    if not include_inactive:
        stmt = stmt.where(MallCategory.status == "active")
    stmt = stmt.order_by(asc(MallCategory.sort_order), asc(MallCategory.id))
    rows = (await db.execute(stmt)).scalars().all()

    counts = dict((await db.execute(
        select(MallProduct.category_id, sa_func.count())
        .where(MallProduct.category_id.isnot(None))
        .group_by(MallProduct.category_id)
    )).all())

    by_id: dict[int, dict] = {}
    for c in rows:
        d = _cat_dict(c)
        d["product_count"] = counts.get(c.id, 0)
        d["children"] = []
        by_id[c.id] = d

    tree: list[dict] = []
    for c in rows:
        d = by_id[c.id]
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id]["children"].append(d)
        else:
            tree.append(d)
    return {"records": tree, "flat": [_cat_dict(c) for c in rows]}


class _CatCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    sort_order: int = 0


@router.post("", status_code=201)
async def create_category(
    body: _CatCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    if body.parent_id:
        parent = await db.get(MallCategory, body.parent_id)
        if parent is None:
            raise HTTPException(status_code=400, detail="父分类不存在")
        if parent.status != "active":
            raise HTTPException(status_code=400, detail="父分类已禁用")

    c = MallCategory(
        name=body.name, parent_id=body.parent_id,
        icon=body.icon, sort_order=body.sort_order, status="active",
    )
    db.add(c)
    await db.flush()
    await log_audit(
        db, action="mall_category.create", entity_type="MallCategory",
        entity_id=str(c.id), user=user, request=request,
        changes={"name": c.name, "parent_id": c.parent_id},
    )
    return _cat_dict(c)


class _CatUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    parent_id: Optional[int] = None


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    body: _CatUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    c = await db.get(MallCategory, category_id)
    if c is None:
        raise HTTPException(status_code=404, detail="分类不存在")

    updates = body.model_dump(exclude_unset=True)

    # 防自引用 / 循环
    if "parent_id" in updates and updates["parent_id"] is not None:
        if updates["parent_id"] == category_id:
            raise HTTPException(status_code=400, detail="分类不能以自己为父")
        parent_id = updates["parent_id"]
        visited = {category_id}
        while parent_id:
            if parent_id in visited:
                raise HTTPException(status_code=400, detail="循环引用：不能将分类移到自己的子孙下")
            visited.add(parent_id)
            p = await db.get(MallCategory, parent_id)
            if p is None:
                raise HTTPException(status_code=400, detail="父分类不存在")
            parent_id = p.parent_id

    for k, v in updates.items():
        setattr(c, k, v)
    c.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_category.update", entity_type="MallCategory",
        entity_id=str(c.id), user=user, request=request, changes=updates,
    )
    return _cat_dict(c)


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删。有子分类或商品挂靠时拒绝。"""
    require_role(user, "admin", "boss")
    c = await db.get(MallCategory, category_id)
    if c is None:
        raise HTTPException(status_code=404, detail="分类不存在")

    child_count = int((await db.execute(
        select(sa_func.count()).select_from(MallCategory)
        .where(MallCategory.parent_id == category_id)
        .where(MallCategory.status == "active")
    )).scalar() or 0)
    if child_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该分类下仍有 {child_count} 个子分类，请先删除或移走",
        )

    prod_count = int((await db.execute(
        select(sa_func.count()).select_from(MallProduct)
        .where(MallProduct.category_id == category_id)
    )).scalar() or 0)
    if prod_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该分类下仍有 {prod_count} 个商品，请先移走",
        )

    c.status = "inactive"
    c.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_category.disable", entity_type="MallCategory",
        entity_id=str(c.id), user=user, request=request, changes={"name": c.name},
    )


# =============================================================================
# 标签（首页楼层）
# =============================================================================

def _tag_dict(t: MallProductTag) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "icon": t.icon,
        "sort_order": t.sort_order,
        "status": t.status,
        "created_at": t.created_at,
    }


@tag_router.get("")
async def list_tags(
    user: CurrentUser,
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = select(MallProductTag)
    if not include_inactive:
        stmt = stmt.where(MallProductTag.status == "active")
    stmt = stmt.order_by(asc(MallProductTag.sort_order), asc(MallProductTag.id))
    rows = (await db.execute(stmt)).scalars().all()

    counts = dict((await db.execute(
        select(MallProductTagRel.tag_id, sa_func.count(MallProductTagRel.id))
        .group_by(MallProductTagRel.tag_id)
    )).all())
    return {
        "records": [
            {**_tag_dict(t), "product_count": counts.get(t.id, 0)}
            for t in rows
        ]
    }


class _TagCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    icon: Optional[str] = None
    sort_order: int = 0


@tag_router.post("", status_code=201)
async def create_tag(
    body: _TagCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    t = MallProductTag(
        title=body.title, icon=body.icon,
        sort_order=body.sort_order, status="active",
    )
    db.add(t)
    await db.flush()
    await log_audit(
        db, action="mall_tag.create", entity_type="MallProductTag",
        entity_id=str(t.id), user=user, request=request, changes={"title": t.title},
    )
    return _tag_dict(t)


class _TagUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    icon: Optional[str] = None
    sort_order: Optional[int] = None


@tag_router.put("/{tag_id}")
async def update_tag(
    tag_id: int,
    body: _TagUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    t = await db.get(MallProductTag, tag_id)
    if t is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(t, k, v)
    await db.flush()
    await log_audit(
        db, action="mall_tag.update", entity_type="MallProductTag",
        entity_id=str(t.id), user=user, request=request, changes=updates,
    )
    return _tag_dict(t)


@tag_router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    t = await db.get(MallProductTag, tag_id)
    if t is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    t.status = "inactive"
    await db.flush()
    await log_audit(
        db, action="mall_tag.disable", entity_type="MallProductTag",
        entity_id=str(t.id), user=user, request=request, changes={"title": t.title},
    )


# =============================================================================
# 商品-标签关联
# =============================================================================

class _TagProductsBody(BaseModel):
    product_ids: list[int]


@tag_router.get("/{tag_id}/products")
async def list_tag_products(
    tag_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    rels = (await db.execute(
        select(MallProductTagRel)
        .where(MallProductTagRel.tag_id == tag_id)
        .order_by(asc(MallProductTagRel.sort_order))
    )).scalars().all()
    if not rels:
        return {"records": []}
    prod_ids = [r.product_id for r in rels]
    prods = (await db.execute(
        select(MallProduct).where(MallProduct.id.in_(prod_ids))
    )).scalars().all()
    prod_map = {p.id: p for p in prods}
    records = []
    for r in rels:
        p = prod_map.get(r.product_id)
        if p is None:
            continue
        records.append({
            "rel_id": r.id, "product_id": p.id, "name": p.name,
            "brief": p.brief, "main_image": p.main_image,
            "status": p.status, "sort_order": r.sort_order,
        })
    return {"records": records}


@tag_router.put("/{tag_id}/products")
async def replace_tag_products(
    tag_id: int,
    body: _TagProductsBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全量覆盖。product_ids 的顺序即 sort_order。"""
    from sqlalchemy import delete as sql_delete

    require_role(user, "admin", "boss")
    t = await db.get(MallProductTag, tag_id)
    if t is None:
        raise HTTPException(status_code=404, detail="标签不存在")

    if body.product_ids:
        existing = (await db.execute(
            select(MallProduct.id).where(MallProduct.id.in_(body.product_ids))
        )).scalars().all()
        missing = set(body.product_ids) - set(existing)
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"商品不存在: {sorted(missing)[:5]}",
            )

    await db.execute(
        sql_delete(MallProductTagRel).where(MallProductTagRel.tag_id == tag_id)
    )
    for idx, pid in enumerate(body.product_ids):
        db.add(MallProductTagRel(tag_id=tag_id, product_id=pid, sort_order=idx))
    await db.flush()
    await log_audit(
        db, action="mall_tag.set_products", entity_type="MallProductTag",
        entity_id=str(tag_id), user=user, request=request,
        changes={"tag": t.title, "count": len(body.product_ids)},
    )
    return {"success": True, "count": len(body.product_ids)}
