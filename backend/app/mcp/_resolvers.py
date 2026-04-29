"""
MCP 公共 resolver — name/code → UUID 转换层。

为什么单独一份：
- HTTP 层要求所有 ID 都是 UUID
- MCP 入口要接纳 AI agent 的自然语言（"张三烟酒店" / "QHL-001" / uuid）
- 转换只是 MCP 的展示层职责，不属于业务逻辑

规则：
- 优先 UUID → 其次 code → 最后 name
- 找不到抛 HTTPException(404)，错误消息带用户传入的 identifier
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _lookup(db: AsyncSession, model: Any, identifier: str, name_attr: str = "name"):
    """三阶段查：UUID (主键) → code → name。"""
    # 1) 主键
    obj = await db.get(model, identifier)
    if obj:
        return obj
    # 2) code（大部分业务模型有 code 字段）
    if hasattr(model, "code"):
        obj = (await db.execute(
            select(model).where(model.code == identifier)
        )).scalar_one_or_none()
        if obj:
            return obj
    # 3) name
    if hasattr(model, name_attr):
        obj = (await db.execute(
            select(model).where(getattr(model, name_attr) == identifier)
        )).scalar_one_or_none()
        if obj:
            return obj
    return None


async def resolve_customer_id(db: AsyncSession, identifier: str) -> str:
    from app.models.customer import Customer
    obj = await _lookup(db, Customer, identifier)
    if not obj:
        raise HTTPException(404, f"客户 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_salesman_id(db: AsyncSession, identifier: str) -> str:
    """Employee.employee_no 作为 code。"""
    from app.models.user import Employee
    obj = await db.get(Employee, identifier)
    if not obj:
        obj = (await db.execute(
            select(Employee).where(Employee.employee_no == identifier)
        )).scalar_one_or_none()
    if not obj:
        obj = (await db.execute(
            select(Employee).where(Employee.name == identifier)
        )).scalar_one_or_none()
    if not obj:
        raise HTTPException(404, f"业务员 {identifier} 不存在（支持 UUID/工号/姓名）")
    return obj.id


async def resolve_product_id(db: AsyncSession, identifier: str) -> str:
    from app.models.product import Product
    obj = await _lookup(db, Product, identifier)
    if not obj:
        raise HTTPException(404, f"商品 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_brand_id(db: AsyncSession, identifier: str) -> str:
    from app.models.product import Brand  # 实际住在 product.py
    obj = await _lookup(db, Brand, identifier)
    if not obj:
        raise HTTPException(404, f"品牌 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_policy_template_id(db: AsyncSession, identifier: str) -> str:
    from app.models.policy_template import PolicyTemplate
    obj = await _lookup(db, PolicyTemplate, identifier)
    if not obj:
        raise HTTPException(404, f"政策模板 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_warehouse_id(db: AsyncSession, identifier: str) -> str:
    from app.models.product import Warehouse  # 住在 product.py
    obj = await _lookup(db, Warehouse, identifier)
    if not obj:
        raise HTTPException(404, f"仓库 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_supplier_id(db: AsyncSession, identifier: str) -> str:
    from app.models.product import Supplier  # 住在 product.py
    obj = await _lookup(db, Supplier, identifier)
    if not obj:
        raise HTTPException(404, f"供应商 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_account_id(db: AsyncSession, identifier: str) -> str:
    from app.models.product import Account  # 模型实际住在 product.py
    obj = await _lookup(db, Account, identifier)
    if not obj:
        raise HTTPException(404, f"账户 {identifier} 不存在（支持 UUID/编码/名称）")
    return obj.id


async def resolve_order_by_no(db: AsyncSession, order_no: str):
    """按 order_no 查 Order 对象，找不到抛 404。"""
    from app.models.order import Order
    obj = (await db.execute(
        select(Order).where(Order.order_no == order_no)
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(404, f"订单 {order_no} 不存在")
    return obj
