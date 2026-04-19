"""
Data range filtering based on user roles.
Provides helper functions to apply row-level security filters.
"""
from typing import Any

from sqlalchemy import Select


def apply_data_scope(
    stmt: Select,
    user: dict[str, Any],
    *,
    salesman_column=None,
    warehouse_column=None,
) -> Select:
    """Apply role-based data range filtering to a query.

    Args:
        stmt: The SQLAlchemy select statement to filter.
        user: The decoded JWT payload (from CurrentUser).
        salesman_column: The column to filter by salesman (e.g., Order.salesman_id).
        warehouse_column: The column to filter by warehouse (e.g., Inventory.warehouse_id).

    Returns:
        The filtered select statement.
    """
    roles: list[str] = user.get("roles", [])

    # admin / boss see everything
    if "admin" in roles or "boss" in roles:
        return stmt

    employee_id = user.get("employee_id")

    # salesman: only own data
    if "salesman" in roles and salesman_column is not None and employee_id:
        stmt = stmt.where(salesman_column == employee_id)

    # warehouse: only authorized warehouses
    if "warehouse" in roles and warehouse_column is not None:
        warehouse_ids = user.get("warehouse_ids", [])
        if warehouse_ids:
            stmt = stmt.where(warehouse_column.in_(warehouse_ids))

    return stmt


def is_privileged(user: dict[str, Any]) -> bool:
    """判断用户是否拥有全局数据可见性（不做业务员过滤）"""
    roles = user.get("roles", [])
    return any(r in roles for r in ("admin", "boss", "finance", "hr", "sales_manager"))


def is_salesman(user: dict[str, Any]) -> bool:
    roles = user.get("roles", [])
    return "salesman" in roles and not is_privileged(user)
