"""
Payroll 相关模型：岗位字典、薪酬方案、员工-品牌-岗位关系、考核项、工资记录、厂家补贴。

核心设计：
  - 底薪（固定+浮动）挂在 Employee，与品牌无关
  - 销售提成 + 厂家补贴挂在 EmployeeBrandPosition（员工×品牌）
  - 工资按月生成 SalaryRecord，每张工资单关联多条订单（SalaryOrderLink）
  - 厂家补贴发薪时生成 ManufacturerSalarySubsidy 应收记录，厂家报账后 reimbursed
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import Employee
    from app.models.product import Brand, Account
    from app.models.order import Order


class Position(Base):
    """岗位字典（全公司通用）"""
    __tablename__ = "positions"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BrandSalaryScheme(Base):
    """品牌×岗位 的默认薪酬方案（提成率、管理提成率、全勤奖）"""
    __tablename__ = "brand_salary_schemes"
    __table_args__ = (
        UniqueConstraint("brand_id", "position_code", name="uq_brand_position_scheme"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=True,
    )  # null = 公司通用（比如财务、仓管）
    position_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("positions.code"), nullable=False,
    )
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("0.0000"),
    )  # 0.01 = 1%
    manager_share_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("0.0000"),
    )  # 业务经理拿下属的提成率，默认 0.003 = 0.3%
    # 底薪模板（该品牌该岗位的标准底薪结构）
    fixed_salary: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("3000.00"),
    )
    variable_salary_max: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("1500.00"),
    )  # 考核满分对应的浮动底薪上限
    attendance_bonus_full: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("200.00"),
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(__import__("datetime").timezone.utc)
    )

    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    position: Mapped["Position"] = relationship("Position", lazy="selectin")


class EmployeeBrandPosition(Base):
    """员工-品牌-岗位 关系（一个员工可兼职多品牌）"""
    __tablename__ = "employee_brand_positions"
    __table_args__ = (
        UniqueConstraint("employee_id", "brand_id", name="uq_employee_brand_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False,
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False,
    )
    position_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("positions.code"), nullable=False,
    )
    # 个性化提成率（null=用品牌默认）
    commission_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 4), nullable=True,
    )
    # 厂家补贴月额
    manufacturer_subsidy: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"),
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # 主属品牌
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    employee: Mapped["Employee"] = relationship("Employee", lazy="selectin")
    brand: Mapped["Brand"] = relationship("Brand", lazy="selectin")
    position: Mapped["Position"] = relationship("Position", lazy="selectin")


class AssessmentItem(Base):
    """月度考核项（每员工每月多条，可动态增加）"""
    __tablename__ = "assessment_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # "2026-04"
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True,
    )  # 可按品牌维度
    item_code: Mapped[str] = mapped_column(String(30), nullable=False)  # kpi_revenue / kpi_customers / ...
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    target_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    actual_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    completion_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0000"))  # 1.0 = 100%
    earned_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SalaryRecord(Base):
    """月度工资记录"""
    __tablename__ = "salary_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "period", name="uq_salary_employee_period"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True,
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # "2026-04"

    # 底薪
    fixed_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    variable_salary_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    # 提成
    commission_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    manager_share_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    # 奖金
    attendance_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    bonus_other: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    # 厂家补贴（总额，明细在 ManufacturerSalarySubsidy）
    manufacturer_subsidy_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    # 扣款
    late_deduction: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    absence_deduction: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    fine_deduction: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    social_security: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    # 合计
    total_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    actual_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    # 状态
    # 状态: draft / pending_approval / approved / rejected / paid
    status: Mapped[str] = mapped_column(String(20), default="draft")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    submitted_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    paid_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("employees.id"), nullable=True)
    # 发放凭证（多张图）
    payment_voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 工作天数信息（用于按天折算）
    work_days_month: Mapped[int] = mapped_column(Integer, default=26)
    work_days_actual: Mapped[int] = mapped_column(Integer, default=26)

    # KPI 规则快照：生成/重算时冻结当时用的规则集合（按品牌分组）
    # 结构：{ brand_id: [{min_rate, max_rate, mode, fixed_value}, ...] }
    # 有争议时可直接翻工资单看当时用的规则，无需依赖 kpi_coefficient_rules 的当前状态
    kpi_rule_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(__import__("datetime").timezone.utc)
    )

    employee: Mapped["Employee"] = relationship("Employee", foreign_keys=[employee_id], lazy="selectin")


class SalaryOrderLink(Base):
    """工资记录对应的订单明细（这月哪些订单算了提成）

    唯一约束 (order_id, is_manager_share)：一个订单最多挂两次——员工本人提成
    一次 + 经理分成一次。并发生成工资单时约束兜底避免双发。
    """
    __tablename__ = "salary_order_links"
    __table_args__ = (
        UniqueConstraint("order_id", "is_manager_share", name="uq_order_commission_once"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    salary_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("salary_records.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), nullable=False)
    brand_id: Mapped[str] = mapped_column(String(36), ForeignKey("brands.id"), nullable=False)
    receipt_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    commission_rate_used: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0.0000"))
    kpi_coefficient: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0000"))
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    is_manager_share: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否是经理拿下属份额
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ManufacturerSalarySubsidy(Base):
    """厂家工资补贴应收记录"""
    __tablename__ = "manufacturer_salary_subsidies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True,
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=False, index=True,
    )
    salary_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("salary_records.id"), nullable=True,
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    subsidy_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # status: pending(应收已挂账,未发薪) / advanced(公司已垫付,待厂家到账) / reimbursed(厂家已到账)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    advanced_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    arrival_billcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    arrival_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reimbursed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reimburse_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True,
    )
    reimburse_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    employee: Mapped["Employee"] = relationship("Employee", lazy="selectin")
    brand: Mapped["Brand"] = relationship("Brand", lazy="selectin")


class KpiCoefficientRule(Base):
    """KPI 完成率系数规则（品牌级，可按时间段留存历史）

    业务规则（boss/admin 配置）：
      - 按 brand_id 独立配置（每品牌一套）
      - 覆盖完成率区间 [min_rate, max_rate)，max_rate=NULL 表示 +∞
      - mode='linear'：系数 = 完成率（按 rate 线性）
      - mode='fixed'：系数 = fixed_value（区间内固定）

    历史留存：
      - 改规则不 UPDATE 旧记录，而是 effective_to=today + INSERT 新记录
      - 工资单另有 kpi_rule_snapshot 字段冻结当时用的规则集
      - 同时段内同品牌的区间不允许重叠（应用层校验）
    """
    __tablename__ = "kpi_coefficient_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    min_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)  # 闭区间下限
    max_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)  # 开区间上限，NULL=+∞
    mode: Mapped[str] = mapped_column(String(10), nullable=False)  # linear | fixed
    fixed_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)  # NULL = 当前有效
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    brand: Mapped["Brand"] = relationship("Brand", lazy="selectin")
