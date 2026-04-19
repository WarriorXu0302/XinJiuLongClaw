"""
HR API routes — CRUD for employees, KPIs, and commissions.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import date, datetime
from decimal import Decimal

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.user import Commission, Employee, EmployeeBrand, KPI

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Employee schemas
# ═══════════════════════════════════════════════════════════════════


class EmployeeCreate(BaseModel):
    employee_no: str
    name: str
    position: Optional[str] = None
    phone: Optional[str] = None
    open_id: Optional[str] = None
    hire_date: Optional[date] = None
    status: str = "active"
    social_security: Optional[float] = 0.0
    company_social_security: Optional[float] = 0.0
    expected_manufacturer_subsidy: Optional[float] = 0.0


class EmployeeUpdate(BaseModel):
    employee_no: Optional[str] = None
    name: Optional[str] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    open_id: Optional[str] = None
    hire_date: Optional[date] = None
    leave_date: Optional[date] = None
    status: Optional[str] = None
    social_security: Optional[float] = None
    company_social_security: Optional[float] = None
    expected_manufacturer_subsidy: Optional[float] = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_no: str
    name: str
    position: Optional[str] = None
    phone: Optional[str] = None
    open_id: Optional[str] = None
    hire_date: Optional[date] = None
    leave_date: Optional[date] = None
    status: str = "active"
    social_security: Optional[float] = None
    company_social_security: Optional[float] = None
    expected_manufacturer_subsidy: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════
# Employee CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(body: EmployeeCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = Employee(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("/employees", response_model=list[EmployeeResponse])
async def list_employees(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Employee)
    if brand_id:
        stmt = stmt.join(EmployeeBrand, Employee.id == EmployeeBrand.employee_id).where(EmployeeBrand.brand_id == brand_id)
    if status:
        stmt = stmt.where(Employee.status == status)
    stmt = stmt.order_by(Employee.employee_no).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/employees/{emp_id}", response_model=EmployeeResponse)
async def get_employee(emp_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Employee, emp_id)
    if obj is None:
        raise HTTPException(404, "Employee not found")
    return obj


@router.put("/employees/{emp_id}", response_model=EmployeeResponse)
async def update_employee(
    emp_id: str, body: EmployeeUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(Employee, emp_id)
    if obj is None:
        raise HTTPException(404, "Employee not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/employees/{emp_id}", status_code=204)
async def delete_employee(emp_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Employee, emp_id)
    if obj is None:
        raise HTTPException(404, "Employee not found")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# KPI schemas
# ═══════════════════════════════════════════════════════════════════


class KPICreate(BaseModel):
    employee_id: str
    period_type: str
    period_value: str
    kpi_type: str
    target_value: Decimal = Decimal("0.00")
    actual_value: Decimal = Decimal("0.00")
    score: Optional[Decimal] = None
    notes: Optional[str] = None


class KPIUpdate(BaseModel):
    employee_id: Optional[str] = None
    period_type: Optional[str] = None
    period_value: Optional[str] = None
    kpi_type: Optional[str] = None
    target_value: Optional[Decimal] = None
    actual_value: Optional[Decimal] = None
    score: Optional[Decimal] = None
    notes: Optional[str] = None


class KPIResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    period_type: str
    period_value: str
    kpi_type: str
    target_value: Decimal
    actual_value: Decimal
    score: Optional[Decimal] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════
# Commission schemas
# ═══════════════════════════════════════════════════════════════════


class CommissionCreate(BaseModel):
    employee_id: str
    order_id: Optional[str] = None
    commission_amount: Decimal
    status: str = "pending"
    notes: Optional[str] = None


class CommissionUpdate(BaseModel):
    employee_id: Optional[str] = None
    order_id: Optional[str] = None
    commission_amount: Optional[Decimal] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class CommissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    order_id: Optional[str] = None
    commission_amount: Decimal
    status: str
    settled_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════
# KPI CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/kpis", response_model=KPIResponse, status_code=201)
async def create_kpi(body: KPICreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = KPI(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("/kpis", response_model=list[KPIResponse])
async def list_kpis(
    user: CurrentUser,
    employee_id: str | None = Query(None),
    brand_id: str | None = Query(None),
    period_type: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(KPI)
    if employee_id:
        stmt = stmt.where(KPI.employee_id == employee_id)
    if period_type:
        stmt = stmt.where(KPI.period_type == period_type)
    if brand_id:
        stmt = stmt.where(KPI.brand_id == brand_id)
    stmt = stmt.order_by(KPI.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/kpis/{kpi_id}", response_model=KPIResponse)
async def get_kpi(kpi_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(KPI, kpi_id)
    if obj is None:
        raise HTTPException(404, "KPI not found")
    return obj


@router.put("/kpis/{kpi_id}", response_model=KPIResponse)
async def update_kpi(
    kpi_id: str, body: KPIUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(KPI, kpi_id)
    if obj is None:
        raise HTTPException(404, "KPI not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/kpis/{kpi_id}", status_code=204)
async def delete_kpi(kpi_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(KPI, kpi_id)
    if obj is None:
        raise HTTPException(404, "KPI not found")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Commission CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/commissions", response_model=CommissionResponse, status_code=201)
async def create_commission(body: CommissionCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = Commission(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("/commissions", response_model=list[CommissionResponse])
async def list_commissions(
    user: CurrentUser,
    employee_id: str | None = Query(None),
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    stmt = select(Commission)
    if employee_id:
        stmt = stmt.where(Commission.employee_id == employee_id)
    if status:
        stmt = stmt.where(Commission.status == status)
    if brand_id:
        stmt = stmt.where(Commission.brand_id == brand_id)
    # 业务员只看自己的佣金
    if is_salesman(user) and user.get("employee_id"):
        stmt = stmt.where(Commission.employee_id == user["employee_id"])
    stmt = stmt.order_by(Commission.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/commissions/{commission_id}", response_model=CommissionResponse)
async def get_commission(commission_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Commission, commission_id)
    if obj is None:
        raise HTTPException(404, "Commission not found")
    return obj


@router.put("/commissions/{commission_id}", response_model=CommissionResponse)
async def update_commission(
    commission_id: str, body: CommissionUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(Commission, commission_id)
    if obj is None:
        raise HTTPException(404, "Commission not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/commissions/{commission_id}", status_code=204)
async def delete_commission(commission_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Commission, commission_id)
    if obj is None:
        raise HTTPException(404, "Commission not found")
    await db.delete(obj)
    await db.flush()


@router.post("/commissions/{commission_id}/settle", response_model=CommissionResponse)
async def settle_commission(commission_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Commission, commission_id)
    if obj is None:
        raise HTTPException(404, "Commission not found")
    obj.status = "settled"
    obj.settled_at = datetime.now()
    await db.flush()
    return obj


# ═══════════════════════════════════════════════════════════════════
# Employee Brand Binding
# ═══════════════════════════════════════════════════════════════════


@router.get("/employees/{emp_id}/brands")
async def get_employee_brands(emp_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(EmployeeBrand).where(EmployeeBrand.employee_id == emp_id)
    )).scalars().all()
    return [{"id": r.id, "brand_id": r.brand_id} for r in rows]


class BindBrandBody(BaseModel):
    brand_id: str


@router.post("/employees/{emp_id}/brands", status_code=201)
async def bind_employee_brand(emp_id: str, body: BindBrandBody, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(
        select(EmployeeBrand).where(EmployeeBrand.employee_id == emp_id, EmployeeBrand.brand_id == body.brand_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该员工已绑定此品牌")
    obj = EmployeeBrand(id=str(uuid.uuid4()), employee_id=emp_id, brand_id=body.brand_id)
    db.add(obj)
    await db.flush()
    return {"id": obj.id, "employee_id": emp_id, "brand_id": body.brand_id}


@router.delete("/employees/{emp_id}/brands/{brand_id}", status_code=204)
async def unbind_employee_brand(emp_id: str, brand_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = (await db.execute(
        select(EmployeeBrand).where(EmployeeBrand.employee_id == emp_id, EmployeeBrand.brand_id == brand_id)
    )).scalar_one_or_none()
    if obj:
        await db.delete(obj)
        await db.flush()
