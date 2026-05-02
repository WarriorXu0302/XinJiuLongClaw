"""
/api/mall/workspace/customers

业务员负责的客户列表（用 ERP CustomerBrandSalesman 反查）。
打卡页 / 拜访页的客户下拉来源。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.customer import Customer, CustomerBrandSalesman
from app.services.mall import auth_service

router = APIRouter()


@router.get("")
async def my_customers(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        return {"records": []}

    # CBS 绑定反查（业务员在任何品牌下名下的客户）
    cbs_rows = (await db.execute(
        select(CustomerBrandSalesman)
        .where(CustomerBrandSalesman.salesman_id == user.linked_employee_id)
    )).scalars().all()
    cust_ids = list({r.customer_id for r in cbs_rows})
    # 同时兼容老字段 salesman_id
    fallback_rows = (await db.execute(
        select(Customer).where(Customer.salesman_id == user.linked_employee_id)
    )).scalars().all()
    cust_ids.extend([c.id for c in fallback_rows if c.id not in cust_ids])

    if not cust_ids:
        return {"records": []}

    # 只返 active 客户（停用/归档的客户不该出现在打卡选择器和拜访下拉）
    customers = (await db.execute(
        select(Customer)
        .where(Customer.id.in_(cust_ids))
        .where(Customer.status == "active")
    )).scalars().all()
    return {
        "records": [
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "contact_name": c.contact_name,
                "contact_phone": c.contact_phone,
                "contact_address": c.contact_address,
                "customer_type": c.customer_type,
                "settlement_mode": c.settlement_mode,
                "status": c.status,
            }
            for c in customers
        ]
    }
