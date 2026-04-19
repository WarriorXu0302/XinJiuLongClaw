"""
考勤系统 API — 打卡、客户拜访、请假、规则。
"""
import math
import uuid
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.attendance import AttendanceRule, CheckinRecord, CustomerVisit, LeaveRequest
from app.models.user import Employee
from app.models.customer import Customer
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"


# ═══════════════════════════════════════════════════════════════════
# 打卡规则 Rules
# ═══════════════════════════════════════════════════════════════════

class RuleCreate(BaseModel):
    name: str = "默认规则"
    work_start_time: str = "09:00"
    work_end_time: str = "18:00"
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None
    office_radius_m: int = 200
    late_tolerance_minutes: int = 0
    late_deduction_per_time: float = 10.0
    late_over30_deduction: float = 50.0
    absence_multiplier: float = 3.0
    min_visit_minutes: int = 30
    daily_visit_target: int = 6
    employee_id: Optional[str] = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    work_start_time: time
    work_end_time: time
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None
    office_radius_m: int
    late_tolerance_minutes: int
    late_deduction_per_time: float
    late_over30_deduction: float
    absence_multiplier: float
    min_visit_minutes: int
    daily_visit_target: int
    employee_id: Optional[str] = None
    is_active: bool


async def _get_rule_for_employee(db: AsyncSession, emp_id: str) -> AttendanceRule:
    """取员工适用的规则：优先个人规则，否则全局默认"""
    r = (await db.execute(
        select(AttendanceRule).where(
            AttendanceRule.employee_id == emp_id, AttendanceRule.is_active == True,
        ).limit(1)
    )).scalar_one_or_none()
    if r:
        return r
    r = (await db.execute(
        select(AttendanceRule).where(
            AttendanceRule.employee_id.is_(None), AttendanceRule.is_active == True,
        ).limit(1)
    )).scalar_one_or_none()
    if r:
        return r
    # 无规则时返回默认值对象（不落库）
    default = AttendanceRule(id=str(uuid.uuid4()), name="默认")
    return default


