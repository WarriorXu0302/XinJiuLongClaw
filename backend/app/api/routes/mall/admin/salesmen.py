"""
/api/mall/admin/salesmen/*

管理员管理业务员账号。

端点：
  GET  /                     列表（分页 + 搜索 + 状态过滤，附带 employee/brand 信息）
  POST /                     新建业务员
  GET  /{id}                 详情
  PUT  /{id}                 更新（nickname / phone / assigned_brand_id）
  POST /{id}/disable         禁用（token_version +1 → 立即踢下线）
  POST /{id}/enable          启用
  PUT  /{id}/reset-password  重置密码

  GET  /_helpers/employees   可绑定 employee 下拉（未被其他 salesman 占用、active）
  GET  /_helpers/brands      品牌下拉
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser, get_password_hash
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
from app.models.product import Brand
from app.models.user import Employee
from app.services.audit_service import log_audit

router = APIRouter()


def _salesman_dict(u: MallUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "phone": u.phone,
        "status": u.status,
        "linked_employee_id": u.linked_employee_id,
        "assigned_brand_id": u.assigned_brand_id,
        "assigned_store_id": u.assigned_store_id,
        "is_accepting_orders": u.is_accepting_orders,
        "must_change_password": u.must_change_password,
        "created_at": u.created_at,
    }


# =============================================================================
# 列表（分页 + 搜索 + 关联 employee/brand）
# =============================================================================

@router.get("")
async def list_salesmen(
    user: CurrentUser,
    keyword: Optional[str] = Query(default=None, description="昵称/手机/用户名"),
    status: Optional[str] = Query(default=None, description="active/disabled/inactive_archived"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    stmt = select(MallUser).where(MallUser.user_type == MallUserType.SALESMAN.value)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            (MallUser.username.ilike(kw))
            | (MallUser.nickname.ilike(kw))
            | (MallUser.phone.ilike(kw))
        )
    if status:
        stmt = stmt.where(MallUser.status == status)

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallUser.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    emp_ids = [r.linked_employee_id for r in rows if r.linked_employee_id]
    brand_ids = [r.assigned_brand_id for r in rows if r.assigned_brand_id]

    emps = []
    brands = []
    if emp_ids:
        emps = (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars().all()
    if brand_ids:
        brands = (await db.execute(
            select(Brand).where(Brand.id.in_(brand_ids))
        )).scalars().all()
    emp_map = {e.id: e for e in emps}
    brand_map = {b.id: b for b in brands}

    records = []
    for r in rows:
        emp = emp_map.get(r.linked_employee_id)
        brand = brand_map.get(r.assigned_brand_id) if r.assigned_brand_id else None
        records.append({
            **_salesman_dict(r),
            "employee": {"id": emp.id, "name": emp.name, "status": emp.status} if emp else None,
            "brand": {"id": brand.id, "name": brand.name} if brand else None,
        })
    return {"records": records, "total": total}


# =============================================================================
# 详情
# =============================================================================

@router.get("/{salesman_id}")
async def get_salesman(
    salesman_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    emp = await db.get(Employee, sm.linked_employee_id) if sm.linked_employee_id else None
    brand = await db.get(Brand, sm.assigned_brand_id) if sm.assigned_brand_id else None

    # 销售统计：completed / partial_closed 订单数 + GMV
    from app.models.mall.base import MallOrderStatus
    from app.models.mall.order import MallOrder, MallSkipAlert
    from sqlalchemy import func as sa_f
    stats = (await db.execute(
        select(
            sa_f.count(MallOrder.id),
            sa_f.coalesce(sa_f.sum(MallOrder.received_amount), 0),
        )
        .where(MallOrder.assigned_salesman_id == salesman_id)
        .where(MallOrder.status.in_([
            MallOrderStatus.COMPLETED.value,
            MallOrderStatus.PARTIAL_CLOSED.value,
        ]))
    )).one()
    completed_count = int(stats[0] or 0)
    total_gmv = str(stats[1] or 0)

    # 在途订单数（assigned / shipped / delivered / pending_payment_confirmation）
    in_progress_count = int((await db.execute(
        select(sa_f.count(MallOrder.id))
        .where(MallOrder.assigned_salesman_id == salesman_id)
        .where(MallOrder.status.in_([
            MallOrderStatus.ASSIGNED.value,
            MallOrderStatus.SHIPPED.value,
            MallOrderStatus.DELIVERED.value,
            MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        ]))
    )).scalar() or 0)

    # 推荐客户数
    referred_count = int((await db.execute(
        select(sa_f.count(MallUser.id))
        .where(MallUser.referrer_salesman_id == salesman_id)
    )).scalar() or 0)

    # 未解决告警数
    open_alerts = int((await db.execute(
        select(sa_f.count(MallSkipAlert.id))
        .where(MallSkipAlert.salesman_user_id == salesman_id)
        .where(MallSkipAlert.status == "open")
    )).scalar() or 0)

    return {
        **_salesman_dict(sm),
        "employee": ({
            "id": emp.id, "name": emp.name, "status": emp.status,
        } if emp else None),
        "brand": ({"id": brand.id, "name": brand.name} if brand else None),
        "stats": {
            "completed_order_count": completed_count,
            "total_gmv": total_gmv,
            "in_progress_order_count": in_progress_count,
            "referred_customer_count": referred_count,
            "open_skip_alerts": open_alerts,
        },
    }


# =============================================================================
# 新建
# =============================================================================

class _CreateSalesmanBody(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    linked_employee_id: str = Field(min_length=36, max_length=36)
    assigned_brand_id: Optional[str] = None
    # 门店店员归属门店仓（warehouse_type='store'）；非店员为 None
    assigned_store_id: Optional[str] = None
    nickname: Optional[str] = None
    phone: Optional[str] = None


@router.post("")
async def create_salesman(
    body: _CreateSalesmanBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    emp = await db.get(Employee, body.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="linked_employee_id 指向的员工不存在")
    if emp.status != "active":
        raise HTTPException(status_code=400, detail=f"员工状态 {emp.status}，无法绑定")

    dup_emp = (await db.execute(
        select(MallUser)
        .where(MallUser.linked_employee_id == body.linked_employee_id)
        .where(MallUser.user_type == MallUserType.SALESMAN.value)
    )).scalar_one_or_none()
    if dup_emp:
        raise HTTPException(
            status_code=409,
            detail=f"员工 {emp.name} 已绑定业务员账号 {dup_emp.username}",
        )

    dup = (await db.execute(
        select(MallUser).where(MallUser.username == body.username)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="账号已存在")

    # 门店店员校验（assigned_store_id 非空时必须指向 warehouse_type='store' 的 active 仓）
    if body.assigned_store_id:
        from app.models.base import WarehouseType
        from app.models.product import Warehouse
        wh = await db.get(Warehouse, body.assigned_store_id)
        if wh is None:
            raise HTTPException(status_code=400, detail="归属门店不存在")
        if wh.warehouse_type != WarehouseType.STORE.value:
            raise HTTPException(
                status_code=400,
                detail=f"[{wh.name}] 不是门店类型（warehouse_type={wh.warehouse_type}）",
            )
        if not wh.is_active:
            raise HTTPException(status_code=400, detail=f"门店 [{wh.name}] 已停用")
        # 同步到 employees.assigned_store_id（双边一致）
        if emp.assigned_store_id != body.assigned_store_id:
            emp.assigned_store_id = body.assigned_store_id

    sm = MallUser(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        phone=body.phone,
        nickname=body.nickname or emp.name or body.username,
        status=MallUserStatus.ACTIVE.value,
        user_type=MallUserType.SALESMAN.value,
        linked_employee_id=body.linked_employee_id,
        assigned_brand_id=body.assigned_brand_id,
        assigned_store_id=body.assigned_store_id,
        is_accepting_orders=True,
        must_change_password=True,
        token_version=1,
    )
    db.add(sm)
    try:
        await db.flush()
    except IntegrityError as e:
        # 不手动 rollback：get_db 依赖在请求结束时会统一回滚；
        # 手动 rollback 会把当前事务的其他已改动标脏/丢失（和 C 端 register 一致的修法）
        raise HTTPException(status_code=409, detail="账号冲突，请稍后重试") from e

    await log_audit(
        db, action="mall_salesman.create", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={
            "username": body.username,
            "linked_employee_id": body.linked_employee_id,
            "employee_name": emp.name,
            "assigned_brand_id": body.assigned_brand_id,
            "assigned_store_id": body.assigned_store_id,
        },
    )
    return _salesman_dict(sm)


# =============================================================================
# 更新
# =============================================================================

class _UpdateSalesmanBody(BaseModel):
    nickname: Optional[str] = None
    phone: Optional[str] = None
    assigned_brand_id: Optional[str] = None  # 传空字符串或 null 清除
    assigned_store_id: Optional[str] = None  # 门店店员归属切换；同时同步到 Employee 表
    is_accepting_orders: Optional[bool] = None


@router.put("/{salesman_id}")
async def update_salesman(
    salesman_id: str,
    body: _UpdateSalesmanBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    updates = body.model_dump(exclude_unset=True)
    # 空串归一化为 None
    if updates.get("assigned_brand_id") == "":
        updates["assigned_brand_id"] = None
    if updates.get("assigned_store_id") == "":
        updates["assigned_store_id"] = None

    if "assigned_brand_id" in updates and updates["assigned_brand_id"]:
        b = await db.get(Brand, updates["assigned_brand_id"])
        if b is None:
            raise HTTPException(status_code=400, detail="品牌不存在")

    # assigned_store_id 变更校验 + 同步到 Employee.assigned_store_id
    if "assigned_store_id" in updates:
        new_store = updates["assigned_store_id"]
        if new_store:
            from app.models.base import WarehouseType
            from app.models.product import Warehouse
            wh = await db.get(Warehouse, new_store)
            if wh is None:
                raise HTTPException(status_code=400, detail="归属门店不存在")
            if wh.warehouse_type != WarehouseType.STORE.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"[{wh.name}] 不是门店类型",
                )
            if not wh.is_active:
                raise HTTPException(status_code=400, detail=f"门店 [{wh.name}] 已停用")
        # 同步到 employees 表（双边一致）
        if sm.linked_employee_id:
            from app.models.user import Employee
            emp = await db.get(Employee, sm.linked_employee_id)
            if emp is not None:
                emp.assigned_store_id = new_store

    for k, v in updates.items():
        setattr(sm, k, v)
    sm.updated_at = datetime.now(timezone.utc)

    await log_audit(
        db, action="mall_salesman.update", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request, changes=updates,
    )
    await db.flush()
    return _salesman_dict(sm)


# =============================================================================
# 换绑 ERP employee
# =============================================================================

class _RebindEmployeeBody(BaseModel):
    new_employee_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=1, max_length=500, description="换绑原因（审计）")


@router.put("/{salesman_id}/rebind-employee")
async def rebind_employee(
    salesman_id: str,
    body: _RebindEmployeeBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """业务员账号换绑到新的 ERP employee。

    场景：创建业务员时绑错了 employee，或业务员调岗换了 ERP 员工档案。
    严格校验，避免在途数据对不上：
      1. 新 employee 存在 + active
      2. 新 employee 未被其他 salesman 账号占用（unique 约束）
      3. 当前 salesman 没有在途订单（assigned/shipped/delivered/pending_payment_confirmation）
         —— 否则已有 commission/考勤/报销会绑在老 employee_id 上，换绑后历史错乱
      4. token_version +1 → 强制重新登录（新 employee 的 brand/position 可能不同）
      5. 记审计 + 通知业务员
    """
    from app.models.mall.base import MallOrderStatus
    from app.models.mall.order import MallOrder

    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    old_employee_id = sm.linked_employee_id
    if old_employee_id == body.new_employee_id:
        raise HTTPException(status_code=400, detail="新 employee 与当前 employee 相同")

    new_emp = await db.get(Employee, body.new_employee_id)
    if new_emp is None:
        raise HTTPException(status_code=400, detail="新 employee 不存在")
    if new_emp.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"新 employee 状态 {new_emp.status}，无法绑定",
        )

    # 2. 新 employee 被其他 salesman 占用
    dup = (await db.execute(
        select(MallUser)
        .where(MallUser.linked_employee_id == body.new_employee_id)
        .where(MallUser.user_type == MallUserType.SALESMAN.value)
        .where(MallUser.id != salesman_id)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"employee 已被业务员 {dup.username} 绑定",
        )

    # 3. 在途订单阻塞
    in_progress = int((await db.execute(
        select(sa_func.count(MallOrder.id))
        .where(MallOrder.assigned_salesman_id == salesman_id)
        .where(MallOrder.status.in_([
            MallOrderStatus.ASSIGNED.value,
            MallOrderStatus.SHIPPED.value,
            MallOrderStatus.DELIVERED.value,
            MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        ]))
    )).scalar() or 0)
    if in_progress > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"该业务员有 {in_progress} 个在途订单，请先完成或改派后再换绑"
                "（换绑会让新 employee 承接老订单的考勤/报销关联，容易错乱）"
            ),
        )

    old_emp = await db.get(Employee, old_employee_id) if old_employee_id else None
    sm.linked_employee_id = body.new_employee_id
    sm.token_version = (sm.token_version or 0) + 1
    sm.updated_at = datetime.now(timezone.utc)

    await log_audit(
        db, action="mall_salesman.rebind_employee",
        entity_type="MallUser", entity_id=sm.id,
        user=user, request=request,
        changes={
            "username": sm.username,
            "old_employee_id": old_employee_id,
            "old_employee_name": old_emp.name if old_emp else None,
            "new_employee_id": body.new_employee_id,
            "new_employee_name": new_emp.name,
            "reason": body.reason,
        },
    )

    # 通知业务员
    from app.services.notification_service import notify_mall_user
    await notify_mall_user(
        db, mall_user_id=sm.id,
        title="ERP 员工已换绑",
        content=(
            f"管理员将您的账号重新绑定到 ERP 员工 {new_emp.name}。"
            "请重新登录以加载最新的考勤/报销/KPI 数据。"
        ),
        entity_type="MallUser", entity_id=sm.id,
    )

    await db.flush()
    return {
        "success": True,
        "old_employee_id": old_employee_id,
        "new_employee_id": body.new_employee_id,
        "must_relogin": True,
    }


# =============================================================================
# 禁用 / 启用
# =============================================================================

class _ReasonBody(BaseModel):
    reason: Optional[str] = None


@router.post("/{salesman_id}/disable")
async def disable_salesman(
    salesman_id: str,
    body: _ReasonBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """禁用业务员。

    级联处理：
      - bump token_version 让所有在途 JWT 立即失效
      - 关闭 is_accepting_orders 防抢单
      - 已抢到但还没出库的订单（assigned）自动释放回独占期 / 开放池（assigned_salesman_id=null, status=pending_assignment）
      - 已出库/送达/待确认的订单不动，用 in_progress_count 汇报给 admin，需手动改派
      - 推荐关系不动（历史归属保留，新客户绑定前端会看到"该业务员已停用"）
    """
    from app.models.mall.base import MallOrderStatus
    from app.models.mall.order import MallOrder, MallOrderClaimLog

    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")
    if sm.status == MallUserStatus.DISABLED.value:
        return _salesman_dict(sm)

    sm.status = MallUserStatus.DISABLED.value
    sm.token_version = (sm.token_version or 0) + 1
    sm.is_accepting_orders = False

    # 1. assigned 状态订单（刚抢未发货）→ 释放回池子，记 claim log
    to_release = (await db.execute(
        select(MallOrder)
        .where(MallOrder.assigned_salesman_id == sm.id)
        .where(MallOrder.status == MallOrderStatus.ASSIGNED.value)
        .with_for_update()
    )).scalars().all()
    for o in to_release:
        o.status = MallOrderStatus.PENDING_ASSIGNMENT.value
        o.assigned_salesman_id = None
        o.claimed_at = None
        db.add(MallOrderClaimLog(
            order_id=o.id,
            action="release",
            from_salesman_id=sm.id,
            to_salesman_id=None,
            operator_id=user["sub"],
            reason=f"业务员被禁用自动释放：{body.reason or ''}",
        ))

    # 2. 已出库/送达/待确认的单子不动（会影响用户履约），只汇报数量提示 admin
    in_progress = (await db.execute(
        select(sa_func.count()).select_from(MallOrder)
        .where(MallOrder.assigned_salesman_id == sm.id)
        .where(MallOrder.status.in_([
            MallOrderStatus.SHIPPED.value,
            MallOrderStatus.DELIVERED.value,
            MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        ]))
    )).scalar() or 0

    await log_audit(
        db, action="mall_salesman.disable", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={
            "username": sm.username,
            "reason": body.reason,
            "released_assigned_orders": len(to_release),
            "in_progress_orders_need_reassign": int(in_progress),
        },
    )
    await db.flush()
    result = _salesman_dict(sm)
    result["released_assigned_orders"] = len(to_release)
    result["in_progress_orders_need_reassign"] = int(in_progress)
    return result


@router.post("/{salesman_id}/enable")
async def enable_salesman(
    salesman_id: str,
    body: _ReasonBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """启用被禁用的业务员。

    同时恢复 is_accepting_orders=True —— disable 时会关闭接单开关，如果 enable
    不重新打开，业务员账号虽然 active 但抢单池/派单都跳过他，实际等同"僵尸账号"
    """
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")
    if sm.status == MallUserStatus.ACTIVE.value:
        return _salesman_dict(sm)

    sm.status = MallUserStatus.ACTIVE.value
    sm.is_accepting_orders = True

    await log_audit(
        db, action="mall_salesman.enable", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request,
        changes={"username": sm.username, "reason": body.reason},
    )
    await db.flush()
    return _salesman_dict(sm)


# =============================================================================
# 重置密码
# =============================================================================

class _ResetPwdBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


@router.put("/{salesman_id}/reset-password")
async def reset_password(
    salesman_id: str,
    body: _ResetPwdBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    sm = await db.get(MallUser, salesman_id)
    if sm is None or sm.user_type != MallUserType.SALESMAN.value:
        raise HTTPException(status_code=404, detail="业务员不存在")

    sm.hashed_password = get_password_hash(body.new_password)
    sm.must_change_password = True
    sm.token_version = (sm.token_version or 0) + 1

    await log_audit(
        db, action="mall_salesman.reset_password", entity_type="MallUser",
        entity_id=sm.id, user=user, request=request, changes={"username": sm.username},
    )
    await db.flush()
    return {"success": True, "must_change_password": True}


# =============================================================================
# 辅助下拉
# =============================================================================

@router.get("/_helpers/employees")
async def list_bindable_employees(
    user: CurrentUser,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """列出可绑定的 employee（未绑定过 salesman，且 status=active）。"""
    require_role(user, "admin", "boss", "hr")

    # 已绑定过的 employee id
    bound_ids = [
        eid for eid, in (await db.execute(
            select(MallUser.linked_employee_id)
            .where(MallUser.user_type == MallUserType.SALESMAN.value)
            .where(MallUser.linked_employee_id.isnot(None))
        )).all()
    ]

    stmt = select(Employee).where(Employee.status == "active")
    if bound_ids:
        stmt = stmt.where(Employee.id.notin_(bound_ids))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where((Employee.name.ilike(kw)) | (Employee.phone.ilike(kw)))
    stmt = stmt.order_by(Employee.name).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {"id": e.id, "name": e.name, "phone": e.phone}
            for e in rows
        ]
    }


@router.get("/_helpers/brands")
async def list_brands_helper(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "hr")
    rows = (await db.execute(
        select(Brand).order_by(Brand.name)
    )).scalars().all()
    return {"records": [{"id": b.id, "name": b.name} for b in rows]}
