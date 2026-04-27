"""
Payroll API — 岗位、薪酬方案、员工品牌岗位关系、考核项、工资单、厂家补贴报账。
"""
import uuid
from datetime import datetime, timezone, date as date_type
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.payroll import (
    Position,
    BrandSalaryScheme,
    EmployeeBrandPosition,
    AssessmentItem,
    SalaryRecord,
    SalaryOrderLink,
    ManufacturerSalarySubsidy,
)
from app.models.user import Employee
from app.models.product import Brand, Account
from app.services.audit_service import log_audit

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 岗位 Positions
# ═══════════════════════════════════════════════════════════════════

class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    description: Optional[str] = None
    sort_order: int
    is_active: bool


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Position).where(Position.is_active == True).order_by(Position.sort_order)
    )).scalars().all()
    return rows


# ═══════════════════════════════════════════════════════════════════
# 品牌薪酬方案 BrandSalaryScheme
# ═══════════════════════════════════════════════════════════════════

class BrandSalarySchemeCreate(BaseModel):
    brand_id: Optional[str] = None  # null=公司通用
    position_code: str
    commission_rate: float = 0.0
    manager_share_rate: float = 0.0
    fixed_salary: float = 3000.0
    variable_salary_max: float = 1500.0
    attendance_bonus_full: float = 200.0
    notes: Optional[str] = None


class BrandSalarySchemeUpdate(BaseModel):
    commission_rate: Optional[float] = None
    manager_share_rate: Optional[float] = None
    fixed_salary: Optional[float] = None
    variable_salary_max: Optional[float] = None
    attendance_bonus_full: Optional[float] = None
    notes: Optional[str] = None


class BrandSalarySchemeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    position_code: str
    position_name: Optional[str] = None
    commission_rate: float
    manager_share_rate: float
    fixed_salary: float
    variable_salary_max: float
    attendance_bonus_full: float
    notes: Optional[str] = None
    created_at: datetime


@router.get("/salary-schemes", response_model=list[BrandSalarySchemeResponse])
async def list_schemes(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(BrandSalaryScheme).order_by(BrandSalaryScheme.brand_id, BrandSalaryScheme.position_code)
    )).scalars().all()
    result = []
    for s in rows:
        d = BrandSalarySchemeResponse.model_validate(s).model_dump()
        d["brand_name"] = s.brand.name if s.brand else "公司通用"
        d["position_name"] = s.position.name if s.position else s.position_code
        result.append(d)
    return result


@router.post("/salary-schemes", response_model=BrandSalarySchemeResponse, status_code=201)
async def create_scheme(body: BrandSalarySchemeCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    # 幂等：同一 brand+position 已存在则更新
    existing = (await db.execute(
        select(BrandSalaryScheme).where(
            BrandSalaryScheme.brand_id.is_(body.brand_id) if body.brand_id is None else BrandSalaryScheme.brand_id == body.brand_id,
            BrandSalaryScheme.position_code == body.position_code,
        )
    )).scalar_one_or_none()
    if existing:
        existing.commission_rate = Decimal(str(body.commission_rate))
        existing.manager_share_rate = Decimal(str(body.manager_share_rate))
        existing.fixed_salary = Decimal(str(body.fixed_salary))
        existing.variable_salary_max = Decimal(str(body.variable_salary_max))
        existing.attendance_bonus_full = Decimal(str(body.attendance_bonus_full))
        existing.notes = body.notes
        obj = existing
    else:
        obj = BrandSalaryScheme(
            id=str(uuid.uuid4()),
            brand_id=body.brand_id,
            position_code=body.position_code,
            commission_rate=Decimal(str(body.commission_rate)),
            manager_share_rate=Decimal(str(body.manager_share_rate)),
            fixed_salary=Decimal(str(body.fixed_salary)),
            variable_salary_max=Decimal(str(body.variable_salary_max)),
            attendance_bonus_full=Decimal(str(body.attendance_bonus_full)),
            notes=body.notes,
        )
        db.add(obj)
    await db.flush()
    await db.refresh(obj, ["brand", "position"])
    await log_audit(db, action="upsert_salary_scheme", entity_type="BrandSalaryScheme",
                    entity_id=obj.id, user=user)
    d = BrandSalarySchemeResponse.model_validate(obj).model_dump()
    d["brand_name"] = obj.brand.name if obj.brand else "公司通用"
    d["position_name"] = obj.position.name if obj.position else obj.position_code
    return d


@router.put("/salary-schemes/{scheme_id}", response_model=BrandSalarySchemeResponse)
async def update_scheme(scheme_id: str, body: BrandSalarySchemeUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(BrandSalaryScheme, scheme_id)
    if not obj:
        raise HTTPException(404, "薪酬方案不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, Decimal(str(v)) if k in ("commission_rate", "manager_share_rate", "fixed_salary", "variable_salary_max", "attendance_bonus_full") else v)
    await db.flush()
    await db.refresh(obj, ["brand", "position"])
    d = BrandSalarySchemeResponse.model_validate(obj).model_dump()
    d["brand_name"] = obj.brand.name if obj.brand else "公司通用"
    d["position_name"] = obj.position.name if obj.position else obj.position_code
    return d


@router.delete("/salary-schemes/{scheme_id}", status_code=204)
async def delete_scheme(scheme_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(BrandSalaryScheme, scheme_id)
    if not obj:
        raise HTTPException(404, "薪酬方案不存在")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# 员工 × 品牌 × 岗位 关系
# ═══════════════════════════════════════════════════════════════════

class EmpBrandPositionCreate(BaseModel):
    brand_id: str
    position_code: str
    commission_rate: Optional[float] = None
    manufacturer_subsidy: float = 0.0
    is_primary: bool = False


class EmpBrandPositionUpdate(BaseModel):
    position_code: Optional[str] = None
    commission_rate: Optional[float] = None
    manufacturer_subsidy: Optional[float] = None
    is_primary: Optional[bool] = None


class EmpBrandPositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    brand_id: str
    brand_name: Optional[str] = None
    position_code: str
    position_name: Optional[str] = None
    commission_rate: Optional[float] = None
    manufacturer_subsidy: float
    is_primary: bool


@router.get("/employees/{emp_id}/brand-positions", response_model=list[EmpBrandPositionResponse])
async def list_emp_brand_positions(emp_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(EmployeeBrandPosition).where(EmployeeBrandPosition.employee_id == emp_id)
    )).scalars().all()
    return [
        {
            **EmpBrandPositionResponse.model_validate(r).model_dump(),
            "brand_name": r.brand.name if r.brand else None,
            "position_name": r.position.name if r.position else r.position_code,
        } for r in rows
    ]


@router.post("/employees/{emp_id}/brand-positions", response_model=EmpBrandPositionResponse, status_code=201)
async def add_emp_brand_position(emp_id: str, body: EmpBrandPositionCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    emp = await db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(404, "员工不存在")
    # 如果设为主属品牌，清空其它主属
    if body.is_primary:
        others = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == emp_id,
                EmployeeBrandPosition.is_primary == True,
            )
        )).scalars().all()
        for o in others:
            o.is_primary = False

    obj = EmployeeBrandPosition(
        id=str(uuid.uuid4()),
        employee_id=emp_id,
        brand_id=body.brand_id,
        position_code=body.position_code,
        commission_rate=Decimal(str(body.commission_rate)) if body.commission_rate is not None else None,
        manufacturer_subsidy=Decimal(str(body.manufacturer_subsidy)),
        is_primary=body.is_primary,
    )
    db.add(obj)
    try:
        await db.flush()
    except Exception:
        raise HTTPException(400, "该员工已在此品牌下")
    await db.refresh(obj, ["brand", "position"])
    return {
        **EmpBrandPositionResponse.model_validate(obj).model_dump(),
        "brand_name": obj.brand.name if obj.brand else None,
        "position_name": obj.position.name if obj.position else obj.position_code,
    }


@router.put("/brand-positions/{ebp_id}", response_model=EmpBrandPositionResponse)
async def update_emp_brand_position(ebp_id: str, body: EmpBrandPositionUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(EmployeeBrandPosition, ebp_id)
    if not obj:
        raise HTTPException(404, "关系不存在")
    data = body.model_dump(exclude_unset=True)
    if data.get("is_primary"):
        others = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == obj.employee_id,
                EmployeeBrandPosition.id != obj.id,
                EmployeeBrandPosition.is_primary == True,
            )
        )).scalars().all()
        for o in others:
            o.is_primary = False
    for k, v in data.items():
        if k in ("commission_rate", "manufacturer_subsidy") and v is not None:
            setattr(obj, k, Decimal(str(v)))
        else:
            setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj, ["brand", "position"])
    return {
        **EmpBrandPositionResponse.model_validate(obj).model_dump(),
        "brand_name": obj.brand.name if obj.brand else None,
        "position_name": obj.position.name if obj.position else obj.position_code,
    }


