"""
Role / permission helpers.
RLS 是数据库层兜底；本模块提供应用层软边界：
- require_role / is_*  — API 入口显式 403，省得打到 DB
- apply_data_scope     — 业务语义过滤（比 RLS 细，如"只看自己的订单"）
- can_see_* helpers    — 前端菜单/按钮 + 后端同步判断
"""
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select


# ─── 数据范围 ────────────────────────────────────────────────────

def apply_data_scope(
    stmt: Select,
    user: dict[str, Any],
    *,
    salesman_column=None,
    warehouse_column=None,
) -> Select:
    """业务语义过滤。RLS 已强制品牌隔离，这里补充"只看自己"类语义。"""
    roles: list[str] = user.get("roles", [])

    if "admin" in roles or "boss" in roles:
        return stmt

    employee_id = user.get("employee_id")

    if "salesman" in roles and salesman_column is not None and employee_id:
        stmt = stmt.where(salesman_column == employee_id)

    if "warehouse" in roles and warehouse_column is not None:
        warehouse_ids = user.get("warehouse_ids", [])
        if warehouse_ids:
            stmt = stmt.where(warehouse_column.in_(warehouse_ids))

    return stmt


# ─── 基础角色判断 ──────────────────────────────────────────────

def _roles(user: dict[str, Any]) -> list[str]:
    return user.get("roles", [])


def is_admin(user: dict[str, Any]) -> bool:
    return "admin" in _roles(user) or "boss" in _roles(user)


def is_privileged(user: dict[str, Any]) -> bool:
    """全局业务数据可见（收窄：只含 admin/boss/sales_manager，剔除 finance/hr）"""
    return any(r in _roles(user) for r in ("admin", "boss", "sales_manager"))


def is_salesman(user: dict[str, Any]) -> bool:
    return "salesman" in _roles(user) and not is_privileged(user)


# ─── 功能域权限 ───────────────────────────────────────────────

def can_see_master_account(user: dict[str, Any]) -> bool:
    """看公司总资金池（master 现金账户）—— 只有 admin/boss"""
    return is_admin(user)


def can_see_salary(user: dict[str, Any]) -> bool:
    """看工资明细、薪酬方案、厂家补贴 —— admin/boss/hr（财务不能看）"""
    return any(r in _roles(user) for r in ("admin", "boss", "hr"))


def can_operate_fund_transfer(user: dict[str, Any]) -> bool:
    """做资金调拨 —— admin/boss/finance"""
    return any(r in _roles(user) for r in ("admin", "boss", "finance"))


def can_manage_inspections(user: dict[str, Any]) -> bool:
    """稽查案件的创建/审批 —— admin/boss/finance"""
    return any(r in _roles(user) for r in ("admin", "boss", "finance"))


# ─── 强制断言 ─────────────────────────────────────────────────

def require_role(user: dict[str, Any], *allowed: str) -> None:
    """不在允许列表抛 403。`admin` 总是被默认接受。"""
    roles = _roles(user)
    if "admin" in roles:
        return
    if not any(r in roles for r in allowed):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"需要角色之一: {', '.join(allowed)}")


def require_can_see_salary(user: dict[str, Any]) -> None:
    if not can_see_salary(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看工资数据")


def require_can_see_master(user: dict[str, Any]) -> None:
    if not can_see_master_account(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看总资金池")
