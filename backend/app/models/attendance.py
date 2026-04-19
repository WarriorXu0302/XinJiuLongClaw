"""
考勤系统模型：
  - AttendanceRule：打卡规则（全局默认或按员工）
  - CheckinRecord：上下班打卡记录
  - CustomerVisit：客户拜访（进/出两条打卡组成 1 次有效）
  - LeaveRequest：请假/调休申请
"""
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import Employee
    from app.models.customer import Customer


class AttendanceRule(Base):
    """打卡规则（默认一条 global 规则，可按员工覆盖）"""
    __tablename__ = "attendance_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), default="默认规则")
    # 工作时间
    work_start_time: Mapped[time] = mapped_column(Time, default=time(9, 0))
    work_end_time: Mapped[time] = mapped_column(Time, default=time(18, 0))
    # 办公地点围栏
    office_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    office_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    office_radius_m: Mapped[int] = mapped_column(Integer, default=200)
    # 迟到/早退规则
    late_tolerance_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 宽限分钟
    late_deduction_per_time: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("10.00"))  # 每次迟到扣款
    late_over30_deduction: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("50.00"))  # >30min 扣款
    absence_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("3.00"))  # 旷工扣款 = 日薪 × 倍数
    # 客户拜访规则
    min_visit_minutes: Mapped[int] = mapped_column(Integer, default=30)  # 进出间隔
    daily_visit_target: Mapped[int] = mapped_column(Integer, default=6)  # 每日目标
    # 适用范围
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True,
    )  # null = 全局默认
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")


class CheckinRecord(Base):
    """上下班打卡"""
    __tablename__ = "checkin_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "checkin_date", "checkin_type", name="uq_checkin_daily"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True,
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    checkin_type: Mapped[str] = mapped_column(String(20), nullable=False)  # work_in / work_out
    checkin_time: Mapped[datetime] = mapped_column(nullable=False)
    # 位置 + 自拍
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # 状态
    status: Mapped[str] = mapped_column(String(20), default="normal")  # normal/late/late_over30/absence
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    employee: Mapped["Employee"] = relationship("Employee", lazy="selectin")


class CustomerVisit(Base):
    """客户拜访打卡（进店/出店两条记录组成一次有效拜访）"""
    __tablename__ = "customer_visits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True, index=True,
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 也可临时手填
    visit_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 进店
    enter_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    enter_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enter_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enter_photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # 出店
    leave_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    leave_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leave_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leave_photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # 计算字段
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)  # 时长达标才算有效
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    employee: Mapped["Employee"] = relationship("Employee", lazy="selectin")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", lazy="selectin")


class LeaveRequest(Base):
    """请假/调休"""
    __tablename__ = "leave_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True,
    )
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)  # personal / sick / annual / overtime_off
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    half_day_start: Mapped[bool] = mapped_column(Boolean, default=False)  # 开始是半天
    half_day_end: Mapped[bool] = mapped_column(Boolean, default=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=Decimal("0"))  # 总天数（半天=0.5）
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_urls: Mapped[Optional[list]] = mapped_column(String(2000), nullable=True)  # 病假附件
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/approved/rejected
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("employees.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    employee: Mapped["Employee"] = relationship("Employee", foreign_keys=[employee_id], lazy="selectin")
