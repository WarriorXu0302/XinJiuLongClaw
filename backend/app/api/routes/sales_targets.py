"""
销售目标 API — 三级（公司/品牌/员工）目标设定与进度查询
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.sales_target import SalesTarget
from app.models.product import Brand
from app.models.user import Employee
from app.services.audit_service import log_audit
from app.services.notification_service import notify

router = APIRouter()


class TargetCreate(BaseModel):
    target_level: str  # company / brand / employee
    target_year: int
    target_month: Optional[int] = None
    brand_id: Optional[str] = None
    employee_id: Optional[str] = None
    parent_target_id: Optional[str] = None
    receipt_target: float = 0.0
    sales_target: float = 0.0
    bonus_at_100: float = 0.0
    bonus_at_120: float = 0.0
    bonus_metric: str = "receipt"  # receipt / sales
    notes: Optional[str] = None


class TargetUpdate(BaseModel):
    receipt_target: Optional[float] = None
    sales_target: Optional[float] = None
    bonus_at_100: Optional[float] = None
    bonus_at_120: Optional[float] = None
    bonus_metric: Optional[str] = None
    notes: Optional[str] = None


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    target_level: str
    target_year: int
    target_month: Optional[int] = None
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    parent_target_id: Optional[str] = None
    receipt_target: float
    sales_target: float
    bonus_at_100: float = 0.0
    bonus_at_120: float = 0.0
    bonus_metric: str = "receipt"
    notes: Optional[str] = None
    # 实际完成数据
    actual_receipt: float = 0.0
    actual_sales: float = 0.0
    receipt_completion: float = 0.0  # 回款完成率
    sales_completion: float = 0.0


async def _calc_actual(
    db: AsyncSession, level: str, year: int, month: Optional[int],
    brand_id: Optional[str], employee_id: Optional[str],
) -> tuple[Decimal, Decimal]:
    """计算实际销售额 + 回款额"""
    from app.models.order import Order
    from app.models.finance import Receipt
    from sqlalchemy import extract

    # 销售 = Σ Order.total_amount
    sales_stmt = select(func.coalesce(func.sum(Order.total_amount), 0))
    sales_stmt = sales_stmt.where(extract("year", Order.created_at) == year)
    if month:
        sales_stmt = sales_stmt.where(extract("month", Order.created_at) == month)
    if brand_id:
        sales_stmt = sales_stmt.where(Order.brand_id == brand_id)
    if employee_id:
        sales_stmt = sales_stmt.where(Order.salesman_id == employee_id)
    sales = (await db.execute(sales_stmt)).scalar_one()

    # 回款 = Σ Receipt.amount
    receipt_stmt = (
        select(func.coalesce(func.sum(Receipt.amount), 0))
        .select_from(Receipt)
        .join(Order, Order.id == Receipt.order_id, isouter=True)
    )
    # 按 Receipt 时间过滤（回款周期）
    receipt_stmt = receipt_stmt.where(extract("year", Receipt.receipt_date) == year)
    if month:
        receipt_stmt = receipt_stmt.where(extract("month", Receipt.receipt_date) == month)
    if brand_id:
        receipt_stmt = receipt_stmt.where(Order.brand_id == brand_id)
    if employee_id:
        receipt_stmt = receipt_stmt.where(Order.salesman_id == employee_id)
    receipts = (await db.execute(receipt_stmt)).scalar_one()

    return Decimal(str(sales or 0)), Decimal(str(receipts or 0))


def _to_response(t: SalesTarget, actual_sales: Decimal, actual_receipt: Decimal) -> dict:
    sales_comp = float(actual_sales / t.sales_target) if t.sales_target > 0 else 0
    recv_comp = float(actual_receipt / t.receipt_target) if t.receipt_target > 0 else 0
    return {
        "id": t.id,
        "target_level": t.target_level,
        "target_year": t.target_year,
        "target_month": t.target_month,
        "brand_id": t.brand_id,
        "brand_name": t.brand.name if t.brand else None,
        "employee_id": t.employee_id,
        "employee_name": t.employee.name if t.employee else None,
        "parent_target_id": t.parent_target_id,
        "receipt_target": float(t.receipt_target),
        "sales_target": float(t.sales_target),
        "bonus_at_100": float(t.bonus_at_100 or 0),
        "bonus_at_120": float(t.bonus_at_120 or 0),
        "bonus_metric": t.bonus_metric or "receipt",
        "notes": t.notes,
        "actual_sales": float(actual_sales),
        "actual_receipt": float(actual_receipt),
        "sales_completion": round(sales_comp, 4),
        "receipt_completion": round(recv_comp, 4),
    }


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    user: CurrentUser,
    target_year: Optional[int] = Query(None),
    target_month: Optional[int] = Query(None),
    target_level: Optional[str] = Query(None),
    brand_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SalesTarget)
    if target_year:
        stmt = stmt.where(SalesTarget.target_year == target_year)
    if target_month is not None:
        stmt = stmt.where(SalesTarget.target_month == target_month)
    if target_level:
        stmt = stmt.where(SalesTarget.target_level == target_level)
    if brand_id:
        stmt = stmt.where(SalesTarget.brand_id == brand_id)
    if employee_id:
        stmt = stmt.where(SalesTarget.employee_id == employee_id)
    stmt = stmt.order_by(SalesTarget.target_year.desc(), SalesTarget.target_month.asc().nulls_first())
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for r in rows:
        s, rc = await _calc_actual(db, r.target_level, r.target_year, r.target_month, r.brand_id, r.employee_id)
        result.append(_to_response(r, s, rc))
    return result


@router.post("", response_model=TargetResponse, status_code=201)
async def create_target(body: TargetCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # 幂等：同一 key 已存在则更新
    existing = (await db.execute(
        select(SalesTarget).where(
            SalesTarget.target_level == body.target_level,
            SalesTarget.target_year == body.target_year,
            SalesTarget.target_month.is_(body.target_month) if body.target_month is None else SalesTarget.target_month == body.target_month,
            SalesTarget.brand_id.is_(body.brand_id) if body.brand_id is None else SalesTarget.brand_id == body.brand_id,
            SalesTarget.employee_id.is_(body.employee_id) if body.employee_id is None else SalesTarget.employee_id == body.employee_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.receipt_target = Decimal(str(body.receipt_target))
        existing.sales_target = Decimal(str(body.sales_target))
        existing.bonus_at_100 = Decimal(str(body.bonus_at_100))
        existing.bonus_at_120 = Decimal(str(body.bonus_at_120))
        existing.bonus_metric = body.bonus_metric
        existing.notes = body.notes
        obj = existing
    else:
        obj = SalesTarget(
            id=str(uuid.uuid4()),
            target_level=body.target_level,
            target_year=body.target_year,
            target_month=body.target_month,
            brand_id=body.brand_id,
            employee_id=body.employee_id,
            parent_target_id=body.parent_target_id,
            receipt_target=Decimal(str(body.receipt_target)),
            sales_target=Decimal(str(body.sales_target)),
            bonus_at_100=Decimal(str(body.bonus_at_100)),
            bonus_at_120=Decimal(str(body.bonus_at_120)),
            bonus_metric=body.bonus_metric,
            notes=body.notes,
        )
        db.add(obj)
    await db.flush()
    await db.refresh(obj, ["brand", "employee"])
    await log_audit(db, action="upsert_sales_target", entity_type="SalesTarget",
                    entity_id=obj.id, user=user)

    # 推送通知
    period_label = f"{obj.target_year}-{str(obj.target_month).zfill(2)}" if obj.target_month else f"{obj.target_year}年度"
    if obj.target_level == 'employee' and obj.employee_id:
        # 通知员工本人
        from app.models.user import User
        u = (await db.execute(
            select(User).where(User.employee_id == obj.employee_id, User.is_active == True)
        )).scalar_one_or_none()
        if u:
            await notify(
                db, recipient_id=u.id,
                title=f"您有新的{period_label}销售目标",
                content=f"销售目标 ¥{float(obj.sales_target):,.0f}，回款目标 ¥{float(obj.receipt_target):,.0f}",
                entity_type="SalesTarget", entity_id=obj.id,
            )
    elif obj.target_level == 'brand' and obj.brand_id:
        # 通知该品牌所有业务经理和业务员
        from app.models.payroll import EmployeeBrandPosition
        from app.models.user import User
        ebps = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.brand_id == obj.brand_id,
                EmployeeBrandPosition.position_code.in_(['sales_manager', 'salesman']),
            )
        )).scalars().all()
        emp_ids = list({e.employee_id for e in ebps})
        if emp_ids:
            users = (await db.execute(
                select(User).where(User.employee_id.in_(emp_ids), User.is_active == True)
            )).scalars().all()
            brand_name = obj.brand.name if obj.brand else ""
            for u in users:
                await notify(
                    db, recipient_id=u.id,
                    title=f"{brand_name} {period_label} 品牌目标已下达",
                    content=f"销售目标 ¥{float(obj.sales_target):,.0f}，回款目标 ¥{float(obj.receipt_target):,.0f}",
                    entity_type="SalesTarget", entity_id=obj.id,
                )
    elif obj.target_level == 'company':
        from app.services.notification_service import notify_roles
        await notify_roles(
            db, role_codes=['boss', 'finance', 'sales_manager'],
            title=f"公司 {period_label} 目标已设定",
            content=f"销售目标 ¥{float(obj.sales_target):,.0f}，回款目标 ¥{float(obj.receipt_target):,.0f}",
            entity_type="SalesTarget", entity_id=obj.id,
        )

    s, rc = await _calc_actual(db, obj.target_level, obj.target_year, obj.target_month, obj.brand_id, obj.employee_id)
    return _to_response(obj, s, rc)


@router.put("/{target_id}", response_model=TargetResponse)
async def update_target(target_id: str, body: TargetUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(SalesTarget, target_id)
    if not obj:
        raise HTTPException(404, "目标不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None and k in ("receipt_target", "sales_target"):
            setattr(obj, k, Decimal(str(v)))
        elif v is not None:
            setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj, ["brand", "employee"])
    s, rc = await _calc_actual(db, obj.target_level, obj.target_year, obj.target_month, obj.brand_id, obj.employee_id)
    return _to_response(obj, s, rc)


@router.delete("/{target_id}", status_code=204)
async def delete_target(target_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(SalesTarget, target_id)
    if not obj:
        raise HTTPException(404, "目标不存在")
    await db.delete(obj)
    await db.flush()


@router.get("/my-dashboard")
async def my_target_dashboard(
    user: CurrentUser,
    target_year: int = Query(..., description="目标年份"),
    target_month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """当前登录员工的目标 + 进度"""
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "当前用户未关联员工")
    stmt = select(SalesTarget).where(
        SalesTarget.target_level == 'employee',
        SalesTarget.employee_id == emp_id,
        SalesTarget.target_year == target_year,
    )
    if target_month is not None:
        stmt = stmt.where(SalesTarget.target_month == target_month)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for r in rows:
        s, rc = await _calc_actual(db, 'employee', r.target_year, r.target_month, r.brand_id, emp_id)
        result.append(_to_response(r, s, rc))
    return result
