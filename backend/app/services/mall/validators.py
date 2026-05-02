"""
Mall 业务校验工具（应用层）。

三层防御的第二层（JWT 第一层 / DB trigger 第三层）。
返回业务友好的 400/403 错误，避免用户直接撞到 CHECK 约束的 500 级错误。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import (
    MallUserApplicationStatus,
    MallUserStatus,
    MallUserType,
)
from app.models.mall.user import MallUser


async def assert_is_salesman(
    db: AsyncSession, user_id: str, field_name: str = "user_id"
) -> MallUser:
    """给引用"业务员"的字段写入前调用。

    典型场景：设 mall_warehouses.manager_user_id / mall_orders.assigned_salesman_id 前。
    """
    user = (
        await db.execute(select(MallUser).where(MallUser.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"{field_name} 指向的用户不存在")
    if user.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 必须是业务员，当前为 {user.user_type}",
        )
    return user


def assert_mall_user_active(user: MallUser) -> None:
    """登录/下单前检查 status='active'。disabled/inactive_archived 都拒绝。"""
    if user.status != MallUserStatus.ACTIVE.value:
        raise HTTPException(
            status_code=403, detail="账号已停用，请联系管理员"
        )


def assert_mall_user_approved(user: MallUser) -> None:
    """登录前检查 application_status='approved'。

    业务员跳过审批（user_type='salesman'）；消费者若 pending/rejected 都拒绝登录，
    错误 body 里返 application_id 让前端跳"审批中"页。
    """
    if user.user_type == MallUserType.SALESMAN.value:
        return
    if user.application_status != MallUserApplicationStatus.APPROVED.value:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "application_not_approved",
                "application_id": user.id,
                "application_status": user.application_status,
                "rejection_reason": user.rejection_reason,
            },
        )


def assert_salesman_linked_to_employee(user: MallUser) -> None:
    """salesman 必须有 linked_employee_id（CHECK 约束会拒绝空值，此处更早地给出人话错误）。"""
    if (
        user.user_type == MallUserType.SALESMAN.value
        and not user.linked_employee_id
    ):
        raise HTTPException(
            status_code=400,
            detail="业务员账号必须绑定 ERP 员工（linked_employee_id）",
        )


async def assert_salesman_linked_employee_active(db, user: MallUser) -> None:
    """业务员登录时校验 linked employee 仍是 active 状态。

    ERP 端可能把员工改成 inactive/resigned，mall 侧必须同步拒绝登录：
    否则离职业务员还能通过 mall token 刷 ERP 的复用端点（打卡/报销/稽查）。
    """
    if user.user_type != MallUserType.SALESMAN.value:
        return
    if not user.linked_employee_id:
        return
    from app.models.user import Employee
    emp = await db.get(Employee, user.linked_employee_id)
    if emp is None:
        raise HTTPException(
            status_code=403,
            detail="绑定的 ERP 员工不存在，请联系管理员",
        )
    if emp.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"您绑定的 ERP 员工已停用（状态 {emp.status}），请联系 HR",
        )
