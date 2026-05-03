"""
/api/mall/admin/search-keywords/*

热搜词管理 CRUD（admin/boss）：
  GET    /         列表（按 is_active + sort_order 排序）
  POST   /         新增
  PUT    /{id}     更新 keyword / sort_order / is_active
  DELETE /{id}     物理删除（关键词极少，软删无意义）

C 端 /api/mall/search/hot-keywords 从这张表读 is_active=true 的。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.content import MallHotSearchKeyword
from app.services.audit_service import log_audit

router = APIRouter()


def _to_dict(k: MallHotSearchKeyword) -> dict:
    return {
        "id": k.id,
        "keyword": k.keyword,
        "sort_order": k.sort_order,
        "is_active": k.is_active,
        "created_at": k.created_at,
        "updated_at": k.updated_at,
    }


@router.get("")
async def list_keywords(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    rows = (await db.execute(
        select(MallHotSearchKeyword)
        .order_by(MallHotSearchKeyword.is_active.desc(),
                  MallHotSearchKeyword.sort_order,
                  MallHotSearchKeyword.id)
    )).scalars().all()
    return {"records": [_to_dict(r) for r in rows], "total": len(rows)}


class _CreateBody(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    is_active: bool = True


@router.post("")
async def create_keyword(
    body: _CreateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    obj = MallHotSearchKeyword(
        keyword=body.keyword.strip(),
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="关键词已存在") from e
    await log_audit(
        db, action="mall_hot_search.create",
        entity_type="MallHotSearchKeyword", entity_id=str(obj.id),
        user=user, request=request,
        changes={"keyword": obj.keyword},
    )
    return _to_dict(obj)


class _UpdateBody(BaseModel):
    keyword: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.put("/{kid}")
async def update_keyword(
    kid: int,
    body: _UpdateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    obj = await db.get(MallHotSearchKeyword, kid)
    if obj is None:
        raise HTTPException(status_code=404, detail="关键词不存在")

    updates = body.model_dump(exclude_unset=True)
    if "keyword" in updates and updates["keyword"]:
        updates["keyword"] = updates["keyword"].strip()

    for k, v in updates.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="关键词已存在") from e
    await log_audit(
        db, action="mall_hot_search.update",
        entity_type="MallHotSearchKeyword", entity_id=str(obj.id),
        user=user, request=request, changes=updates,
    )
    return _to_dict(obj)


@router.delete("/{kid}", status_code=204)
async def delete_keyword(
    kid: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    obj = await db.get(MallHotSearchKeyword, kid)
    if obj is None:
        return
    keyword_snapshot = obj.keyword
    await db.delete(obj)
    await db.flush()
    await log_audit(
        db, action="mall_hot_search.delete",
        entity_type="MallHotSearchKeyword", entity_id=str(kid),
        user=user, request=request, changes={"keyword": keyword_snapshot},
    )
