"""
/api/mall/admin/audit-logs/*

商城操作审计查询。

共用 ERP `audit_logs` 表，通过 `entity_type LIKE 'Mall%'` 自动过滤 mall 相关条目：
  - MallUser / MallOrder / MallPayment / MallProduct / MallProductSku /
    MallCategory / MallProductTag / MallWarehouse / MallInventory /
    MallInviteCode / MallSkipAlert 等

actor_id 指向 `employees.id`（ERP 员工），展示时联查 employees.name。
"""
import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.audit_log import AuditLog
from app.models.mall.user import MallUser
from app.models.user import Employee

router = APIRouter()


MALL_ENTITY_PREFIX = "Mall"


def _mall_filter(stmt):
    return stmt.where(AuditLog.entity_type.like(f"{MALL_ENTITY_PREFIX}%"))


@router.get("")
async def list_mall_audit_logs(
    user: CurrentUser,
    entity_type: Optional[str] = Query(None, description="精确匹配 MallOrder / MallUser..."),
    action: Optional[str] = Query(None, description="精确匹配 action 码"),
    actor_id: Optional[str] = Query(None, description="操作人 employees.id"),
    entity_id: Optional[str] = Query(None, description="业务对象 id"),
    keyword: Optional[str] = Query(None, description="模糊搜 action / entity_type"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = _mall_filter(select(AuditLog))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(kw), AuditLog.entity_type.ilike(kw)))
    if date_from:
        try:
            stmt = stmt.where(AuditLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(
                AuditLog.created_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            )
        except ValueError:
            pass

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    # ERP 员工名
    emp_ids = {r.actor_id for r in rows if r.actor_id}
    emp_name_map: dict[str, str] = {}
    if emp_ids:
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars().all()
        emp_name_map = {e.id: e.name for e in emps}

    # Mall user 名（业务员/消费者）
    mall_ids = {r.mall_user_id for r in rows if r.mall_user_id}
    mall_map: dict[str, dict] = {}
    if mall_ids:
        mus = (await db.execute(
            select(MallUser).where(MallUser.id.in_(mall_ids))
        )).scalars().all()
        mall_map = {
            m.id: {
                "nickname": m.nickname,
                "username": m.username,
                "phone": m.phone,
                "user_type": m.user_type,
            }
            for m in mus
        }

    def _actor_display(r: AuditLog) -> tuple[str | None, str | None]:
        """(展示名, id) 元组。"""
        if r.actor_type == "mall_user" and r.mall_user_id:
            m = mall_map.get(r.mall_user_id)
            if m:
                label = m["nickname"] or m["username"] or r.mall_user_id
                return label, r.mall_user_id
            return None, r.mall_user_id
        if r.actor_id:
            return emp_name_map.get(r.actor_id), r.actor_id
        return None, None

    records = []
    for r in rows:
        name, aid = _actor_display(r)
        records.append({
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor_id": aid,
            "actor_name": name,
            "actor_type": r.actor_type,
            "actor_mall_user": mall_map.get(r.mall_user_id) if r.mall_user_id else None,
            "changes": r.changes,
            "ip_address": r.ip_address,
            "created_at": r.created_at,
        })
    return {"records": records, "total": total}


@router.get("/entity-types")
async def list_mall_entity_types(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Mall 相关的 entity_type 枚举（供前端下拉）。"""
    require_role(user, "admin", "boss")
    rows = (await db.execute(
        _mall_filter(select(distinct(AuditLog.entity_type)))
    )).scalars().all()
    return sorted([r for r in rows if r])


@router.get("/actions")
async def list_mall_actions(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Mall 相关的 action 枚举（供前端下拉）。"""
    require_role(user, "admin", "boss")
    rows = (await db.execute(
        _mall_filter(select(distinct(AuditLog.action)))
    )).scalars().all()
    return sorted([r for r in rows if r])


@router.get("/export")
async def export_mall_audit_logs(
    user: CurrentUser,
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    max_rows: int = Query(default=10000, ge=1, le=50000),
    db: AsyncSession = Depends(get_db),
):
    """导出 CSV（合规/审计外发用）。最多 50000 行。

    和 list 参数一致，但不分页。
    """
    require_role(user, "admin", "boss")
    stmt = _mall_filter(select(AuditLog))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(kw), AuditLog.entity_type.ilike(kw)))
    if date_from:
        try:
            stmt = stmt.where(AuditLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(
                AuditLog.created_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            )
        except ValueError:
            pass

    rows = (await db.execute(
        stmt.order_by(AuditLog.created_at.desc()).limit(max_rows)
    )).scalars().all()

    # ERP 员工名
    emp_ids = {r.actor_id for r in rows if r.actor_id}
    emp_name_map: dict[str, str] = {}
    if emp_ids:
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars().all()
        emp_name_map = {e.id: e.name for e in emps}

    # Mall user 名
    mall_ids = {r.mall_user_id for r in rows if r.mall_user_id}
    mall_map: dict[str, MallUser] = {}
    if mall_ids:
        mus = (await db.execute(
            select(MallUser).where(MallUser.id.in_(mall_ids))
        )).scalars().all()
        mall_map = {m.id: m for m in mus}

    def _actor_fields(r: AuditLog) -> tuple[str, str]:
        if r.actor_type == "mall_user" and r.mall_user_id:
            m = mall_map.get(r.mall_user_id)
            name = (m.nickname or m.username) if m else ""
            return name or "", r.mall_user_id
        return emp_name_map.get(r.actor_id, "") if r.actor_id else "", r.actor_id or ""

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "created_at", "actor_name", "actor_id", "actor_type",
        "entity_type", "entity_id", "action", "ip_address", "changes_json",
    ])
    for r in rows:
        a_name, a_id = _actor_fields(r)
        writer.writerow([
            r.created_at.isoformat(),
            a_name,
            a_id,
            r.actor_type,
            r.entity_type,
            r.entity_id or "",
            r.action,
            r.ip_address or "",
            json.dumps(r.changes, ensure_ascii=False) if r.changes else "",
        ])
    content = buf.getvalue().encode("utf-8-sig")  # BOM → Excel 正确识别中文

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="mall_audit_{stamp}.csv"',
        },
    )
