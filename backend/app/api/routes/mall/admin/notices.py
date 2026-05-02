"""
/api/mall/admin/notices/*

店铺公告运营 CRUD：
  GET    /            列表（含 draft / published，带分页）
  POST   /            新建
  PUT    /{id}        修改
  POST   /{id}/publish 发布（draft → published，publish_at=now）
  POST   /{id}/unpublish 撤回（published → draft）
  DELETE /{id}        物理删（少见；已发布公告建议用 unpublish 保留记录）

C 端 /api/mall/notices 只看到 published 的，此端点给运营管理。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.base import MallNoticeStatus
from app.models.mall.content import MallNotice
from app.services.audit_service import log_audit

router = APIRouter()


def _to_dict(n: MallNotice) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "publish_at": n.publish_at,
        "sort_order": n.sort_order,
        "status": n.status,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


@router.get("")
async def list_notices(
    user: CurrentUser,
    status: Optional[str] = Query(default=None, description="draft/published"),
    keyword: Optional[str] = Query(default=None, description="title 模糊"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = select(MallNotice)
    if status:
        stmt = stmt.where(MallNotice.status == status)
    if keyword:
        stmt = stmt.where(MallNotice.title.ilike(f"%{keyword}%"))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(MallNotice.sort_order), desc(MallNotice.created_at))
        .offset(skip).limit(limit)
    )).scalars().all()
    return {"records": [_to_dict(r) for r in rows], "total": total}


class _CreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: Optional[str] = None
    sort_order: int = Field(default=0, ge=0)
    status: str = Field(default="draft", pattern="^(draft|published)$")
    publish_at: Optional[datetime] = None  # 不传且 status=published 则取 now


@router.post("", status_code=201)
async def create_notice(
    body: _CreateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    publish_at = body.publish_at
    if body.status == MallNoticeStatus.PUBLISHED.value and publish_at is None:
        publish_at = datetime.now(timezone.utc)

    n = MallNotice(
        title=body.title,
        content=body.content,
        sort_order=body.sort_order,
        status=body.status,
        publish_at=publish_at,
    )
    db.add(n)
    await db.flush()
    await log_audit(
        db, action="mall_notice.create", entity_type="MallNotice",
        entity_id=str(n.id), user=user, request=request,
        changes={"title": n.title, "status": n.status},
    )
    return _to_dict(n)


class _UpdateBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = None
    sort_order: Optional[int] = Field(default=None, ge=0)
    publish_at: Optional[datetime] = None


@router.put("/{notice_id}")
async def update_notice(
    notice_id: int,
    body: _UpdateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    n = await db.get(MallNotice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="公告不存在")
    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(n, k, v)
    n.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_notice.update", entity_type="MallNotice",
        entity_id=str(n.id), user=user, request=request,
        changes=updates,
    )
    return _to_dict(n)


@router.post("/{notice_id}/publish")
async def publish_notice(
    notice_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """发布：draft → published。publish_at 取 now（已有值保留）。"""
    require_role(user, "admin", "boss")
    n = await db.get(MallNotice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="公告不存在")
    if n.status == MallNoticeStatus.PUBLISHED.value:
        return _to_dict(n)
    n.status = MallNoticeStatus.PUBLISHED.value
    if n.publish_at is None:
        n.publish_at = datetime.now(timezone.utc)
    n.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_notice.publish", entity_type="MallNotice",
        entity_id=str(n.id), user=user, request=request,
        changes={"title": n.title},
    )
    return _to_dict(n)


@router.post("/{notice_id}/unpublish")
async def unpublish_notice(
    notice_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """撤回：published → draft。C 端立即看不到。"""
    require_role(user, "admin", "boss")
    n = await db.get(MallNotice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="公告不存在")
    if n.status == MallNoticeStatus.DRAFT.value:
        return _to_dict(n)
    n.status = MallNoticeStatus.DRAFT.value
    n.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="mall_notice.unpublish", entity_type="MallNotice",
        entity_id=str(n.id), user=user, request=request,
        changes={"title": n.title},
    )
    return _to_dict(n)


@router.delete("/{notice_id}", status_code=204)
async def delete_notice(
    notice_id: int,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """物理删。已发布公告建议用 unpublish。"""
    require_role(user, "admin", "boss")
    n = await db.get(MallNotice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="公告不存在")
    await log_audit(
        db, action="mall_notice.delete", entity_type="MallNotice",
        entity_id=str(n.id), user=user, request=request,
        changes={"title": n.title, "was_status": n.status},
    )
    await db.delete(n)
    await db.flush()
