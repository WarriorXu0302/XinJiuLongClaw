"""
Customer API routes — CRUD + order history.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.customer import Customer, CustomerBrandSalesman
from app.models.order import Order
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate
from app.schemas.order import OrderResponse

router = APIRouter()


@router.post("", response_model=CustomerResponse, status_code=201)
async def create_customer(body: CustomerCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "salesman", "sales_manager")
    data = body.model_dump()
    brand_id = data.pop("brand_id", None)

    roles = user.get("roles", [])
    is_salesman = "salesman" in roles and not any(r in roles for r in ("admin", "boss", "finance", "hr", "sales_manager"))

    # 业务员建客户：必须绑品牌，且业务员自动 = 本人
    if is_salesman:
        user_brand_ids = user.get("brand_ids") or []
        # salesman 只绑了一个品牌时自动用它；传了 brand_id 的校验必须在范围内
        if not brand_id:
            if len(user_brand_ids) == 1:
                brand_id = user_brand_ids[0]
            else:
                raise HTTPException(400, "请指定归属品牌")
        elif brand_id not in user_brand_ids:
            raise HTTPException(403, "无权归属到该品牌")
        # salesman 建的客户自动把业务员设为自己
        if not data.get("salesman_id"):
            data["salesman_id"] = user.get("employee_id")

    obj = Customer(id=str(uuid.uuid4()), **data)
    db.add(obj)
    await db.flush()

    # 建品牌-业务员绑定
    if brand_id and data.get("salesman_id"):
        db.add(CustomerBrandSalesman(
            id=str(uuid.uuid4()),
            customer_id=obj.id,
            brand_id=brand_id,
            salesman_id=data["salesman_id"],
        ))
        await db.flush()

    return obj


@router.get("")
async def list_customers(
    user: CurrentUser,
    customer_type: str | None = Query(None),
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None, description="名称/联系人/电话模糊"),
    settlement_mode: str | None = Query(None),
    salesman_id: str | None = Query(None, description="指定业务员的客户"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    base = select(Customer)
    if customer_type:
        base = base.where(Customer.customer_type == customer_type)
    if status:
        base = base.where(Customer.status == status)
    if settlement_mode:
        base = base.where(Customer.settlement_mode == settlement_mode)
    if keyword:
        kw = f"%{keyword}%"
        base = base.where(
            (Customer.name.ilike(kw))
            | (Customer.contact_name.ilike(kw))
            | (Customer.contact_phone.ilike(kw))
        )

    roles = user.get("roles", [])
    force_own = (
        "salesman" in roles
        and not any(r in roles for r in ("admin", "boss", "finance", "hr", "sales_manager"))
        and user.get("employee_id")
    )
    if brand_id or salesman_id or force_own:
        base = base.join(CustomerBrandSalesman, CustomerBrandSalesman.customer_id == Customer.id)
        if brand_id:
            base = base.where(CustomerBrandSalesman.brand_id == brand_id)
        if salesman_id:
            base = base.where(CustomerBrandSalesman.salesman_id == salesman_id)
        if force_own:
            base = base.where(CustomerBrandSalesman.salesman_id == user["employee_id"])
        # 多品牌客户（同一 customer 在 CBS 里有多条）join 后会重复，去重
        base = base.distinct()

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.order_by(Customer.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return {"items": rows, "total": total}


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Customer, customer_id)
    if obj is None:
        raise HTTPException(404, "Customer not found")
    return obj


@router.get("/{customer_id}/orders", response_model=list[OrderResponse])
async def get_customer_orders(
    customer_id: str,
    user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get all orders for a specific customer."""
    stmt = (
        select(Order)
        .where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .offset(skip).limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str, body: CustomerUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    require_role(user, "boss", "salesman", "sales_manager")
    obj = await db.get(Customer, customer_id)
    if obj is None:
        raise HTTPException(404, "Customer not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(customer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "sales_manager")
    obj = await db.get(Customer, customer_id)
    if obj is None:
        raise HTTPException(404, "Customer not found")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Customer Brand-Salesman Binding
# ═══════════════════════════════════════════════════════════════════


@router.get("/{customer_id}/brand-salesman")
async def get_customer_brand_salesman(customer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(CustomerBrandSalesman).where(CustomerBrandSalesman.customer_id == customer_id)
    )).scalars().all()
    return [{"id": r.id, "brand_id": r.brand_id, "salesman_id": r.salesman_id} for r in rows]


from pydantic import BaseModel as _PBM


class BindBrandSalesmanBody(_PBM):
    brand_id: str
    salesman_id: str


@router.post("/{customer_id}/brand-salesman", status_code=201)
async def bind_customer_brand_salesman(
    customer_id: str, body: BindBrandSalesmanBody, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    require_role(user, "boss", "salesman", "sales_manager")
    existing = (await db.execute(
        select(CustomerBrandSalesman).where(
            CustomerBrandSalesman.customer_id == customer_id,
            CustomerBrandSalesman.brand_id == body.brand_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.salesman_id = body.salesman_id
        await db.flush()
        return {"id": existing.id, "customer_id": customer_id, "brand_id": body.brand_id, "salesman_id": body.salesman_id}
    obj = CustomerBrandSalesman(
        id=str(uuid.uuid4()), customer_id=customer_id,
        brand_id=body.brand_id, salesman_id=body.salesman_id,
    )
    db.add(obj)
    await db.flush()
    return {"id": obj.id, "customer_id": customer_id, "brand_id": body.brand_id, "salesman_id": body.salesman_id}


@router.delete("/{customer_id}/brand-salesman/{brand_id}", status_code=204)
async def unbind_customer_brand_salesman(
    customer_id: str, brand_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    require_role(user, "boss", "sales_manager")
    obj = (await db.execute(
        select(CustomerBrandSalesman).where(
            CustomerBrandSalesman.customer_id == customer_id,
            CustomerBrandSalesman.brand_id == brand_id,
        )
    )).scalar_one_or_none()
    if obj:
        await db.delete(obj)
        await db.flush()


@router.get("/{customer_id}/360")
async def customer_360(
    customer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """客户 360 视图：该客户所有订单/政策/收款/应收/拜访的聚合"""
    from app.models.finance import Receipt
    from app.models.customer import Receivable
    from app.models.policy import PolicyRequest
    from app.models.attendance import CustomerVisit
    from sqlalchemy import func

    cust = await db.get(Customer, customer_id)
    if not cust:
        raise HTTPException(404, "客户不存在")

    # 订单
    from app.models.product import Brand as _Brand
    orders = (await db.execute(
        select(Order).where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc()).limit(100)
    )).scalars().all()
    # 批量查品牌名
    brand_ids = {o.brand_id for o in orders if o.brand_id}
    brand_name_map = {}
    if brand_ids:
        bs = (await db.execute(select(_Brand).where(_Brand.id.in_(brand_ids)))).scalars().all()
        brand_name_map = {b.id: b.name for b in bs}
    order_list = [{
        "id": o.id, "order_no": o.order_no,
        "total_amount": float(o.total_amount or 0),
        "status": o.status, "payment_status": o.payment_status,
        "salesman_name": o.salesman.name if o.salesman else None,
        "brand_name": brand_name_map.get(o.brand_id),
        "created_at": str(o.created_at)[:19] if o.created_at else None,
    } for o in orders]

    # 收款
    receipts = (await db.execute(
        select(Receipt).where(Receipt.customer_id == customer_id)
        .order_by(Receipt.receipt_date.desc()).limit(100)
    )).scalars().all()
    receipt_list = [{
        "id": r.id, "receipt_no": r.receipt_no,
        "amount": float(r.amount or 0),
        "receipt_date": str(r.receipt_date) if r.receipt_date else None,
        "payment_method": r.payment_method,
        "order_id": r.order_id,
    } for r in receipts]

    # 应收
    receivables = (await db.execute(
        select(Receivable).where(Receivable.customer_id == customer_id)
        .order_by(Receivable.created_at.desc()).limit(50)
    )).scalars().all()
    receivable_list = [{
        "id": rc.id, "receivable_no": rc.receivable_no,
        "amount": float(rc.amount or 0),
        "paid_amount": float(rc.paid_amount or 0),
        "remaining": float((rc.amount or 0) - (rc.paid_amount or 0)),
        "due_date": str(rc.due_date) if rc.due_date else None,
        "status": rc.status,
        "order_id": rc.order_id,
    } for rc in receivables]

    # 拜访
    visits = (await db.execute(
        select(CustomerVisit).where(CustomerVisit.customer_id == customer_id)
        .order_by(CustomerVisit.visit_date.desc()).limit(50)
    )).scalars().all()
    visit_list = [{
        "id": v.id,
        "employee_name": v.employee.name if v.employee else None,
        "visit_date": str(v.visit_date) if v.visit_date else None,
        "enter_time": str(v.enter_time)[:19] if v.enter_time else None,
        "leave_time": str(v.leave_time)[:19] if v.leave_time else None,
        "duration_minutes": v.duration_minutes,
        "is_valid": v.is_valid,
    } for v in visits]

    # 政策（通过订单关联）
    order_ids = [o.id for o in orders]
    policies = []
    if order_ids:
        prs = (await db.execute(
            select(PolicyRequest).where(PolicyRequest.order_id.in_(order_ids))
            .order_by(PolicyRequest.created_at.desc()).limit(50)
        )).scalars().all()
        policies = [{
            "id": p.id, "status": p.status,
            "usage_purpose": p.usage_purpose,
            "total_policy_value": float(p.total_policy_value or 0),
            "request_source": p.request_source,
            "created_at": str(p.created_at)[:19] if p.created_at else None,
        } for p in prs]

    # 汇总
    total_sales = sum(o["total_amount"] for o in order_list)
    total_received = sum(r["amount"] for r in receipt_list)
    total_outstanding = sum(rc["remaining"] for rc in receivable_list if rc["status"] != "paid")

    return {
        "customer": {
            "id": cust.id, "name": cust.name,
            "phone": getattr(cust, "contact_phone", None),
            "address": getattr(cust, "address", None),
            "customer_type": cust.customer_type,
            "settlement_mode": getattr(cust, "settlement_mode", None),
            "credit_days": getattr(cust, "credit_days", None),
            "status": cust.status,
        },
        "summary": {
            "total_orders": len(order_list),
            "total_sales": total_sales,
            "total_received": total_received,
            "total_outstanding": total_outstanding,
            "visits_count": len(visit_list),
            "policies_count": len(policies),
        },
        "orders": order_list,
        "receipts": receipt_list,
        "receivables": receivable_list,
        "visits": visit_list,
        "policies": policies,
    }
