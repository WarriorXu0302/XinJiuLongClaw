"""
/api/mall/salesman/profile

GET  /                     当前业务员资料
PUT  /accepting-orders     切换接单开关
PUT  /payment-qr           更新收款二维码
PUT  /default-warehouse    设置默认仓
POST /change-password      改密码（主动或首次登录强制）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import (
    CurrentMallUser,
    get_password_hash,
    verify_password,
)
from app.services.audit_service import log_audit
from app.services.mall import auth_service

router = APIRouter()


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


def _profile_dict(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "user_type": user.user_type,
        "is_accepting_orders": user.is_accepting_orders,
        "wechat_qr_url": user.wechat_qr_url,
        "alipay_qr_url": user.alipay_qr_url,
        "default_warehouse_id": user.default_warehouse_id,
        "linked_employee_id": user.linked_employee_id,
        "assigned_brand_id": user.assigned_brand_id,
        "must_change_password": user.must_change_password,
    }


@router.get("")
async def get_profile(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    return _profile_dict(user)


class _AcceptBody(BaseModel):
    enabled: bool


@router.put("/accepting-orders")
async def set_accepting(
    body: _AcceptBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    user.is_accepting_orders = body.enabled
    await db.flush()
    return {"is_accepting_orders": user.is_accepting_orders}


class _QrBody(BaseModel):
    wechat_qr_url: Optional[str] = Field(default=None, max_length=500)
    alipay_qr_url: Optional[str] = Field(default=None, max_length=500)


@router.put("/payment-qr")
async def set_payment_qr(
    body: _QrBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    if body.wechat_qr_url is not None:
        user.wechat_qr_url = body.wechat_qr_url or None
    if body.alipay_qr_url is not None:
        user.alipay_qr_url = body.alipay_qr_url or None
    await db.flush()
    return {
        "wechat_qr_url": user.wechat_qr_url,
        "alipay_qr_url": user.alipay_qr_url,
    }


class _DefaultWhBody(BaseModel):
    warehouse_id: Optional[str] = Field(default=None, max_length=36)


@router.put("/default-warehouse")
async def set_default_warehouse(
    body: _DefaultWhBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    user.default_warehouse_id = body.warehouse_id or None
    await db.flush()
    return {"default_warehouse_id": user.default_warehouse_id}


class _ChangePwdBody(BaseModel):
    old_password: Optional[str] = None  # must_change_password=True 时允许省略
    new_password: str = Field(min_length=8, max_length=128)


def _assert_password_strength(pwd: str) -> None:
    """至少 8 位 + 同时含字母和数字；防止 '12345678' 这种纯数字。"""
    has_alpha = any(c.isalpha() for c in pwd)
    has_digit = any(c.isdigit() for c in pwd)
    if not (has_alpha and has_digit):
        raise HTTPException(
            status_code=400, detail="密码必须同时包含字母和数字（至少 8 位）"
        )


@router.post("/change-password")
async def change_password(
    body: _ChangePwdBody,
    current: CurrentMallUser,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    _assert_password_strength(body.new_password)
    was_forced = user.must_change_password
    if user.hashed_password and not user.must_change_password:
        if not body.old_password:
            raise HTTPException(status_code=400, detail="旧密码必填")
        if not verify_password(body.old_password, user.hashed_password):
            raise HTTPException(status_code=401, detail="旧密码错误")
        # 禁止和旧密码相同
        if verify_password(body.new_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="新密码不能和旧密码相同")
    user.hashed_password = get_password_hash(body.new_password)
    user.must_change_password = False
    # 改密码后 bump token_version，所有旧 token 失效
    user.token_version = (user.token_version or 0) + 1

    # 合规审计（密码修改属于账户安全敏感操作）
    await log_audit(
        db, action="mall_user.change_password",
        entity_type="MallUser", entity_id=user.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={"forced_first_login": was_forced},
    )

    await db.flush()
    return {"success": True}
