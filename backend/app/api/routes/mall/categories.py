"""
/api/mall/categories/*

端点：
  GET /                       返回完整分类树（含 children 递归，对齐 mall4j 契约）
  GET /?parent_id=             只返指定 parent 的直接子节点
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.models.mall.product import MallCategory
from app.schemas.mall.product import MallCategoryVO

router = APIRouter()


@router.get("", response_model=list[MallCategoryVO])
async def list_categories(
    parent_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_mall_db),
):
    """分类列表。

    - 不传 parent_id：返回完整分类树（一次性给前端，减少往返）
    - 传 parent_id：只返该父节点的直接子节点（flat）
    """
    rows = (
        await db.execute(
            select(MallCategory)
            .where(MallCategory.status == "active")
            .order_by(MallCategory.sort_order, MallCategory.id)
        )
    ).scalars().all()

    if parent_id is not None:
        filtered = [r for r in rows if r.parent_id == parent_id]
        return [MallCategoryVO.model_validate(r, from_attributes=True) for r in filtered]

    # 构建 parent_id -> children 索引，递归
    by_parent: dict[Optional[int], list[MallCategory]] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)

    def build(node: MallCategory) -> MallCategoryVO:
        vo = MallCategoryVO.model_validate(node, from_attributes=True)
        vo.children = [build(c) for c in by_parent.get(node.id, [])]
        return vo

    return [build(r) for r in by_parent.get(None, [])]
