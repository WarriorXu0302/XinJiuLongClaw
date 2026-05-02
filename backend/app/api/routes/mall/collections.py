"""
/api/mall/collections/*

C 端用户商品收藏：
  POST /           收藏商品（幂等）
  DELETE /{prod_id} 取消收藏
  GET  /           我的收藏列表（分页）
  GET  /check      批量查询商品是否被收藏（小程序详情页展开心形用）
  GET  /count      收藏总数

按 UniqueConstraint(user_id, product_id) 保证幂等。价格脱敏规则：
未绑定推荐人的用户虽能查看（不做 403），但返回的 price 字段会被 apply_price_visibility 脱敏。
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.product import MallCollection, MallProduct
from app.services.mall import auth_service
from app.services.mall.pricing_service import apply_price_visibility, is_price_visible

router = APIRouter()


class _CreateBody(BaseModel):
    product_id: int = Field(..., gt=0)


@router.post("")
async def add_collection(
    body: _CreateBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """收藏商品。幂等：已收藏则返回已有记录不抛错。"""
    user = await auth_service.verify_token_and_load_user(db, current)

    prod = await db.get(MallProduct, body.product_id)
    if prod is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    if prod.status != "on_sale":
        # 草稿/下架商品不允许收藏（避免 C 端收藏列表充斥永远看不到的商品）
        raise HTTPException(status_code=400, detail="该商品当前未上架")

    existing = (await db.execute(
        select(MallCollection)
        .where(MallCollection.user_id == user.id)
        .where(MallCollection.product_id == body.product_id)
    )).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "collected": True}

    c = MallCollection(user_id=user.id, product_id=body.product_id)
    db.add(c)
    try:
        await db.flush()
    except IntegrityError as e:
        # 并发双写撞 UniqueConstraint(user_id, product_id)：对用户视角是"已收藏"，
        # 抛 409 让客户端识别幂等语义（不手动 rollback，避免释放其他锁）
        raise HTTPException(status_code=409, detail="商品已在您的收藏中") from e
    return {"id": c.id, "collected": True}


@router.delete("/{product_id}", status_code=204)
async def remove_collection(
    product_id: int,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """取消收藏。幂等：不存在也不抛错。"""
    user = await auth_service.verify_token_and_load_user(db, current)
    row = (await db.execute(
        select(MallCollection)
        .where(MallCollection.user_id == user.id)
        .where(MallCollection.product_id == product_id)
    )).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()


@router.get("")
async def list_collections(
    current: CurrentMallUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    """我的收藏列表。按最近收藏倒序。"""
    user = await auth_service.verify_token_and_load_user(db, current)
    await apply_price_visibility(current, db)
    price_hidden = not is_price_visible()

    base = select(MallCollection).where(MallCollection.user_id == user.id)
    total = int((await db.execute(
        select(sa_func.count()).select_from(base.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        base.order_by(desc(MallCollection.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    prod_ids = [r.product_id for r in rows]
    prods = (await db.execute(
        select(MallProduct).where(MallProduct.id.in_(prod_ids))
    )).scalars().all()
    prod_map = {p.id: p for p in prods}

    records = []
    for r in rows:
        p = prod_map.get(r.product_id)
        if p is None:
            # 商品被删但收藏还在 → 跳过，前端不会渲染脏数据
            continue
        records.append({
            "id": r.id,
            "product_id": p.id,
            "name": p.name,
            "brief": p.brief,
            "main_image": p.main_image,
            "min_price": None if price_hidden else (float(p.min_price) if p.min_price else None),
            "max_price": None if price_hidden else (float(p.max_price) if p.max_price else None),
            "status": p.status,
            "total_sales": p.total_sales or 0,
            "created_at": r.created_at,
        })
    return {"records": records, "total": total}


@router.get("/check")
async def check_collections(
    current: CurrentMallUser,
    product_ids: List[int] = Query(..., alias="product_id"),
    db: AsyncSession = Depends(get_mall_db),
):
    """批量查询哪些商品已被收藏。

    调用形式：GET /check?product_id=1&product_id=2&product_id=3
    返回：{"collected": [1, 3]}
    """
    if not product_ids:
        return {"collected": []}
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = (await db.execute(
        select(MallCollection.product_id)
        .where(MallCollection.user_id == user.id)
        .where(MallCollection.product_id.in_(product_ids))
    )).scalars().all()
    return {"collected": list(rows)}


@router.get("/count")
async def count_collections(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """我的收藏总数（user 页角标用）。"""
    user = await auth_service.verify_token_and_load_user(db, current)
    total = int((await db.execute(
        select(sa_func.count(MallCollection.id))
        .where(MallCollection.user_id == user.id)
    )).scalar() or 0)
    return {"total": total}