@router.get("/rules", response_model=list[RuleResponse])
async def list_rules(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(AttendanceRule).order_by(AttendanceRule.employee_id.nulls_first())
    )).scalars().all()
    return rows


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def upsert_rule(body: RuleCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    # 同员工/全局只能一条
    existing = (await db.execute(
        select(AttendanceRule).where(
            AttendanceRule.employee_id.is_(body.employee_id) if body.employee_id is None
            else AttendanceRule.employee_id == body.employee_id,
        )
    )).scalar_one_or_none()
    data = body.model_dump()
    # parse time
    data['work_start_time'] = datetime.strptime(body.work_start_time, "%H:%M").time()
    data['work_end_time'] = datetime.strptime(body.work_end_time, "%H:%M").time()
    for k in ('late_deduction_per_time', 'late_over30_deduction', 'absence_multiplier'):
        data[k] = Decimal(str(data[k]))
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        obj = existing
    else:
        obj = AttendanceRule(id=str(uuid.uuid4()), **data)
        db.add(obj)
    await db.flush()
    await log_audit(db, action="upsert_attendance_rule", entity_type="AttendanceRule",
                    entity_id=obj.id, user=user)
    return obj


# ═══════════════════════════════════════════════════════════════════
# 上下班打卡
# ═══════════════════════════════════════════════════════════════════

class CheckinRequest(BaseModel):
    checkin_type: str  # work_in / work_out
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """两点距离，单位米"""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


class CheckinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    checkin_date: date
    checkin_type: str
    checkin_time: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo_url: Optional[str] = None
    status: str
    late_minutes: int
    notes: Optional[str] = None


@router.post("/checkin", response_model=CheckinResponse, status_code=201)
async def create_checkin(body: CheckinRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """员工打卡（自动判定迟到/旷工）"""
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "当前账号未绑定员工")
    if body.checkin_type not in ("work_in", "work_out"):
        raise HTTPException(400, "checkin_type 必须是 work_in 或 work_out")
    if not body.latitude or not body.longitude:
        raise HTTPException(400, "必须提供 GPS 位置")
    if not body.photo_url:
        raise HTTPException(400, "必须拍照打卡")

    rule = await _get_rule_for_employee(db, emp_id)
    now = datetime.now(timezone.utc)
    today = now.date()

    # 幂等：当日已打过同类型卡 → 报错
    existing = (await db.execute(
        select(CheckinRecord).where(
            CheckinRecord.employee_id == emp_id,
            CheckinRecord.checkin_date == today,
            CheckinRecord.checkin_type == body.checkin_type,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"今日已打过{'上班' if body.checkin_type=='work_in' else '下班'}卡")

    # 距离检查
    if rule.office_latitude and rule.office_longitude:
        dist = _haversine(body.latitude, body.longitude, rule.office_latitude, rule.office_longitude)
        if dist > rule.office_radius_m:
            raise HTTPException(400, f"距离办公地点 {dist:.0f} 米，超出 {rule.office_radius_m} 米围栏")

    # 迟到判定（仅上班卡）
    status = "normal"
    late_minutes = 0
    if body.checkin_type == "work_in":
        work_start = datetime.combine(today, rule.work_start_time).replace(tzinfo=timezone.utc)
        delta = (now - work_start).total_seconds() / 60
        if delta > rule.late_tolerance_minutes:
            late_minutes = int(delta - rule.late_tolerance_minutes)
            if late_minutes > 30:
                status = "late_over30"
            else:
                status = "late"

    rec = CheckinRecord(
        id=str(uuid.uuid4()),
        employee_id=emp_id,
        checkin_date=today,
        checkin_type=body.checkin_type,
        checkin_time=now,
        latitude=body.latitude,
        longitude=body.longitude,
        photo_url=body.photo_url,
        status=status,
        late_minutes=late_minutes,
        notes=body.notes,
    )
    db.add(rec)
    await db.flush()
    await db.refresh(rec, ["employee"])
    r = CheckinResponse.model_validate(rec).model_dump()
    r["employee_name"] = rec.employee.name if rec.employee else None
    return r


@router.get("/checkin", response_model=list[CheckinResponse])
async def list_checkin(
    user: CurrentUser,
    employee_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    # 业务员强制只看自己
    if is_salesman(user):
        employee_id = user.get("employee_id")
    stmt = select(CheckinRecord)
    if employee_id:
        stmt = stmt.where(CheckinRecord.employee_id == employee_id)
    if start_date:
        stmt = stmt.where(CheckinRecord.checkin_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
    if end_date:
        stmt = stmt.where(CheckinRecord.checkin_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
    stmt = stmt.order_by(CheckinRecord.checkin_date.desc(), CheckinRecord.checkin_time.desc()).limit(500)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {**CheckinResponse.model_validate(r).model_dump(),
         "employee_name": r.employee.name if r.employee else None}
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════
# 客户拜访打卡
# ═══════════════════════════════════════════════════════════════════

class VisitEnterRequest(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    latitude: float
    longitude: float
    photo_url: str
    notes: Optional[str] = None


class VisitLeaveRequest(BaseModel):
    visit_id: str
    latitude: float
    longitude: float
    photo_url: str


class VisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    visit_date: date
    enter_time: Optional[datetime] = None
    leave_time: Optional[datetime] = None
    enter_latitude: Optional[float] = None
    enter_longitude: Optional[float] = None
    leave_latitude: Optional[float] = None
    leave_longitude: Optional[float] = None
    enter_photo_url: Optional[str] = None
    leave_photo_url: Optional[str] = None
    duration_minutes: Optional[int] = None
    is_valid: bool
    notes: Optional[str] = None


@router.post("/visits/enter", response_model=VisitResponse, status_code=201)
async def visit_enter(body: VisitEnterRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """进店打卡"""
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "未绑定员工")
    if not body.photo_url:
        raise HTTPException(400, "必须拍照打卡")

    # 自动补 customer_name
    cust_name = body.customer_name
    if body.customer_id and not cust_name:
        c = await db.get(Customer, body.customer_id)
        cust_name = c.name if c else None

    now = datetime.now(timezone.utc)
    rec = CustomerVisit(
        id=str(uuid.uuid4()),
        employee_id=emp_id,
        customer_id=body.customer_id,
        customer_name=cust_name,
        visit_date=now.date(),
        enter_time=now,
        enter_latitude=body.latitude,
        enter_longitude=body.longitude,
        enter_photo_url=body.photo_url,
        notes=body.notes,
    )
    db.add(rec)
    await db.flush()
    await db.refresh(rec, ["employee", "customer"])
    return {**VisitResponse.model_validate(rec).model_dump(),
            "employee_name": rec.employee.name if rec.employee else None}


@router.post("/visits/leave", response_model=VisitResponse)
async def visit_leave(body: VisitLeaveRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """出店打卡"""
    emp_id = user.get("employee_id")
    v = await db.get(CustomerVisit, body.visit_id)
    if not v:
        raise HTTPException(404, "拜访记录不存在")
    if v.employee_id != emp_id:
        raise HTTPException(403, "只能完成自己的拜访打卡")
    if v.leave_time:
        raise HTTPException(400, "已完成出店打卡")
    now = datetime.now(timezone.utc)
    v.leave_time = now
    v.leave_latitude = body.latitude
    v.leave_longitude = body.longitude
    v.leave_photo_url = body.photo_url
    # 算时长 + 有效性
    rule = await _get_rule_for_employee(db, emp_id)
    duration = int((now - v.enter_time).total_seconds() / 60) if v.enter_time else 0
    v.duration_minutes = duration
    v.is_valid = duration >= rule.min_visit_minutes
    await db.flush()
    await db.refresh(v, ["employee", "customer"])
    return {**VisitResponse.model_validate(v).model_dump(),
            "employee_name": v.employee.name if v.employee else None}


@router.get("/visits", response_model=list[VisitResponse])
async def list_visits(
    user: CurrentUser,
    employee_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    if is_salesman(user):
        employee_id = user.get("employee_id")
    stmt = select(CustomerVisit)
    if employee_id:
        stmt = stmt.where(CustomerVisit.employee_id == employee_id)
    if start_date:
        stmt = stmt.where(CustomerVisit.visit_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
    if end_date:
        stmt = stmt.where(CustomerVisit.visit_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
    stmt = stmt.order_by(CustomerVisit.enter_time.desc()).limit(500)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {**VisitResponse.model_validate(r).model_dump(),
         "employee_name": r.employee.name if r.employee else None}
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════
# 请假 LeaveRequest
# ═══════════════════════════════════════════════════════════════════

class LeaveCreate(BaseModel):
    leave_type: str  # personal / sick / annual / overtime_off
    start_date: date
    end_date: date
    half_day_start: bool = False
    half_day_end: bool = False
    reason: str
    attachment_urls: Optional[list[str]] = None


class LeaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    request_no: str
    employee_id: str
    employee_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    half_day_start: bool
    half_day_end: bool
    total_days: float
    reason: str
    status: str
    approved_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    created_at: datetime


def _calc_leave_days(start: date, end: date, half_start: bool, half_end: bool) -> Decimal:
    # 工作日数（不算周日）
    days = 0
    d = start
    while d <= end:
        if d.weekday() != 6:  # 周一=0 ... 周日=6
            days += 1
        d += timedelta(days=1)
    total = Decimal(days)
    if half_start:
        total -= Decimal("0.5")
    if half_end and start != end:
        total -= Decimal("0.5")
    return max(total, Decimal("0.5"))


@router.post("/leave-requests", response_model=LeaveResponse, status_code=201)
async def create_leave(body: LeaveCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "未绑定员工")
    if body.end_date < body.start_date:
        raise HTTPException(400, "结束日期不能早于开始日期")
    total = _calc_leave_days(body.start_date, body.end_date, body.half_day_start, body.half_day_end)
    rec = LeaveRequest(
        id=str(uuid.uuid4()),
        request_no=_gen_no("LV"),
        employee_id=emp_id,
        leave_type=body.leave_type,
        start_date=body.start_date,
        end_date=body.end_date,
        half_day_start=body.half_day_start,
        half_day_end=body.half_day_end,
        total_days=total,
        reason=body.reason,
        status="pending",
    )
    db.add(rec)
    await db.flush()
    await db.refresh(rec, ["employee"])
    await log_audit(db, action="create_leave_request", entity_type="LeaveRequest",
                    entity_id=rec.id, user=user)
    return {**LeaveResponse.model_validate(rec).model_dump(),
            "employee_name": rec.employee.name if rec.employee else None}


@router.get("/leave-requests", response_model=list[LeaveResponse])
async def list_leaves(
    user: CurrentUser,
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    if is_salesman(user):
        employee_id = user.get("employee_id")
    stmt = select(LeaveRequest)
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    stmt = stmt.order_by(LeaveRequest.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {**LeaveResponse.model_validate(r).model_dump(),
         "employee_name": r.employee.name if r.employee else None}
        for r in rows
    ]


class LeaveApprove(BaseModel):
    approved: bool
    reject_reason: Optional[str] = None


@router.post("/leave-requests/{req_id}/approve", response_model=LeaveResponse)
async def approve_leave(req_id: str, body: LeaveApprove, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rec = await db.get(LeaveRequest, req_id)
    if not rec:
        raise HTTPException(404, "请假申请不存在")
    if rec.status != "pending":
        raise HTTPException(400, f"申请状态为 {rec.status}")
    rec.status = "approved" if body.approved else "rejected"
    rec.approved_by = user.get("employee_id")
    rec.approved_at = datetime.now(timezone.utc)
    rec.reject_reason = body.reject_reason
    await db.flush()
    await db.refresh(rec, ["employee"])
    await log_audit(db, action=f"{'approve' if body.approved else 'reject'}_leave_request",
                    entity_type="LeaveRequest", entity_id=rec.id, user=user)
    return {**LeaveResponse.model_validate(rec).model_dump(),
            "employee_name": rec.employee.name if rec.employee else None}


# ═══════════════════════════════════════════════════════════════════
# 月度汇总（供工资单使用）
# ═══════════════════════════════════════════════════════════════════

@router.get("/monthly-summary")
async def monthly_summary(
    user: CurrentUser,
    period: str = Query(..., description="YYYY-MM"),
    employee_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """月度考勤汇总：迟到次数/旷工天数/有效拜访天数/请假天数"""
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    if m == 12:
        end = date(y+1, 1, 1) - timedelta(days=1)
    else:
        end = date(y, m+1, 1) - timedelta(days=1)

    emp_stmt = select(Employee).where(Employee.status == 'active')
    if employee_id:
        emp_stmt = emp_stmt.where(Employee.id == employee_id)
    emps = (await db.execute(emp_stmt)).scalars().all()

    result = []
    for emp in emps:
        checkins = (await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.employee_id == emp.id,
                CheckinRecord.checkin_date.between(start, end),
            )
        )).scalars().all()
        late_times = sum(1 for c in checkins if c.status == "late")
        late_over30 = sum(1 for c in checkins if c.status == "late_over30")

        # 请假天数（已通过）
        leaves = (await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
        )).scalars().all()
        leave_days = sum(float(l.total_days) for l in leaves)

        # 有效拜访天数
        visits = (await db.execute(
            select(CustomerVisit).where(
                CustomerVisit.employee_id == emp.id,
                CustomerVisit.visit_date.between(start, end),
                CustomerVisit.is_valid == True,
            )
        )).scalars().all()
        valid_visits = len(visits)

        rule = await _get_rule_for_employee(db, emp.id)
        late_deduction = (Decimal(late_times) * rule.late_deduction_per_time
                          + Decimal(late_over30) * rule.late_over30_deduction)
        # 简化：全勤判定 = 无迟到 + 无旷工 + 无请假（调休除外）
        non_overtime_leaves = [l for l in leaves if l.leave_type != "overtime_off"]
        is_full_attendance = (late_times == 0 and late_over30 == 0
                              and len(non_overtime_leaves) == 0)

        result.append({
            "employee_id": emp.id,
            "employee_name": emp.name,
            "late_times": late_times,
            "late_over30_times": late_over30,
            "late_deduction": float(late_deduction),
            "leave_days": leave_days,
            "valid_visits": valid_visits,
            "is_full_attendance": is_full_attendance,
        })
    return result
