"""
/api/mall/workspace/attendance/*

业务员打卡 / 拜访 — 直接写 ERP `checkin_records` / `customer_visits` 表，
employee_id 从 mall_user.linked_employee_id 取。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.attendance import AttendanceRule, CheckinRecord, CustomerVisit
from app.services.mall import auth_service

router = APIRouter()


async def _require_linked_salesman(current, db):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="业务员未绑定员工记录，无法打卡")
    # 校验 employee 当前处于在职状态（避免离职员工打卡）
    from app.models.user import Employee
    emp = await db.get(Employee, user.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="绑定的员工记录不存在")
    status = getattr(emp, "status", None)
    if status and status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"员工状态 {status}，无法进行考勤操作",
        )
    return user


# =============================================================================
# 上/下班打卡
# =============================================================================

class _CheckinBody(BaseModel):
    checkin_type: str
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    address: Optional[str] = None
    selfie_url: Optional[str] = None


@router.post("/checkin")
async def checkin(
    body: _CheckinBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    if body.checkin_type not in ("work_in", "work_out"):
        raise HTTPException(status_code=400, detail="checkin_type 非法")

    # checkin_date 按业务时区（北京），避免凌晨打卡被记到前一天
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    exists = (await db.execute(
        select(CheckinRecord)
        .where(CheckinRecord.employee_id == user.linked_employee_id)
        .where(CheckinRecord.checkin_date == today)
        .where(CheckinRecord.checkin_type == body.checkin_type)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="今日已打过卡")

    now = datetime.now(timezone.utc)
    status = "normal"
    late_minutes = 0
    if body.checkin_type == "work_in":
        bj = now.astimezone(ZoneInfo("Asia/Shanghai"))
        threshold = bj.replace(hour=9, minute=10, second=0, microsecond=0)
        if bj > threshold:
            status = "late"
            late_minutes = int((bj - threshold).total_seconds() / 60)

    record = CheckinRecord(
        id=str(uuid.uuid4()),
        employee_id=user.linked_employee_id,
        checkin_date=today,
        checkin_type=body.checkin_type,
        checkin_time=now,
        latitude=body.latitude,
        longitude=body.longitude,
        photo_url=body.selfie_url,
        status=status,
        late_minutes=late_minutes,
    )
    db.add(record)
    await db.flush()
    return {
        "id": record.id,
        "checkin_time": record.checkin_time,
        "status": record.status,
        "late_minutes": record.late_minutes,
    }


@router.get("/today")
async def today_status(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    rows = (await db.execute(
        select(CheckinRecord)
        .where(CheckinRecord.employee_id == user.linked_employee_id)
        .where(CheckinRecord.checkin_date == today)
    )).scalars().all()
    out = {"work_in": None, "work_out": None}
    for r in rows:
        if r.checkin_type in ("work_in", "work_out"):
            out[r.checkin_type] = {
                "checkin_time": r.checkin_time,
                "status": r.status,
                "late_minutes": r.late_minutes,
            }
    return out


# =============================================================================
# 客户拜访
# =============================================================================

class _VisitEnterBody(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    address: Optional[str] = None
    enter_photo_url: Optional[str] = None


@router.get("/visits/active")
async def active_visit(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    visit = (await db.execute(
        select(CustomerVisit)
        .where(CustomerVisit.employee_id == user.linked_employee_id)
        .where(CustomerVisit.enter_time.is_not(None))
        .where(CustomerVisit.leave_time.is_(None))
        .order_by(desc(CustomerVisit.enter_time))
        .limit(1)
    )).scalar_one_or_none()
    if visit is None:
        return None
    return {
        "visit_id": visit.id,
        "customer_id": visit.customer_id,
        "customer_name": visit.customer_name,
        "enter_time": visit.enter_time,
    }


@router.post("/visits/enter")
async def enter_visit(
    body: _VisitEnterBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    existing = (await db.execute(
        select(CustomerVisit)
        .where(CustomerVisit.employee_id == user.linked_employee_id)
        .where(CustomerVisit.enter_time.is_not(None))
        .where(CustomerVisit.leave_time.is_(None))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="有进行中的拜访，请先离店")

    now = datetime.now(timezone.utc)
    visit = CustomerVisit(
        id=str(uuid.uuid4()),
        employee_id=user.linked_employee_id,
        customer_id=body.customer_id,
        customer_name=body.customer_name,
        visit_date=now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        enter_time=now,
        enter_latitude=body.latitude,
        enter_longitude=body.longitude,
        enter_photo_url=body.enter_photo_url,
        is_valid=False,
    )
    db.add(visit)
    await db.flush()
    return {"visit_id": visit.id, "enter_time": visit.enter_time}


class _VisitLeaveBody(BaseModel):
    visit_id: str
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    address: Optional[str] = None
    leave_photo_url: Optional[str] = None


@router.post("/visits/leave")
async def leave_visit(
    body: _VisitLeaveBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    visit = (await db.execute(
        select(CustomerVisit).where(CustomerVisit.id == body.visit_id)
    )).scalar_one_or_none()
    if visit is None or visit.employee_id != user.linked_employee_id:
        raise HTTPException(status_code=404, detail="拜访记录不存在")
    if visit.leave_time is not None:
        raise HTTPException(status_code=409, detail="该拜访已离店")
    if visit.enter_time is None:
        raise HTTPException(status_code=400, detail="拜访记录缺少进店时间")

    now = datetime.now(timezone.utc)
    visit.leave_time = now
    visit.leave_latitude = body.latitude
    visit.leave_longitude = body.longitude
    visit.leave_photo_url = body.leave_photo_url
    duration = int((now - visit.enter_time).total_seconds() / 60)
    visit.duration_minutes = duration

    min_visit = 30
    rule = (await db.execute(select(AttendanceRule).limit(1))).scalar_one_or_none()
    if rule and getattr(rule, "min_visit_minutes", None):
        min_visit = rule.min_visit_minutes
    visit.is_valid = duration >= min_visit

    await db.flush()
    return {
        "visit_id": visit.id,
        "duration_minutes": duration,
        "is_valid": visit.is_valid,
    }


@router.get("/visits")
async def list_visits(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    rows = (await db.execute(
        select(CustomerVisit)
        .where(CustomerVisit.employee_id == user.linked_employee_id)
        .order_by(desc(CustomerVisit.enter_time))
        .limit(50)
    )).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "visit_date": r.visit_date,
                "enter_time": r.enter_time,
                "leave_time": r.leave_time,
                "duration_minutes": r.duration_minutes,
                "is_valid": r.is_valid,
            }
            for r in rows
        ]
    }
