"""
/api/mall/auth/*

端点：
  POST /login-password       账密登录（业务员 + 有账密的 consumer）
  POST /register             邀请码注册（必传 invite_code）
  POST /wechat-login         微信 code → 已注册用户登录（未注册返 404 引导走注册）
  POST /wechat-register      首次微信注册（必传 invite_code）
  POST /refresh              刷新 token
  POST /logout               退出登录（bump token_version，所有在途 JWT 失效）

协议：ERP 原生（200 + body；失败 HTTPException → `{detail}`）
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.base import MallLoginMethod
from app.schemas.mall.auth import (
    MallLoginPasswordRequest,
    MallRefreshRequest,
    MallRegisterRequest,
    MallTokenResponse,
    MallWechatLoginRequest,
    MallWechatRegisterRequest,
)
from app.services.mall import auth_service
from app.services.mall.validators import assert_mall_user_active

router = APIRouter()


# =============================================================================
# 账密登录
# =============================================================================

@router.post("/login-password", response_model=MallTokenResponse)
async def login_password(
    payload: MallLoginPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.authenticate_by_password(
        db, payload.username, payload.password
    )
    await auth_service.record_login_log(
        db,
        user=user,
        request=request,
        login_method=MallLoginMethod.PASSWORD.value,
        device_info=payload.device_info,
    )
    return auth_service.issue_tokens(user)


# =============================================================================
# 账密注册
# =============================================================================

@router.post("/register", response_model=MallTokenResponse)
async def register(
    payload: MallRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.register_mall_user(
        db,
        invite_code=payload.invite_code,
        username=payload.username,
        password=payload.password,
        phone=payload.phone,
        nickname=payload.nickname,
    )
    await auth_service.record_login_log(
        db,
        user=user,
        request=request,
        login_method=MallLoginMethod.PASSWORD.value,
        device_info=payload.device_info,
    )
    return auth_service.issue_tokens(user)


# =============================================================================
# 微信登录
# =============================================================================

@router.post("/wechat-login", response_model=MallTokenResponse)
async def wechat_login(
    payload: MallWechatLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    session = await auth_service.wechat_code2session(payload.code)
    openid = session.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail="微信登录失败：未获取 openid")

    user = await auth_service.get_mall_user_by_openid(db, openid)
    if user is None:
        raise HTTPException(
            status_code=404, detail="账号未注册，请输入邀请码完成注册"
        )
    assert_mall_user_active(user)

    await auth_service.record_login_log(
        db,
        user=user,
        request=request,
        login_method=MallLoginMethod.WECHAT.value,
        device_info=payload.device_info,
    )
    return auth_service.issue_tokens(user)


# =============================================================================
# 微信注册
# =============================================================================

@router.post("/wechat-register", response_model=MallTokenResponse)
async def wechat_register(
    payload: MallWechatRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    session = await auth_service.wechat_code2session(payload.code)
    openid = session.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail="微信登录失败：未获取 openid")

    user = await auth_service.register_mall_user(
        db,
        invite_code=payload.invite_code,
        openid=openid,
        unionid=session.get("unionid"),
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
    )
    await auth_service.record_login_log(
        db,
        user=user,
        request=request,
        login_method=MallLoginMethod.WECHAT.value,
        device_info=payload.device_info,
    )
    return auth_service.issue_tokens(user)


# =============================================================================
# 刷新 token
# =============================================================================

@router.post("/refresh", response_model=MallTokenResponse)
async def refresh(
    payload: MallRefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    tokens = await auth_service.refresh_tokens(db, payload.refresh_token)
    # 记一条 refresh 日志
    user = await auth_service.get_mall_user_by_id(db, tokens["user_id"])
    if user:
        await auth_service.record_login_log(
            db,
            user=user,
            request=request,
            login_method=MallLoginMethod.REFRESH.value,
        )
    return tokens


# =============================================================================
# 退出登录：bump token_version，所有在途 token 失效
# =============================================================================

@router.post("/logout")
async def logout(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    await auth_service.bump_token_version(db, current["sub"])
    return {"success": True}
