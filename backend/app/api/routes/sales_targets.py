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
    # 审批
    status: str = "approved"
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    # 实际完成数据
    actual_receipt: float = 0.0
    actual_sales: float = 0.0
    receipt_completion: float = 0.0
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
        "status": t.status or "approved",
        "submitted_by": t.submitted_by,
        "submitted_at": t.submitted_at,
        "approved_by": t.approved_by,
        "approved_at": t.approved_at,
        "reject_reason": t.reject_reason,
        "actual_sales": float(actual_sales),
        "actual_receipt": float(actual_receipt),
        "sales_completion": round(sales_comp, 4),
        "receipt_completion": round(recv_comp, 4),
    }


def _roles(user) -> list[str]:
    return user.get("roles", []) or []


def _is_admin(user) -> bool:
    r = _roles(user)
    return "admin" in r or "boss" in r


def _is_sales_manager(user) -> bool:
    return "sales_manager" in _roles(user)


def _is_pure_salesman(user) -> bool:
    r = _roles(user)
    return "salesman" in r and not _is_admin(user) and not _is_sales_manager(user)


async def _assert_sub_in_brand(
    db: AsyncSession, manager_emp_id: str, subordinate_emp_id: str, brand_id: Optional[str],
) -> str:
    """确认 subordinate 在指定品牌（或经理自己某个品牌）下是 salesman；返回 brand_id。"""
    from app.models.payroll import EmployeeBrandPosition
    # 经理的品牌集合
    mgr_brands = set((await db.execute(
        select(EmployeeBrandPosition.brand_id).where(
            EmployeeBrandPosition.employee_id == manager_emp_id,
            EmployeeBrandPosition.position_code == 'sales_manager',
        )
    )).scalars().all())
    if not mgr_brands:
        raise HTTPException(403, "您不是任何品牌的业务经理")
    # 下属
    sub_ebps = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.employee_id == subordinate_emp_id,
            EmployeeBrandPosition.position_code == 'salesman',
        )
    )).scalars().all()
    sub_brand_ids = {e.brand_id for e in sub_ebps}
    common = mgr_brands & sub_brand_ids
    if not common:
        raise HTTPException(403, "该员工不是您品牌下的业务员")
    if brand_id:
        if brand_id not in common:
            raise HTTPException(403, "该品牌不在您管辖范围")
        return brand_id
    if len(common) > 1:
        raise HTTPException(400, "请指定 brand_id（共同品牌多个）")
    return next(iter(common))


