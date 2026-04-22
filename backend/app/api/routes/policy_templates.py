"""
Policy Template API routes — CRUD for policy_templates and policy_adjustments.
"""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.policy_template import PolicyAdjustment, PolicyTemplate
from app.models.policy_template_benefit import PolicyTemplateBenefit
from app.services.audit_service import log_audit
from decimal import Decimal

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# PolicyTemplate schemas
# ═══════════════════════════════════════════════════════════════════


class BenefitItemCreate(BaseModel):
    benefit_type: str
    name: str
    quantity: int = 1
    quantity_unit: str = "次"
    standard_unit_value: float = 0  # 实际价值单价（厂家面值）
    unit_value: float = 0  # 折算单价（我们到手）
    product_id: Optional[str] = None
    is_material: bool = False
    fulfill_mode: str = "claim"  # claim / direct / material
    notes: Optional[str] = None
    sort_order: int = 0


class BenefitItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    benefit_type: str
    name: str
    quantity: int
    quantity_unit: str = "次"
    standard_unit_value: float = 0
    standard_total: float = 0
    unit_value: float
    total_value: float
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    is_material: bool
    fulfill_mode: str = "claim"
    notes: Optional[str] = None
    sort_order: int = 0


class PolicyTemplateCreate(BaseModel):
    code: str
    name: str
    template_type: str = "channel"
    brand_id: Optional[str] = None
    required_unit_price: Optional[float] = None
    customer_unit_price: Optional[float] = None
    benefit_rules: Optional[dict[str, Any]] = None
    internal_valuation: Optional[dict[str, Any]] = None
    min_cases: Optional[int] = None
    max_cases: Optional[int] = None
    member_tier: Optional[str] = None
    min_points: Optional[int] = None
    max_points: Optional[int] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    default_scheme_no: Optional[str] = None
    version: int = 1
    is_active: bool = True
    notes: Optional[str] = None
    benefits: list[BenefitItemCreate] = []


class PolicyTemplateUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    template_type: Optional[str] = None
    brand_id: Optional[str] = None
    required_unit_price: Optional[float] = None
    customer_unit_price: Optional[float] = None
    benefit_rules: Optional[dict[str, Any]] = None
    internal_valuation: Optional[dict[str, Any]] = None
    min_cases: Optional[int] = None
    max_cases: Optional[int] = None
    member_tier: Optional[str] = None
    min_points: Optional[int] = None
    max_points: Optional[int] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    default_scheme_no: Optional[str] = None
    version: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    benefits: Optional[list[BenefitItemCreate]] = None


class PolicyTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    template_type: str = "channel"
    brand_id: Optional[str] = None
    required_unit_price: Optional[float] = None
    customer_unit_price: Optional[float] = None
    benefit_rules: Optional[dict[str, Any]] = None
    internal_valuation: Optional[dict[str, Any]] = None
    min_cases: Optional[int] = None
    max_cases: Optional[int] = None
    member_tier: Optional[str] = None
    min_points: Optional[int] = None
    max_points: Optional[int] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    default_scheme_no: Optional[str] = None
    total_policy_value: float = 0
    version: int
    is_active: bool
    notes: Optional[str] = None
    benefits: list[BenefitItemResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None


CONFIDENTIAL_ROLES = {"admin", "boss", "finance"}


def _strip_confidential(data: dict, user: dict) -> dict:
    """Remove internal_valuation if user is not admin/boss/finance."""
    roles = set(user.get("roles", []))
    if not roles & CONFIDENTIAL_ROLES:
        data.pop("internal_valuation", None)
    return data


# ═══════════════════════════════════════════════════════════════════
# PolicyAdjustment schemas
# ═══════════════════════════════════════════════════════════════════


class PolicyAdjustmentCreate(BaseModel):
    policy_request_id: str
    adjustment_type: str
    diff: Optional[dict[str, Any]] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class PolicyAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    policy_request_id: str
    adjustment_type: str
    diff: Optional[dict[str, Any]] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# PolicyTemplate CRUD
# ═══════════════════════════════════════════════════════════════════


def _sync_benefits(template: PolicyTemplate, benefits_data: list[BenefitItemCreate]) -> None:
    """Replace template benefits with new list and recalculate total."""
    template.benefits.clear()
    total = Decimal("0")
    for i, b in enumerate(benefits_data):
        suv = Decimal(str(b.standard_unit_value))
        st = suv * b.quantity
        uv = Decimal(str(b.unit_value))
        tv = uv * b.quantity
        item = PolicyTemplateBenefit(
            id=str(uuid.uuid4()), template_id=template.id,
            benefit_type=b.benefit_type, name=b.name,
            quantity=b.quantity,
            standard_unit_value=suv, standard_total=st,
            unit_value=uv, total_value=tv,
            product_id=b.product_id,
            is_material=b.is_material, fulfill_mode=b.fulfill_mode, quantity_unit=b.quantity_unit, notes=b.notes, sort_order=b.sort_order or i,
        )
        template.benefits.append(item)
        total += tv
    template.total_policy_value = total


def _template_to_response(obj: PolicyTemplate) -> dict:
    d = PolicyTemplateResponse.model_validate(obj).model_dump()
    d["benefits"] = []
    for b in obj.benefits:
        bd = BenefitItemResponse.model_validate(b).model_dump()
        bd["product_name"] = b.product.name if b.product else None
        d["benefits"].append(bd)
    return d


@router.post("/templates", response_model=PolicyTemplateResponse, status_code=201)
async def create_template(body: PolicyTemplateCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    data = body.model_dump(exclude={"benefits"})
    obj = PolicyTemplate(id=str(uuid.uuid4()), **data)
    db.add(obj)
    _sync_benefits(obj, body.benefits)
    await db.flush()
    await db.refresh(obj, ["benefits"])
    return _template_to_response(obj)


@router.get("/templates")
async def list_templates(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    base = select(PolicyTemplate)
    if brand_id:
        base = base.where(PolicyTemplate.brand_id == brand_id)
    if is_active is not None:
        base = base.where(PolicyTemplate.is_active == is_active)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(PolicyTemplate.code).offset(skip).limit(limit))).scalars().all()
    result = []
    for r in rows:
        d = _template_to_response(r)
        result.append(_strip_confidential(d, user))
    return {"items": result, "total": total}


# ── Business: auto-match templates ───────────────────────────────────


@router.get("/templates/match")
async def match_templates(
    user: CurrentUser,
    brand_id: str = Query(..., description="品牌ID"),
    cases: int = Query(0, description="箱数（渠道模板用）"),
    points: int = Query(0, description="积分（团购模板用）"),
    unit_price: float = Query(0, description="订单单价，用于价格校验"),
    db: AsyncSession = Depends(get_db),
):
    """Find active, in-date policy templates matching brand, cases/points, and price.

    Templates with required_unit_price will only match if order price matches.
    """
    from sqlalchemy import or_

    today = date.today()

    def _validity_filter(stmt):
        """Only return templates within valid date range."""
        stmt = stmt.where(
            or_(PolicyTemplate.valid_from <= today, PolicyTemplate.valid_from.is_(None))
        )
        stmt = stmt.where(
            or_(PolicyTemplate.valid_to >= today, PolicyTemplate.valid_to.is_(None))
        )
        return stmt

    results = []

    # ── Channel templates: exact case count match ──
    if cases > 0:
        stmt = (
            select(PolicyTemplate)
            .where(PolicyTemplate.is_active == True)
            .where(PolicyTemplate.template_type == "channel")
            .where(
                or_(PolicyTemplate.brand_id == brand_id, PolicyTemplate.brand_id.is_(None))
            )
            .where(PolicyTemplate.min_cases == cases)
        )
        stmt = _validity_filter(stmt)
        rows = (await db.execute(stmt)).scalars().all()
        for r in rows:
            d = _template_to_response(r)
            results.append(_strip_confidential(d, user))

    # ── Group purchase templates: match by points ──
    if points > 0:
        stmt = (
            select(PolicyTemplate)
            .where(PolicyTemplate.is_active == True)
            .where(PolicyTemplate.template_type == "group_purchase")
            .where(
                or_(PolicyTemplate.brand_id == brand_id, PolicyTemplate.brand_id.is_(None))
            )
            .where(
                or_(PolicyTemplate.min_points <= points, PolicyTemplate.min_points.is_(None))
            )
            .where(
                or_(PolicyTemplate.max_points >= points, PolicyTemplate.max_points.is_(None))
            )
            .order_by(PolicyTemplate.min_points.desc().nulls_last())
        )
        stmt = _validity_filter(stmt)
        rows = (await db.execute(stmt)).scalars().all()
        for r in rows:
            d = _template_to_response(r)
            results.append(_strip_confidential(d, user))

    # ── Filter by price requirement ──
    if unit_price > 0:
        results = [
            r for r in results
            if r.get('required_unit_price') is None
            or abs(float(r['required_unit_price']) - unit_price) < 0.01
        ]

    # ── Add price_match status to each result ──
    for r in results:
        req_price = r.get('required_unit_price')
        if req_price is not None and unit_price > 0:
            r['price_matched'] = abs(float(req_price) - unit_price) < 0.01
        else:
            r['price_matched'] = True

    return results


@router.get("/templates/{template_id}")
async def get_template(template_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(PolicyTemplate, template_id)
    if obj is None:
        raise HTTPException(404, "PolicyTemplate not found")
    d = _template_to_response(obj)
    return _strip_confidential(d, user)




class ExtendRequest(BaseModel):
    new_valid_to: date


@router.post("/templates/{template_id}/extend")
async def extend_template(
    template_id: str, body: ExtendRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Extend a template's validity period. Requires admin/boss role."""
    roles = set(user.get("roles", []))
    if not roles & {"admin", "boss"}:
        raise HTTPException(403, "仅老板/管理员可延期政策模板")
    obj = await db.get(PolicyTemplate, template_id)
    if obj is None:
        raise HTTPException(404, "PolicyTemplate not found")
    old_to = obj.valid_to
    obj.valid_to = body.new_valid_to
    obj.is_active = True
    await db.flush()
    await log_audit(
        db, action="extend_template", entity_type="PolicyTemplate", entity_id=obj.id,
        changes={"old_valid_to": str(old_to), "new_valid_to": str(body.new_valid_to)}, user=user)
    return {"detail": f"已延期至 {body.new_valid_to}", "id": obj.id}


@router.put("/templates/{template_id}", response_model=PolicyTemplateResponse)
async def update_template(
    template_id: str, body: PolicyTemplateUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(PolicyTemplate, template_id)
    if obj is None:
        raise HTTPException(404, "PolicyTemplate not found")
    for k, v in body.model_dump(exclude_unset=True, exclude={"benefits"}).items():
        setattr(obj, k, v)
    if body.benefits is not None:
        _sync_benefits(obj, body.benefits)
    await db.flush()
    await db.refresh(obj, ["benefits"])
    return _template_to_response(obj)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(PolicyTemplate, template_id)
    if obj is None:
        raise HTTPException(404, "PolicyTemplate not found")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# PolicyAdjustment CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/adjustments", response_model=PolicyAdjustmentResponse, status_code=201)
async def create_adjustment(body: PolicyAdjustmentCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = PolicyAdjustment(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    await log_audit(db, action="create_policy_adjustment", entity_type="PolicyAdjustment", entity_id=obj.id, user=user)
    return obj


@router.get("/adjustments")
async def list_adjustments(
    user: CurrentUser,
    policy_request_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    base = select(PolicyAdjustment)
    if policy_request_id:
        base = base.where(PolicyAdjustment.policy_request_id == policy_request_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(PolicyAdjustment.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/adjustments/{adj_id}", response_model=PolicyAdjustmentResponse)
async def get_adjustment(adj_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(PolicyAdjustment, adj_id)
    if obj is None:
        raise HTTPException(404, "PolicyAdjustment not found")
    return obj