@router.delete("/brand-positions/{ebp_id}", status_code=204)
async def delete_emp_brand_position(ebp_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(EmployeeBrandPosition, ebp_id)
    if not obj:
        raise HTTPException(404, "关系不存在")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# 月度考核项
# ═══════════════════════════════════════════════════════════════════

class AssessmentItemCreate(BaseModel):
    employee_id: str
    period: str
    brand_id: Optional[str] = None
    item_code: str
    item_name: str
    item_amount: float
    target_value: float = 0.0
    actual_value: float = 0.0
    notes: Optional[str] = None


class AssessmentItemUpdate(BaseModel):
    item_name: Optional[str] = None
    item_amount: Optional[float] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    notes: Optional[str] = None


class AssessmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    period: str
    brand_id: Optional[str] = None
    item_code: str
    item_name: str
    item_amount: float
    target_value: float
    actual_value: float
    completion_rate: float
    earned_amount: float
    notes: Optional[str] = None


def _recalc_earned(item: AssessmentItem) -> None:
    """考核项完成比例 & 应得金额。<50% 为 0，否则按比例"""
    if item.target_value and item.target_value > 0:
        rate = Decimal(item.actual_value) / Decimal(item.target_value)
    else:
        rate = Decimal("0")
    item.completion_rate = rate
    if rate < Decimal("0.5"):
        item.earned_amount = Decimal("0")
    else:
        item.earned_amount = (item.item_amount * rate).quantize(Decimal("0.01"))


@router.get("/assessment-items", response_model=list[AssessmentItemResponse])
async def list_assessment(
    user: CurrentUser,
    employee_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AssessmentItem)
    if employee_id:
        stmt = stmt.where(AssessmentItem.employee_id == employee_id)
    if period:
        stmt = stmt.where(AssessmentItem.period == period)
    stmt = stmt.order_by(AssessmentItem.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.post("/assessment-items", response_model=AssessmentItemResponse, status_code=201)
async def create_assessment(body: AssessmentItemCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = AssessmentItem(
        id=str(uuid.uuid4()),
        employee_id=body.employee_id,
        period=body.period,
        brand_id=body.brand_id,
        item_code=body.item_code,
        item_name=body.item_name,
        item_amount=Decimal(str(body.item_amount)),
        target_value=Decimal(str(body.target_value)),
        actual_value=Decimal(str(body.actual_value)),
        notes=body.notes,
    )
    _recalc_earned(obj)
    db.add(obj)
    await db.flush()
    return obj


@router.put("/assessment-items/{item_id}", response_model=AssessmentItemResponse)
async def update_assessment(item_id: str, body: AssessmentItemUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(AssessmentItem, item_id)
    if not obj:
        raise HTTPException(404, "考核项不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("item_amount", "target_value", "actual_value") and v is not None:
            setattr(obj, k, Decimal(str(v)))
        else:
            setattr(obj, k, v)
    _recalc_earned(obj)
    await db.flush()
    return obj


@router.delete("/assessment-items/{item_id}", status_code=204)
async def delete_assessment(item_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(AssessmentItem, item_id)
    if not obj:
        raise HTTPException(404, "考核项不存在")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# 工资单 SalaryRecord
# ═══════════════════════════════════════════════════════════════════

class SalaryRecordCreate(BaseModel):
    employee_id: str
    period: str
    fixed_salary: float = 0.0
    variable_salary_total: float = 0.0
    commission_total: float = 0.0
    manager_share_total: float = 0.0
    attendance_bonus: float = 0.0
    bonus_other: float = 0.0
    manufacturer_subsidy_total: float = 0.0
    late_deduction: float = 0.0
    absence_deduction: float = 0.0
    fine_deduction: float = 0.0
    social_security: float = 0.0
    work_days_month: int = 26
    work_days_actual: int = 26
    notes: Optional[str] = None


class SalaryRecordUpdate(BaseModel):
    fixed_salary: Optional[float] = None
    variable_salary_total: Optional[float] = None
    commission_total: Optional[float] = None
    manager_share_total: Optional[float] = None
    attendance_bonus: Optional[float] = None
    bonus_other: Optional[float] = None
    manufacturer_subsidy_total: Optional[float] = None
    late_deduction: Optional[float] = None
    absence_deduction: Optional[float] = None
    fine_deduction: Optional[float] = None
    social_security: Optional[float] = None
    actual_pay: Optional[float] = None
    notes: Optional[str] = None


class SalaryRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    period: str
    fixed_salary: float
    variable_salary_total: float
    commission_total: float
    manager_share_total: float
    attendance_bonus: float
    bonus_other: float
    manufacturer_subsidy_total: float
    late_deduction: float
    absence_deduction: float
    fine_deduction: float
    social_security: float
    total_pay: float
    actual_pay: float
    status: str
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    paid_at: Optional[datetime] = None
    payment_voucher_urls: Optional[list[str]] = None
    work_days_month: int
    work_days_actual: int
    notes: Optional[str] = None
    created_at: datetime


def _recalc_salary_total(r: SalaryRecord) -> None:
    """合计应发 = 底薪+浮动+提成+管理提成+全勤+其他奖+厂家补贴 - 扣款"""
    def _d(x):
        return Decimal(str(x)) if x is not None else Decimal("0")
    r.fixed_salary = _d(r.fixed_salary)
    r.variable_salary_total = _d(r.variable_salary_total)
    r.commission_total = _d(r.commission_total)
    r.manager_share_total = _d(r.manager_share_total)
    r.attendance_bonus = _d(r.attendance_bonus)
    r.bonus_other = _d(r.bonus_other)
    r.manufacturer_subsidy_total = _d(r.manufacturer_subsidy_total)
    r.late_deduction = _d(r.late_deduction)
    r.absence_deduction = _d(r.absence_deduction)
    r.fine_deduction = _d(r.fine_deduction)
    r.social_security = _d(r.social_security)
    # 厂家补贴不进员工实发（属公司对外应收，在 ManufacturerSalarySubsidy 单独记账）
    r.total_pay = (
        r.fixed_salary + r.variable_salary_total + r.commission_total
        + r.manager_share_total + r.attendance_bonus + r.bonus_other
        - r.late_deduction - r.absence_deduction - r.fine_deduction - r.social_security
    )
    # 若未手工指定 actual_pay，自动等于 total_pay
    if not r.actual_pay or _d(r.actual_pay) == 0:
        r.actual_pay = r.total_pay


@router.get("/salary-records", response_model=list[SalaryRecordResponse])
async def list_salary(
    user: CurrentUser,
    period: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import can_see_salary
    # 非 HR 类角色只能看自己的工资单
    if not can_see_salary(user) and user.get("employee_id"):
        employee_id = user.get("employee_id")
    stmt = select(SalaryRecord)
    if period:
        stmt = stmt.where(SalaryRecord.period == period)
    if employee_id:
        stmt = stmt.where(SalaryRecord.employee_id == employee_id)
    if status:
        stmt = stmt.where(SalaryRecord.status == status)
    stmt = stmt.order_by(SalaryRecord.period.desc(), SalaryRecord.employee_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {**SalaryRecordResponse.model_validate(r).model_dump(),
         "employee_name": r.employee.name if r.employee else None}
        for r in rows
    ]


@router.post("/salary-records", response_model=SalaryRecordResponse, status_code=201)
async def create_salary(body: SalaryRecordCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_can_see_salary
    require_can_see_salary(user)
    # 幂等
    existing = (await db.execute(
        select(SalaryRecord).where(
            SalaryRecord.employee_id == body.employee_id,
            SalaryRecord.period == body.period,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"{body.period} 期已存在该员工的工资单")
    data = body.model_dump()
    for k in ("fixed_salary", "variable_salary_total", "commission_total", "manager_share_total",
              "attendance_bonus", "bonus_other", "manufacturer_subsidy_total",
              "late_deduction", "absence_deduction", "fine_deduction", "social_security"):
        data[k] = Decimal(str(data[k]))
    obj = SalaryRecord(id=str(uuid.uuid4()), **data)
    _recalc_salary_total(obj)
    db.add(obj)
    await db.flush()
    await db.refresh(obj, ["employee"])
    return {**SalaryRecordResponse.model_validate(obj).model_dump(),
            "employee_name": obj.employee.name if obj.employee else None}


@router.put("/salary-records/{rec_id}", response_model=SalaryRecordResponse)
async def update_salary(rec_id: str, body: SalaryRecordUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.core.permissions import require_can_see_salary
    require_can_see_salary(user)
    obj = await db.get(SalaryRecord, rec_id)
    if not obj:
        raise HTTPException(404, "工资单不存在")
    if obj.status in ("paid", "approved", "pending_approval"):
        raise HTTPException(400, f"状态为 {obj.status} 的工资单不能修改，如需调整请驳回")
    # 仅允许修改手工字段：罚款、其他奖金、备注、实发（人工覆盖）
    ALLOWED = {"fine_deduction", "bonus_other", "notes", "actual_pay"}
    payload = body.model_dump(exclude_unset=True)
    rejected = [k for k in payload if k not in ALLOWED and payload[k] is not None]
    if rejected:
        raise HTTPException(400, f"字段 {rejected} 不能人工修改（由系统自动计算）")
    for k, v in payload.items():
        if v is not None and k in ALLOWED:
            if k == "notes":
                obj.notes = v
            else:
                setattr(obj, k, Decimal(str(v)))
    _recalc_salary_total(obj)
    await db.flush()
    await db.refresh(obj, ["employee"])
    return {**SalaryRecordResponse.model_validate(obj).model_dump(),
            "employee_name": obj.employee.name if obj.employee else None}


# ═══════════════════════════════════════════════════════════════════
# 审批流
# ═══════════════════════════════════════════════════════════════════

@router.post("/salary-records/{rec_id}/submit")
async def submit_salary(rec_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """HR 提交审批（draft/rejected → pending_approval）"""
    require_role(user, "boss", "hr")
    rec = await db.get(SalaryRecord, rec_id)
    if not rec:
        raise HTTPException(404, "工资单不存在")
    if rec.status not in ("draft", "rejected"):
        raise HTTPException(400, f"状态 {rec.status} 不能提交审批")
    rec.status = "pending_approval"
    rec.submitted_at = datetime.now(timezone.utc)
    rec.submitted_by = user.get("employee_id")
    rec.reject_reason = None
    # 通知老板
    from app.services.notification_service import notify_roles
    await notify_roles(db, role_codes=["boss", "admin"],
        title=f"工资审批：{rec.employee.name if rec.employee else ''} {rec.period}",
        content=f"实发 ¥{rec.actual_pay}，请审批。",
        entity_type="SalaryRecord", entity_id=rec.id)
    await db.flush()
    await log_audit(db, action="submit_salary", entity_type="SalaryRecord",
                    entity_id=rec.id, user=user)
    return {"detail": "已提交审批"}


class BatchSubmitRequest(BaseModel):
    salary_record_ids: list[str]


@router.post("/salary-records/batch-submit")
async def batch_submit_salary(body: BatchSubmitRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """批量提交审批"""
    require_role(user, "boss", "hr")
    recs = (await db.execute(
        select(SalaryRecord).where(SalaryRecord.id.in_(body.salary_record_ids))
    )).scalars().all()
    count = 0
    now = datetime.now(timezone.utc)
    eid = user.get("employee_id")
    from app.services.notification_service import notify_roles
    for r in recs:
        if r.status in ("draft", "rejected"):
            r.status = "pending_approval"
            r.submitted_at = now
            r.submitted_by = eid
            r.reject_reason = None
            count += 1
    if count > 0:
        await notify_roles(db, role_codes=["boss", "admin"],
            title=f"工资审批批次：{count} 人",
            content="请审批中心处理", entity_type="SalaryRecord")
    await db.flush()
    return {"detail": f"已提交 {count} 张", "count": count}


class ApproveRequest(BaseModel):
    approved: bool = True
    reject_reason: Optional[str] = None


@router.post("/salary-records/{rec_id}/approve")
async def approve_salary(rec_id: str, body: ApproveRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """老板审批（pending_approval → approved 或 rejected）"""
    require_role(user, "boss", "finance")
    rec = await db.get(SalaryRecord, rec_id)
    if not rec:
        raise HTTPException(404, "工资单不存在")
    if rec.status != "pending_approval":
        raise HTTPException(400, f"状态 {rec.status} 无法审批")
    now = datetime.now(timezone.utc)
    if body.approved:
        rec.status = "approved"
        rec.approved_at = now
        rec.approved_by = user.get("employee_id")
        rec.reject_reason = None
    else:
        rec.status = "rejected"
        rec.reject_reason = body.reject_reason or "已驳回"
    # 通知 HR 提交人
    if rec.submitted_by:
        from app.models.user import User
        from app.services.notification_service import notify
        u = (await db.execute(
            select(User).where(User.employee_id == rec.submitted_by, User.is_active == True)
        )).scalar_one_or_none()
        if u:
            await notify(db, recipient_id=u.id,
                title=f"工资{'已批准' if body.approved else '已驳回'}：{rec.employee.name if rec.employee else ''} {rec.period}",
                content=body.reject_reason or f"实发 ¥{rec.actual_pay}",
                entity_type="SalaryRecord", entity_id=rec.id)
    await db.flush()
    await log_audit(db, action=f"{'approve' if body.approved else 'reject'}_salary",
                    entity_type="SalaryRecord", entity_id=rec.id, user=user)
    return {"detail": "已批准" if body.approved else "已驳回"}


class PaySalaryRequest(BaseModel):
    payment_account_id: str  # 从哪个公司现金账户出
    voucher_urls: list[str]  # 转款凭证（银行回单/转账截图）必传


@router.post("/salary-records/{rec_id}/pay")
async def pay_salary(rec_id: str, body: PaySalaryRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """发放工资：扣公司账户 + 记录厂家应收 + 保存转款凭证"""
    require_role(user, "boss", "finance")
    from app.api.routes.accounts import record_fund_flow

    rec = await db.get(SalaryRecord, rec_id)
    if not rec:
        raise HTTPException(404, "工资单不存在")
    if rec.status == "paid":
        raise HTTPException(400, "该工资单已发放")
    if rec.status != "approved":
        raise HTTPException(400, f"必须老板审批通过才能发放，当前状态：{rec.status}")
    if not body.voucher_urls or len(body.voucher_urls) == 0:
        raise HTTPException(400, "请上传转款凭证（银行回单/转账截图）")

    pay_acc = await db.get(Account, body.payment_account_id)
    if not pay_acc:
        raise HTTPException(400, "支付账户不存在")
    if pay_acc.balance < rec.actual_pay:
        raise HTTPException(400, f"账户余额不足：{pay_acc.name} 余额 ¥{pay_acc.balance}，需付 ¥{rec.actual_pay}")

    # 扣账户 + 流水
    pay_acc.balance -= rec.actual_pay
    emp_name = rec.employee.name if rec.employee else rec.employee_id[:8]
    await record_fund_flow(
        db, account_id=pay_acc.id, flow_type='debit', amount=rec.actual_pay,
        balance_after=pay_acc.balance, related_type='salary_payment', related_id=rec.id,
        notes=f"工资发放 {emp_name} {rec.period}", created_by=user.get('employee_id'),
    )

    # 升级已有应收为 advanced；若月初未生成则补建
    ebps = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.employee_id == rec.employee_id,
            EmployeeBrandPosition.manufacturer_subsidy > 0,
        )
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for ebp in ebps:
        existing = (await db.execute(
            select(ManufacturerSalarySubsidy).where(
                ManufacturerSalarySubsidy.employee_id == rec.employee_id,
                ManufacturerSalarySubsidy.brand_id == ebp.brand_id,
                ManufacturerSalarySubsidy.period == rec.period,
            )
        )).scalar_one_or_none()
        if existing:
            if existing.status == 'pending':
                existing.status = 'advanced'
                existing.advanced_at = now
                existing.salary_record_id = rec.id
                existing.subsidy_amount = ebp.manufacturer_subsidy
        else:
            db.add(ManufacturerSalarySubsidy(
                id=str(uuid.uuid4()),
                employee_id=rec.employee_id,
                brand_id=ebp.brand_id,
                salary_record_id=rec.id,
                period=rec.period,
                subsidy_amount=ebp.manufacturer_subsidy,
                status='advanced',
                advanced_at=now,
            ))

    rec.status = 'paid'
    rec.paid_at = now
    rec.paid_by = user.get('employee_id')
    rec.payment_voucher_urls = body.voucher_urls

    # 推送工资到账通知给员工本人
    from app.models.user import User
    from app.services.notification_service import notify
    u = (await db.execute(
        select(User).where(User.employee_id == rec.employee_id, User.is_active == True)
    )).scalar_one_or_none()
    if u:
        await notify(
            db, recipient_id=u.id,
            title=f"您的 {rec.period} 工资已发放",
            content=f"实发工资 ¥{rec.actual_pay}。请在\"我的\"查看明细。",
            entity_type="SalaryRecord", entity_id=rec.id,
        )

    await db.flush()
    await log_audit(db, action="pay_salary", entity_type="SalaryRecord", entity_id=rec.id,
                    changes={"employee": emp_name, "period": rec.period, "amount": float(rec.actual_pay)},
                    user=user)
    return {"detail": f"{emp_name} {rec.period} 工资 ¥{rec.actual_pay} 已发放"}


@router.delete("/salary-records/{rec_id}", status_code=204)
async def delete_salary(rec_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "hr")
    obj = await db.get(SalaryRecord, rec_id)
    if not obj:
        raise HTTPException(404, "工资单不存在")
    if obj.status == 'paid':
        raise HTTPException(400, "已发放的工资单不能删除")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# 厂家工资补贴报账
# ═══════════════════════════════════════════════════════════════════

class SubsidyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    brand_id: str
    brand_name: Optional[str] = None
    salary_record_id: Optional[str] = None
    period: str
    subsidy_amount: float
    status: str
    advanced_at: Optional[datetime] = None
    arrival_billcode: Optional[str] = None
    arrival_at: Optional[datetime] = None
    reimbursed_at: Optional[datetime] = None
    reimburse_notes: Optional[str] = None


@router.get("/manufacturer-subsidies")
async def list_subsidies(
    user: CurrentUser,
    brand_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func as sa_func
    base = select(ManufacturerSalarySubsidy)
    if brand_id:
        base = base.where(ManufacturerSalarySubsidy.brand_id == brand_id)
    if period:
        base = base.where(ManufacturerSalarySubsidy.period == period)
    if status:
        base = base.where(ManufacturerSalarySubsidy.status == status)
    total = (await db.execute(select(sa_func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(ManufacturerSalarySubsidy.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": [
        {**SubsidyResponse.model_validate(s).model_dump(),
         "employee_name": s.employee.name if s.employee else None,
         "brand_name": s.brand.name if s.brand else None}
        for s in rows
    ], "total": total}


class GenerateExpectedRequest(BaseModel):
    period: str  # "2026-04"


@router.post("/manufacturer-subsidies/generate-expected")
async def generate_expected_subsidies(body: GenerateExpectedRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """月初按员工×品牌应得补贴挂账 pending 记录（幂等：已存在则跳过）"""
    from app.core.permissions import require_can_see_salary
    require_can_see_salary(user)
    ebps = (await db.execute(
        select(EmployeeBrandPosition).where(EmployeeBrandPosition.manufacturer_subsidy > 0)
    )).scalars().all()
    created = 0
    skipped = 0
    for ebp in ebps:
        existing = (await db.execute(
            select(ManufacturerSalarySubsidy).where(
                ManufacturerSalarySubsidy.employee_id == ebp.employee_id,
                ManufacturerSalarySubsidy.brand_id == ebp.brand_id,
                ManufacturerSalarySubsidy.period == body.period,
            )
        )).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        db.add(ManufacturerSalarySubsidy(
            id=str(uuid.uuid4()),
            employee_id=ebp.employee_id,
            brand_id=ebp.brand_id,
            period=body.period,
            subsidy_amount=ebp.manufacturer_subsidy,
            status='pending',
        ))
        created += 1
    await db.flush()
    await log_audit(db, action="generate_expected_subsidies",
                    entity_type="ManufacturerSalarySubsidy",
                    changes={"period": body.period, "created": created}, user=user)
    return {"detail": f"已生成 {created} 条，跳过 {skipped} 条（已存在）", "created": created, "skipped": skipped}


class ConfirmSubsidyArrivalRequest(BaseModel):
    brand_id: str
    period: str
    arrived_amount: float
    billcode: Optional[str] = None
    notes: Optional[str] = None


@router.post("/manufacturer-subsidies/confirm-arrival")
async def confirm_subsidy_arrival(body: ConfirmSubsidyArrivalRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """厂家工资补贴到账确认：金额必须等于该品牌该期 pending+advanced 记录合计，钱进品牌现金账户。"""
    require_role(user, "boss", "finance")
    from app.api.routes.accounts import record_fund_flow

    subs = (await db.execute(
        select(ManufacturerSalarySubsidy).where(
            ManufacturerSalarySubsidy.brand_id == body.brand_id,
            ManufacturerSalarySubsidy.period == body.period,
            ManufacturerSalarySubsidy.status.in_(('pending', 'advanced')),
        )
    )).scalars().all()
    if not subs:
        raise HTTPException(400, f"未找到 {body.period} 待到账补贴")
    total = sum((s.subsidy_amount for s in subs), Decimal("0"))
    arrived = Decimal(str(body.arrived_amount))
    if arrived != total:
        raise HTTPException(400, f"到账金额 ¥{arrived} 与应收合计 ¥{total} 不一致")

    cash_acc = (await db.execute(
        select(Account).where(
            Account.brand_id == body.brand_id,
            Account.account_type == 'cash',
            Account.level == 'project',
        )
    )).scalar_one_or_none()
    if not cash_acc:
        raise HTTPException(400, "品牌未配置现金账户")

    now = datetime.now(timezone.utc)
    cash_acc.balance += total
    await record_fund_flow(
        db, account_id=cash_acc.id, flow_type='credit', amount=total,
        balance_after=cash_acc.balance,
        related_type='manufacturer_salary_arrival',
        notes=f"厂家工资补贴到账 {body.period} 单据 {body.billcode or '-'}",
        created_by=user.get('employee_id'),
    )
    for s in subs:
        s.status = 'reimbursed'
        s.arrival_at = now
        s.arrival_billcode = body.billcode
        s.reimbursed_at = now
        s.reimburse_account_id = cash_acc.id
        s.reimburse_notes = body.notes

    await db.flush()
    await log_audit(db, action="confirm_subsidy_arrival",
                    entity_type="ManufacturerSalarySubsidy",
                    changes={"brand_id": body.brand_id, "period": body.period,
                             "amount": float(total), "count": len(subs)}, user=user)
    return {"detail": f"已核销 {len(subs)} 条，合计 ¥{total}", "count": len(subs)}


class ManualMarkRequest(BaseModel):
    subsidy_id: str
    notes: Optional[str] = None


@router.post("/manufacturer-subsidies/manual-mark-arrived")
async def manual_mark_arrived(body: ManualMarkRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """兜底：单条手工标记到账（厂家不走对账单，如现金直给）"""
    require_role(user, "boss", "finance")
    s = await db.get(ManufacturerSalarySubsidy, body.subsidy_id)
    if not s:
        raise HTTPException(404, "补贴记录不存在")
    if s.status == 'reimbursed':
        raise HTTPException(400, "该记录已核销")
    now = datetime.now(timezone.utc)
    s.status = 'reimbursed'
    s.arrival_at = now
    s.reimbursed_at = now
    s.reimburse_notes = body.notes or "手工标记"
    await db.flush()
    return {"detail": "已标记到账"}


# ═══════════════════════════════════════════════════════════════════
# 工资单一键生成（Phase 2：佣金自动算）
# ═══════════════════════════════════════════════════════════════════

class GenerateSalaryRequest(BaseModel):
    period: str  # 如 "2026-04"
    pay_cutoff_date: Optional[str] = None  # 发薪截止日 YYYY-MM-DD，默认取 period 月底
    employee_ids: Optional[list[str]] = None  # 指定员工；不传=所有在职员工
    overwrite: bool = False  # 若已存在该期工资单是否覆盖


def _compute_kpi_coefficient(actual: Decimal, target: Decimal) -> Decimal:
    """根据回款完成率返回提成系数。
    规则：<50% → 0；[50%,100%) → 按完成率（单调递增）；≥100% → 按完成率（继续放大）。
    历史 bug：[0.8,1.0) 区间曾 return 0.8，导致完成度 0.9 的员工系数比 0.7 的还低（反转）。
    """
    if not target or target <= 0:
        return Decimal("1.0")
    rate = actual / target
    if rate < Decimal("0.5"):
        return Decimal("0")
    return rate.quantize(Decimal("0.0001"))


async def _get_fully_paid_orders_for_employee(
    db: AsyncSession, employee_id: str, brand_id: str, pay_cutoff: datetime,
) -> list[tuple[str, Decimal]]:
    """返回 (order_id, commission_base) 列表。
    commission_base 按结算模式：
      - company_pay：使用 deal_amount（客户到手价总额，公司实收）
      - 其他：使用 total_amount（指导价总额）
    过滤条件：
      - Order.salesman_id=emp / brand / FULLY_PAID
      - 最后一笔 Receipt <= pay_cutoff
      - 未被纳入其他 SalaryOrderLink
    """
    from app.models.order import Order
    from app.models.finance import Receipt
    from app.models.base import PaymentStatus

    stmt = (
        select(
            Order.id,
            Order.customer_paid_amount,
            Order.total_amount,
            func.max(Receipt.receipt_date).label("last_receipt_date"),
        )
        .select_from(Order)
        .join(Receipt, Receipt.order_id == Order.id, isouter=True)
        .where(
            Order.salesman_id == employee_id,
            Order.brand_id == brand_id,
            Order.payment_status == PaymentStatus.FULLY_PAID,
        )
        .group_by(Order.id)
    )
    rows = (await db.execute(stmt)).all()

    cutoff_date = pay_cutoff.date() if isinstance(pay_cutoff, datetime) else pay_cutoff
    qualified = [r for r in rows if r.last_receipt_date and r.last_receipt_date <= cutoff_date]

    if not qualified:
        return []

    already = (await db.execute(
        select(SalaryOrderLink.order_id).where(SalaryOrderLink.order_id.in_([r.id for r in qualified]))
    )).scalars().all()
    already_set = set(already)

    # 提成基数 = 订单应收（customer_paid_amount；公司让利模式下公司实收）
    def _base(r) -> Decimal:
        return Decimal(str(r.customer_paid_amount or r.total_amount or 0))

    return [(r.id, _base(r)) for r in qualified if r.id not in already_set]


async def _commission_rate_for(
    db: AsyncSession, ebp: EmployeeBrandPosition,
) -> tuple[Decimal, Decimal]:
    """返回 (销售提成率, 管理提成率)。个性化覆盖 > 品牌默认 > 0"""
    # 个性化
    if ebp.commission_rate is not None:
        cr = Decimal(str(ebp.commission_rate))
    else:
        cr = Decimal("0")
    # 品牌默认
    scheme = (await db.execute(
        select(BrandSalaryScheme).where(
            BrandSalaryScheme.brand_id == ebp.brand_id,
            BrandSalaryScheme.position_code == ebp.position_code,
        )
    )).scalar_one_or_none()
    if scheme:
        if ebp.commission_rate is None:
            cr = Decimal(str(scheme.commission_rate))
        manager_share = Decimal(str(scheme.manager_share_rate))
    else:
        manager_share = Decimal("0")
    return cr, manager_share


@router.post("/salary-records/generate")
async def generate_salary_records(
    body: GenerateSalaryRequest, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """一键按周期为所有员工自动生成工资单（含自动算佣金、KPI系数、厂家补贴）。

    计算规则：
      - 销售提成: 员工名下该品牌已全额回款且未结算过的订单 → Σ回款 × 品牌提成率 × KPI系数
      - 管理提成(仅 sales_manager): 同品牌下所有 salesman 的订单回款合计 × 经理的 manager_share_rate
      - 考核浮动底薪: 从 AssessmentItem 表 earned_amount 汇总
      - 厂家补贴: 从 EmployeeBrandPosition.manufacturer_subsidy 累加
      - 底薪 / 社保: 从 Employee 表取
    """
    require_role(user, "boss", "finance")
    # 解析截止日期
    if body.pay_cutoff_date:
        cutoff = datetime.strptime(body.pay_cutoff_date, "%Y-%m-%d")
    else:
        # 默认 period 月末
        y, m = map(int, body.period.split("-"))
        if m == 12:
            cutoff = datetime(y+1, 1, 1) - __import__("datetime").timedelta(days=1)
        else:
            cutoff = datetime(y, m+1, 1) - __import__("datetime").timedelta(days=1)
        cutoff = cutoff.replace(hour=23, minute=59, second=59)

    # 目标员工
    emp_stmt = select(Employee).where(Employee.status == 'active')
    if body.employee_ids:
        emp_stmt = emp_stmt.where(Employee.id.in_(body.employee_ids))
    employees = (await db.execute(emp_stmt)).scalars().all()

    generated = []
    skipped = []
    for emp in employees:
        # 厂家人员不发工资
        # 检查是否已存在该期工资单
        exists = (await db.execute(
            select(SalaryRecord).where(
                SalaryRecord.employee_id == emp.id,
                SalaryRecord.period == body.period,
            )
        )).scalar_one_or_none()
        if exists and not body.overwrite:
            skipped.append({"employee_id": emp.id, "name": emp.name, "reason": "已存在"})
            continue
        if exists and body.overwrite and exists.status == 'paid':
            skipped.append({"employee_id": emp.id, "name": emp.name, "reason": "已发放无法覆盖"})
            continue

        # 员工所有品牌×岗位
        ebps = (await db.execute(
            select(EmployeeBrandPosition).where(EmployeeBrandPosition.employee_id == emp.id)
        )).scalars().all()

        # 跳过纯厂家人员
        if ebps and all(e.position_code == 'mfr_staff' for e in ebps):
            skipped.append({"employee_id": emp.id, "name": emp.name, "reason": "厂家人员不发薪"})
            continue

        # 取 KPI 考核项的 earned_amount 合计作为浮动底薪
        assess = (await db.execute(
            select(func.coalesce(func.sum(AssessmentItem.earned_amount), 0))
            .where(
                AssessmentItem.employee_id == emp.id,
                AssessmentItem.period == body.period,
            )
        )).scalar_one()
        variable_total = Decimal(str(assess))

        # 计算 KPI 系数（全局回款目标完成率，用于缩放销售提成）
        # 取"回款金额"考核项的 completion_rate 作为 KPI 系数基础
        kpi_item = (await db.execute(
            select(AssessmentItem).where(
                AssessmentItem.employee_id == emp.id,
                AssessmentItem.period == body.period,
                AssessmentItem.item_code == 'kpi_revenue',
            )
        )).scalar_one_or_none()

        # 遍历品牌×岗位计算提成
        commission_total = Decimal("0")
        manager_share_total = Decimal("0")
        subsidy_total = Decimal("0")
        order_links = []

        # 整体回款合计（算 KPI 系数）
        total_receipt = Decimal("0")

        for ebp in ebps:
            if ebp.position_code == 'mfr_staff':
                continue
            subsidy_total += Decimal(str(ebp.manufacturer_subsidy))
            orders = await _get_fully_paid_orders_for_employee(db, emp.id, ebp.brand_id, cutoff)
            if not orders:
                continue
            emp_brand_receipt = sum((r for _, r in orders), Decimal("0"))
            total_receipt += emp_brand_receipt

            cr, manager_share = await _commission_rate_for(db, ebp)

            # KPI 系数（按实际完成率）
            if kpi_item and kpi_item.target_value:
                coef = _compute_kpi_coefficient(
                    Decimal(str(kpi_item.actual_value or 0)),
                    Decimal(str(kpi_item.target_value)),
                )
            else:
                coef = Decimal("1.0")  # 没设 KPI 目标，系数=1

            for oid, rec_amount in orders:
                comm = (rec_amount * cr * coef).quantize(Decimal("0.01"))
                commission_total += comm
                order_links.append({
                    "order_id": oid, "brand_id": ebp.brand_id,
                    "receipt_amount": rec_amount, "rate": cr, "coef": coef,
                    "amount": comm, "is_manager": False,
                })

            # 业务经理 额外拿同品牌下属的份额
            if ebp.position_code == 'sales_manager' and manager_share > 0:
                subs = (await db.execute(
                    select(EmployeeBrandPosition).where(
                        EmployeeBrandPosition.brand_id == ebp.brand_id,
                        EmployeeBrandPosition.position_code == 'salesman',
                        EmployeeBrandPosition.employee_id != emp.id,
                    )
                )).scalars().all()
                for sub in subs:
                    sub_orders = await _get_fully_paid_orders_for_employee(
                        db, sub.employee_id, ebp.brand_id, cutoff,
                    )
                    for oid, rec_amount in sub_orders:
                        share = (rec_amount * manager_share).quantize(Decimal("0.01"))
                        manager_share_total += share
                        order_links.append({
                            "order_id": oid, "brand_id": ebp.brand_id,
                            "receipt_amount": rec_amount, "rate": manager_share,
                            "coef": Decimal("1"), "amount": share, "is_manager": True,
                        })

        # 考勤汇总（用于判全勤 + 迟到扣款）
        from app.models.attendance import CheckinRecord, LeaveRequest
        from datetime import date as _d
        _y, _m = map(int, body.period.split("-"))
        _start = _d(_y, _m, 1)
        _end = _d(_y+1, 1, 1) - __import__("datetime").timedelta(days=1) if _m == 12 \
            else _d(_y, _m+1, 1) - __import__("datetime").timedelta(days=1)
        checkins = (await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.employee_id == emp.id,
                CheckinRecord.checkin_date.between(_start, _end),
            )
        )).scalars().all()
        late_times = sum(1 for c in checkins if c.status == "late")
        late_over30 = sum(1 for c in checkins if c.status == "late_over30")
        leaves = (await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= _end,
                LeaveRequest.end_date >= _start,
                LeaveRequest.leave_type != 'overtime_off',  # 调休不算缺勤
            )
        )).scalars().all()
        leave_days_total = sum(Decimal(str(l.total_days or 0)) for l in leaves)

        # 迟到扣款：<=30分钟 每次10，>30分钟 每次50
        late_deduction = Decimal(late_times) * Decimal("10") + Decimal(late_over30) * Decimal("50")

        # 底薪与全勤奖：按主属品牌×岗位的 BrandSalaryScheme 取
        primary = next((e for e in ebps if e.is_primary), None)
        if primary is None:
            skipped.append({"employee_id": emp.id, "name": emp.name, "reason": "未设置主属品牌，无法生成底薪"})
            continue
        scheme = (await db.execute(
            select(BrandSalaryScheme).where(
                BrandSalaryScheme.brand_id == primary.brand_id,
                BrandSalaryScheme.position_code == primary.position_code,
            )
        )).scalar_one_or_none()
        if scheme is None:
            skipped.append({
                "employee_id": emp.id, "name": emp.name,
                "reason": f"主属品牌×岗位（{primary.brand_id[:8]}/{primary.position_code}）未配置薪酬方案",
            })
            continue
        fixed = Decimal(str(scheme.fixed_salary))
        full_amount = Decimal(str(scheme.attendance_bonus_full))

        # 全勤奖：按请假天数阶梯扣（公司统一规则）
        #   0天=100% / 1天=80% / 2天=60% / 3天=40% / 4天=20% / ≥5天=0
        # 有迟到或旷工 → 直接 0
        if late_times > 0 or late_over30 > 0:
            attendance_bonus = Decimal("0")
        else:
            ld = int(leave_days_total)
            ratio_map = {0: Decimal("1"), 1: Decimal("0.8"), 2: Decimal("0.6"),
                         3: Decimal("0.4"), 4: Decimal("0.2")}
            ratio = ratio_map.get(ld, Decimal("0"))
            attendance_bonus = (full_amount * ratio).quantize(Decimal("0.01"))

        # 社保代扣（员工个人差异项）
        social = Decimal(str(emp.social_security or 0))

        # 达标奖金：扫描该员工本月 employee 级目标，按完成率匹配
        from app.models.sales_target import SalesTarget
        from app.models.order import Order as _Ord
        from app.models.finance import Receipt as _Rc
        from sqlalchemy import extract as _ext
        bonus_other = Decimal("0")
        bonus_notes = []
        targets = (await db.execute(
            select(SalesTarget).where(
                SalesTarget.target_level == 'employee',
                SalesTarget.employee_id == emp.id,
                SalesTarget.target_year == _y,
                SalesTarget.target_month == _m,
            )
        )).scalars().all()
        for t in targets:
            # 取触发指标的实际值
            if t.bonus_metric == 'sales':
                actual_stmt = select(func.coalesce(func.sum(_Ord.total_amount), 0)).where(
                    _Ord.salesman_id == emp.id,
                    _ext("year", _Ord.created_at) == _y,
                    _ext("month", _Ord.created_at) == _m,
                )
                if t.brand_id:
                    actual_stmt = actual_stmt.where(_Ord.brand_id == t.brand_id)
                target_val = t.sales_target
            else:
                actual_stmt = (
                    select(func.coalesce(func.sum(_Rc.amount), 0))
                    .select_from(_Rc).join(_Ord, _Ord.id == _Rc.order_id, isouter=True)
                    .where(
                        _Ord.salesman_id == emp.id,
                        _ext("year", _Rc.receipt_date) == _y,
                        _ext("month", _Rc.receipt_date) == _m,
                    )
                )
                if t.brand_id:
                    actual_stmt = actual_stmt.where(_Ord.brand_id == t.brand_id)
                target_val = t.receipt_target
            actual = (await db.execute(actual_stmt)).scalar_one() or 0
            if not target_val or target_val <= 0:
                continue
            rate = Decimal(str(actual)) / target_val
            # 阶梯：≥120% 拿 bonus_at_120，否则若 ≥100% 拿 bonus_at_100
            if rate >= Decimal("1.2") and t.bonus_at_120 and t.bonus_at_120 > 0:
                bonus_other += t.bonus_at_120
                bonus_notes.append(f"达标奖(120%+) ¥{t.bonus_at_120}")
            elif rate >= Decimal("1.0") and t.bonus_at_100 and t.bonus_at_100 > 0:
                bonus_other += t.bonus_at_100
                bonus_notes.append(f"达标奖(100%+) ¥{t.bonus_at_100}")

        # 删除旧工资单（overwrite 情况）
        if exists and body.overwrite:
            await db.execute(
                __import__("sqlalchemy").delete(SalaryOrderLink).where(
                    SalaryOrderLink.salary_record_id == exists.id
                )
            )
            await db.delete(exists)
            await db.flush()

        rec = SalaryRecord(
            id=str(uuid.uuid4()),
            employee_id=emp.id,
            period=body.period,
            fixed_salary=fixed,
            variable_salary_total=variable_total,
            commission_total=commission_total,
            manager_share_total=manager_share_total,
            attendance_bonus=attendance_bonus,
            bonus_other=bonus_other,
            manufacturer_subsidy_total=subsidy_total,
            late_deduction=late_deduction,
            absence_deduction=Decimal("0"),
            fine_deduction=Decimal("0"),
            social_security=social,
            status='draft',
            work_days_month=26,
            work_days_actual=26,
            notes="；".join(bonus_notes) if bonus_notes else None,
        )
        _recalc_salary_total(rec)
        db.add(rec)
        await db.flush()

        # 订单明细
        for link in order_links:
            db.add(SalaryOrderLink(
                id=str(uuid.uuid4()),
                salary_record_id=rec.id,
                order_id=link["order_id"],
                brand_id=link["brand_id"],
                receipt_amount=link["receipt_amount"],
                commission_rate_used=link["rate"],
                kpi_coefficient=link["coef"],
                commission_amount=link["amount"],
                is_manager_share=link["is_manager"],
            ))

        generated.append({
            "employee_id": emp.id,
            "name": emp.name,
            "commission": float(commission_total),
            "manager_share": float(manager_share_total),
            "subsidy": float(subsidy_total),
            "total_pay": float(rec.total_pay),
            "order_count": len(order_links),
        })

    await db.flush()
    await log_audit(
        db, action="generate_salary_records", entity_type="SalaryRecord",
        changes={"period": body.period, "generated": len(generated), "skipped": len(skipped)},
        user=user,
    )
    return {
        "period": body.period,
        "generated": generated,
        "skipped": skipped,
    }


@router.get("/salary-records/{rec_id}/order-links")
async def get_salary_order_links(
    rec_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """查看工资单的订单提成明细"""
    from app.models.order import Order
    rows = (await db.execute(
        select(SalaryOrderLink).where(SalaryOrderLink.salary_record_id == rec_id)
        .order_by(SalaryOrderLink.created_at.desc())
    )).scalars().all()
    result = []
    for r in rows:
        order = await db.get(Order, r.order_id)
        brand = await db.get(Brand, r.brand_id)
        result.append({
            "id": r.id,
            "order_id": r.order_id,
            "order_no": order.order_no if order else None,
            "customer_name": order.customer.name if order and order.customer else None,
            "brand_id": r.brand_id,
            "brand_name": brand.name if brand else None,
            "receipt_amount": float(r.receipt_amount),
            "commission_rate_used": float(r.commission_rate_used),
            "kpi_coefficient": float(r.kpi_coefficient),
            "commission_amount": float(r.commission_amount),
            "is_manager_share": r.is_manager_share,
        })
    return result


# ═══════════════════════════════════════════════════════════════════
# 批量发放工资
# ═══════════════════════════════════════════════════════════════════

class BatchPayRequest(BaseModel):
    salary_record_ids: list[str]
    payment_account_id: str
    voucher_urls: list[str]  # 批量发放共用一套凭证


@router.post("/salary-records/batch-pay")
async def batch_pay_salary(
    body: BatchPayRequest, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """批量发放：一次扣公司账户总额 + 批量生成厂家应收"""
    require_role(user, "boss", "finance")
    from app.api.routes.accounts import record_fund_flow

    if not body.salary_record_ids:
        raise HTTPException(400, "未选择工资单")
    if not body.voucher_urls or len(body.voucher_urls) == 0:
        raise HTTPException(400, "请上传转款凭证（银行回单/转账截图）")

    recs = (await db.execute(
        select(SalaryRecord).where(SalaryRecord.id.in_(body.salary_record_ids))
    )).scalars().all()
    # 只发放 approved 状态
    pending = [r for r in recs if r.status == 'approved']
    if not pending:
        raise HTTPException(400, "选中的工资单中没有已审批通过的")

    pay_acc = await db.get(Account, body.payment_account_id)
    if not pay_acc:
        raise HTTPException(400, "支付账户不存在")
    total = sum((r.actual_pay for r in pending), Decimal("0"))
    if pay_acc.balance < total:
        raise HTTPException(400, f"账户余额不足：{pay_acc.name} 余额 ¥{pay_acc.balance}，需付 ¥{total}")

    now = datetime.now(timezone.utc)
    paid_count = 0
    for rec in pending:
        if rec.actual_pay <= 0:
            continue
        pay_acc.balance -= rec.actual_pay
        emp_name = rec.employee.name if rec.employee else rec.employee_id[:8]
        await record_fund_flow(
            db, account_id=pay_acc.id, flow_type='debit', amount=rec.actual_pay,
            balance_after=pay_acc.balance, related_type='salary_payment', related_id=rec.id,
            notes=f"工资发放 {emp_name} {rec.period}",
            created_by=user.get('employee_id'),
        )
        # 升级已有补贴应收为 advanced；缺失则补建
        ebps = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == rec.employee_id,
                EmployeeBrandPosition.manufacturer_subsidy > 0,
            )
        )).scalars().all()
        for ebp in ebps:
            existing = (await db.execute(
                select(ManufacturerSalarySubsidy).where(
                    ManufacturerSalarySubsidy.employee_id == rec.employee_id,
                    ManufacturerSalarySubsidy.brand_id == ebp.brand_id,
                    ManufacturerSalarySubsidy.period == rec.period,
                )
            )).scalar_one_or_none()
            if existing:
                if existing.status == 'pending':
                    existing.status = 'advanced'
                    existing.advanced_at = now
                    existing.salary_record_id = rec.id
                    existing.subsidy_amount = ebp.manufacturer_subsidy
            else:
                db.add(ManufacturerSalarySubsidy(
                    id=str(uuid.uuid4()),
                    employee_id=rec.employee_id,
                    brand_id=ebp.brand_id,
                    salary_record_id=rec.id,
                    period=rec.period,
                    subsidy_amount=ebp.manufacturer_subsidy,
                    status='advanced',
                    advanced_at=now,
                ))
        rec.status = 'paid'
        rec.paid_at = now
        rec.paid_by = user.get('employee_id')
        rec.payment_voucher_urls = body.voucher_urls
        paid_count += 1

        # 推送给员工本人
        from app.models.user import User as _U
        from app.services.notification_service import notify as _notify
        u = (await db.execute(
            select(_U).where(_U.employee_id == rec.employee_id, _U.is_active == True)
        )).scalar_one_or_none()
        if u:
            await _notify(
                db, recipient_id=u.id,
                title=f"您的 {rec.period} 工资已发放",
                content=f"实发工资 ¥{rec.actual_pay}。请在\"我的\"查看明细。",
                entity_type="SalaryRecord", entity_id=rec.id,
            )

    await db.flush()
    await log_audit(db, action="batch_pay_salary", entity_type="SalaryRecord",
                    changes={"count": paid_count, "total": float(total)}, user=user)
    return {"detail": f"已发放 {paid_count} 张工资单，共扣款 ¥{total}", "count": paid_count}


class BatchConfirmRequest(BaseModel):
    salary_record_ids: list[str]


@router.post("/salary-records/batch-confirm")
async def batch_confirm_salary(
    body: BatchConfirmRequest, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """批量确认（draft → confirmed）"""
    require_role(user, "boss", "hr")
    recs = (await db.execute(
        select(SalaryRecord).where(SalaryRecord.id.in_(body.salary_record_ids))
    )).scalars().all()
    count = 0
    for r in recs:
        if r.status == 'draft':
            r.status = 'confirmed'
            count += 1
    await db.flush()
    return {"detail": f"已确认 {count} 张"}


@router.get("/salary-records/{rec_id}/detail")
async def salary_detail(rec_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """工资明细详情页：订单提成明细 / 管理提成 / 考核项 / 厂家补贴 / 扣款 / 达标奖金"""
    from app.core.permissions import can_see_salary
    rec = await db.get(SalaryRecord, rec_id)
    if not rec:
        raise HTTPException(404, "工资单不存在")
    # 权限：HR 类全开；其他只能看本人工资
    if not can_see_salary(user) and user.get("employee_id") != rec.employee_id:
        raise HTTPException(403, "无权查看他人工资")

    # 订单明细
    from app.models.order import Order as _Ord
    from app.models.customer import Customer as _Cu
    order_links = (await db.execute(
        select(SalaryOrderLink).where(SalaryOrderLink.salary_record_id == rec_id)
    )).scalars().all()
    order_details = []
    manager_share_details = []
    for link in order_links:
        o = await db.get(_Ord, link.order_id)
        cust = await db.get(_Cu, o.customer_id) if o and o.customer_id else None
        brand = await db.get(Brand, link.brand_id) if link.brand_id else None
        d = {
            "order_no": o.order_no if o else link.order_id[:8],
            "customer_name": cust.name if cust else '-',
            "brand_name": brand.name if brand else '-',
            "receipt_amount": float(link.receipt_amount),
            "commission_rate": float(link.commission_rate_used),
            "kpi_coefficient": float(link.kpi_coefficient),
            "commission_amount": float(link.commission_amount),
            "salesman_name": o.salesman.name if o and o.salesman else '-',
        }
        if link.is_manager_share:
            manager_share_details.append(d)
        else:
            order_details.append(d)

    # 考核项
    assess = (await db.execute(
        select(AssessmentItem).where(
            AssessmentItem.employee_id == rec.employee_id,
            AssessmentItem.period == rec.period,
        )
    )).scalars().all()
    assessment_details = [{
        "item_name": a.item_name, "target_value": float(a.target_value),
        "actual_value": float(a.actual_value),
        "completion_rate": float(a.completion_rate),
        "item_amount": float(a.item_amount), "earned_amount": float(a.earned_amount),
    } for a in assess]

    # 厂家补贴明细（按品牌）
    ebps = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.employee_id == rec.employee_id,
            EmployeeBrandPosition.manufacturer_subsidy > 0,
        )
    )).scalars().all()
    subsidy_details = []
    for ebp in ebps:
        subsidy_details.append({
            "brand_name": ebp.brand.name if ebp.brand else '-',
            "position_name": ebp.position.name if ebp.position else ebp.position_code,
            "amount": float(ebp.manufacturer_subsidy),
        })

    # 考勤汇总
    from app.models.attendance import CheckinRecord, LeaveRequest
    from datetime import date as _d
    _y, _m = map(int, rec.period.split("-"))
    _start = _d(_y, _m, 1)
    from datetime import timedelta as _td
    _end = _d(_y+1, 1, 1) - _td(days=1) if _m == 12 else _d(_y, _m+1, 1) - _td(days=1)
    checkins = (await db.execute(
        select(CheckinRecord).where(
            CheckinRecord.employee_id == rec.employee_id,
            CheckinRecord.checkin_date.between(_start, _end),
        )
    )).scalars().all()
    late_times = sum(1 for c in checkins if c.status == "late")
    late_over30 = sum(1 for c in checkins if c.status == "late_over30")
    leaves = (await db.execute(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == rec.employee_id,
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= _end,
            LeaveRequest.end_date >= _start,
            LeaveRequest.leave_type != "overtime_off",
        )
    )).scalars().all()
    leave_days = sum(float(l.total_days or 0) for l in leaves)

    emp_name = rec.employee.name if rec.employee else '-'
    emp = rec.employee
    # 取主属品牌薪酬方案（展示模板金额）
    primary_ebp = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.employee_id == rec.employee_id,
            EmployeeBrandPosition.is_primary == True,
        )
    )).scalar_one_or_none()
    primary_scheme = None
    if primary_ebp:
        primary_scheme = (await db.execute(
            select(BrandSalaryScheme).where(
                BrandSalaryScheme.brand_id == primary_ebp.brand_id,
                BrandSalaryScheme.position_code == primary_ebp.position_code,
            )
        )).scalar_one_or_none()
    return {
        "id": rec.id,
        "employee_id": rec.employee_id,
        "employee_name": emp_name,
        "period": rec.period,
        "status": rec.status,
        "employee_info": {
            "primary_brand_name": primary_ebp.brand.name if primary_ebp and primary_ebp.brand else None,
            "primary_position_name": primary_ebp.position.name if primary_ebp and primary_ebp.position else None,
            "base_salary_fixed": float(primary_scheme.fixed_salary) if primary_scheme else 0,
            "variable_salary_max": float(primary_scheme.variable_salary_max) if primary_scheme else 0,
            "attendance_bonus_full": float(primary_scheme.attendance_bonus_full) if primary_scheme else 0,
            "social_security": float(emp.social_security or 0) if emp else 0,
            "company_social_security": float(emp.company_social_security or 0) if emp else 0,
        },
        "income": {
            "fixed_salary": float(rec.fixed_salary),
            "variable_salary_total": float(rec.variable_salary_total),
            "commission_total": float(rec.commission_total),
            "manager_share_total": float(rec.manager_share_total),
            "attendance_bonus": float(rec.attendance_bonus),
            "bonus_other": float(rec.bonus_other),
            "manufacturer_subsidy_total": float(rec.manufacturer_subsidy_total),
        },
        "deduction": {
            "late_deduction": float(rec.late_deduction),
            "absence_deduction": float(rec.absence_deduction),
            "fine_deduction": float(rec.fine_deduction),
            "social_security": float(rec.social_security),
        },
        "total_pay": float(rec.total_pay),
        "actual_pay": float(rec.actual_pay),
        "attendance_summary": {
            "late_times": late_times, "late_over30_times": late_over30,
            "leave_days": leave_days,
        },
        "order_details": order_details,
        "manager_share_details": manager_share_details,
        "assessment_details": assessment_details,
        "subsidy_details": subsidy_details,
        "notes": rec.notes,
        # 流程信息
        "submitted_at": str(rec.submitted_at) if rec.submitted_at else None,
        "approved_at": str(rec.approved_at) if rec.approved_at else None,
        "reject_reason": rec.reject_reason,
        "paid_at": str(rec.paid_at) if rec.paid_at else None,
        "payment_voucher_urls": rec.payment_voucher_urls or [],
    }