@router.get("")
async def list_targets(
    user: CurrentUser,
    target_year: Optional[int] = Query(None),
    target_month: Optional[int] = Query(None),
    target_level: Optional[str] = Query(None),
    brand_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
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
    if status:
        stmt = stmt.where(SalesTarget.status == status)

    # 角色数据范围：
    # - admin/boss/finance: 全看
    # - sales_manager: 自己品牌下全部（公司层看不到）
    # - 纯 salesman: 只看自己的 employee 级 approved 目标
    # - 其他: 只看 approved company+brand
    if _is_pure_salesman(user):
        emp_id = user.get("employee_id")
        stmt = stmt.where(
            SalesTarget.target_level == 'employee',
            SalesTarget.employee_id == emp_id,
            SalesTarget.status == 'approved',
        )
    elif _is_sales_manager(user) and not _is_admin(user):
        from app.models.payroll import EmployeeBrandPosition
        mgr_brands = list((await db.execute(
            select(EmployeeBrandPosition.brand_id).where(
                EmployeeBrandPosition.employee_id == user.get("employee_id"),
                EmployeeBrandPosition.position_code == 'sales_manager',
            )
        )).scalars().all())
        # 自己品牌的所有目标（brand/employee 层）
        if mgr_brands:
            stmt = stmt.where(SalesTarget.brand_id.in_(mgr_brands))
        else:
            stmt = stmt.where(SalesTarget.id == None)  # 不是任何品牌经理 → 空
    elif not _is_admin(user) and 'finance' not in _roles(user) and 'hr' not in _roles(user):
        # 其他角色默认只看已批准目标
        stmt = stmt.where(SalesTarget.status == 'approved')

    from sqlalchemy import func as sa_func
    total = (await db.execute(select(sa_func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = stmt.order_by(SalesTarget.target_year.desc(), SalesTarget.target_month.asc().nulls_first()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for r in rows:
        s, rc = await _calc_actual(db, r.target_level, r.target_year, r.target_month, r.brand_id, r.employee_id)
        result.append(_to_response(r, s, rc))
    return {"items": result, "total": total}


@router.post("", response_model=TargetResponse, status_code=201)
async def create_target(body: TargetCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # 权限门禁
    if _is_pure_salesman(user):
        raise HTTPException(403, "业务员无权设定目标")

    is_admin = _is_admin(user)
    is_mgr = _is_sales_manager(user) and not is_admin

    # 仅老板/管理员可下 company / brand 目标
    if body.target_level in ('company', 'brand') and not is_admin:
        raise HTTPException(403, "仅老板/管理员可下达公司或品牌目标")

    # sales_manager 只能下 employee 级目标给自己品牌下的业务员
    if body.target_level == 'employee' and is_mgr:
        if not body.employee_id:
            raise HTTPException(400, "需指定 employee_id")
        mgr_emp_id = user.get("employee_id")
        if not mgr_emp_id:
            raise HTTPException(403, "当前账号未关联员工")
        body.brand_id = await _assert_sub_in_brand(db, mgr_emp_id, body.employee_id, body.brand_id)

    # 幂等
    existing = (await db.execute(
        select(SalesTarget).where(
            SalesTarget.target_level == body.target_level,
            SalesTarget.target_year == body.target_year,
            SalesTarget.target_month.is_(body.target_month) if body.target_month is None else SalesTarget.target_month == body.target_month,
            SalesTarget.brand_id.is_(body.brand_id) if body.brand_id is None else SalesTarget.brand_id == body.brand_id,
            SalesTarget.employee_id.is_(body.employee_id) if body.employee_id is None else SalesTarget.employee_id == body.employee_id,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    # 状态决策：老板下的一律 approved；业务经理下 employee 目标 → pending_approval
    if is_admin:
        new_status = "approved"
        approval_fields = {"approved_by": user.get("employee_id"), "approved_at": now}
    else:
        new_status = "pending_approval"
        approval_fields = {
            "submitted_by": user.get("employee_id"),
            "submitted_at": now,
            "approved_by": None,
            "approved_at": None,
            "reject_reason": None,
        }

    if existing:
        # 已生效的目标不允许被经理覆盖；只允许自己重新提交被驳回的
        if existing.status == 'approved' and not is_admin:
            raise HTTPException(400, "该目标已生效，如需调整请联系老板")
        existing.receipt_target = Decimal(str(body.receipt_target))
        existing.sales_target = Decimal(str(body.sales_target))
        existing.bonus_at_100 = Decimal(str(body.bonus_at_100))
        existing.bonus_at_120 = Decimal(str(body.bonus_at_120))
        existing.bonus_metric = body.bonus_metric
        existing.notes = body.notes
        existing.status = new_status
        for k, v in approval_fields.items():
            setattr(existing, k, v)
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
            status=new_status,
            **approval_fields,
        )
        db.add(obj)
    await db.flush()
    await db.refresh(obj, ["brand", "employee"])
    await log_audit(db, action="upsert_sales_target", entity_type="SalesTarget",
                    entity_id=obj.id, user=user)

    # pending 的目标推审批通知给老板，不通知员工
    if obj.status == 'pending_approval':
        from app.services.notification_service import notify_roles
        period_label2 = f"{obj.target_year}-{str(obj.target_month).zfill(2)}" if obj.target_month else f"{obj.target_year}年度"
        emp_name = obj.employee.name if obj.employee else obj.employee_id[:8] if obj.employee_id else '-'
        await notify_roles(
            db, role_codes=['boss', 'admin'],
            title=f"销售目标审批：{emp_name} {period_label2}",
            content=f"销售 ¥{float(obj.sales_target):,.0f} / 回款 ¥{float(obj.receipt_target):,.0f}，请审批。",
            entity_type="SalesTarget", entity_id=obj.id,
        )
        s, rc = await _calc_actual(db, obj.target_level, obj.target_year, obj.target_month, obj.brand_id, obj.employee_id)
        return _to_response(obj, s, rc)

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
    # 纯业务员禁止改；sales_manager 只能改自己提交的 pending/rejected 记录
    if _is_pure_salesman(user):
        raise HTTPException(403, "业务员无权修改目标")
    is_admin = _is_admin(user)
    if not is_admin:
        if obj.submitted_by != user.get("employee_id") or obj.status not in ('pending_approval', 'rejected'):
            raise HTTPException(403, "已生效目标仅老板可改")
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
    if not _is_admin(user):
        # 经理只能删自己提交的 pending/rejected 记录
        if obj.submitted_by != user.get("employee_id") or obj.status not in ('pending_approval', 'rejected'):
            raise HTTPException(403, "仅老板可删除已生效目标")
    await db.delete(obj)
    await db.flush()


class TargetApproveRequest(BaseModel):
    approved: bool = True
    reject_reason: Optional[str] = None


@router.post("/{target_id}/approve", response_model=TargetResponse)
async def approve_target(target_id: str, body: TargetApproveRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """老板审批业务经理提交的员工目标。"""
    if not _is_admin(user):
        raise HTTPException(403, "仅老板/管理员可审批目标")
    obj = await db.get(SalesTarget, target_id)
    if not obj:
        raise HTTPException(404, "目标不存在")
    if obj.status != 'pending_approval':
        raise HTTPException(400, f"状态 {obj.status} 不能审批")
    now = datetime.now(timezone.utc)
    if body.approved:
        obj.status = 'approved'
        obj.approved_by = user.get("employee_id")
        obj.approved_at = now
        obj.reject_reason = None
    else:
        obj.status = 'rejected'
        obj.reject_reason = body.reject_reason or '已驳回'
    await db.flush()
    await db.refresh(obj, ["brand", "employee"])
    await log_audit(db, action=f"{'approve' if body.approved else 'reject'}_sales_target",
                    entity_type="SalesTarget", entity_id=obj.id, user=user)

    # 通知提交人 + 员工本人
    from app.models.user import User
    period_label = f"{obj.target_year}-{str(obj.target_month).zfill(2)}" if obj.target_month else f"{obj.target_year}年度"
    emp_name = obj.employee.name if obj.employee else '-'
    if obj.submitted_by:
        u_mgr = (await db.execute(
            select(User).where(User.employee_id == obj.submitted_by, User.is_active == True)
        )).scalar_one_or_none()
        if u_mgr:
            await notify(
                db, recipient_id=u_mgr.id,
                title=f"目标{'已批准' if body.approved else '已驳回'}：{emp_name} {period_label}",
                content=body.reject_reason if not body.approved else f"销售 ¥{float(obj.sales_target):,.0f}",
                entity_type="SalesTarget", entity_id=obj.id,
            )
    if body.approved and obj.employee_id:
        u_emp = (await db.execute(
            select(User).where(User.employee_id == obj.employee_id, User.is_active == True)
        )).scalar_one_or_none()
        if u_emp:
            await notify(
                db, recipient_id=u_emp.id,
                title=f"您有新的{period_label}销售目标",
                content=f"销售 ¥{float(obj.sales_target):,.0f} / 回款 ¥{float(obj.receipt_target):,.0f}",
                entity_type="SalesTarget", entity_id=obj.id,
            )

    s, rc = await _calc_actual(db, obj.target_level, obj.target_year, obj.target_month, obj.brand_id, obj.employee_id)
    return _to_response(obj, s, rc)


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
        SalesTarget.status == 'approved',
    )
    if target_month is not None:
        stmt = stmt.where(SalesTarget.target_month == target_month)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for r in rows:
        s, rc = await _calc_actual(db, 'employee', r.target_year, r.target_month, r.brand_id, emp_id)
        result.append(_to_response(r, s, rc))
    return result
