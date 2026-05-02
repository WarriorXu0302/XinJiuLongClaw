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
    MallApplicationResponse,
    MallApplicationStatusResponse,
    MallLoginPasswordRequest,
    MallRefreshRequest,
    MallRegisterRequest,
    MallTokenResponse,
    MallWechatLoginRequest,
    MallWechatRegisterRequest,
)
from app.core.database import admin_session_factory
from app.services.audit_service import log_audit
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
    try:
        user = await auth_service.authenticate_by_password(
            db, payload.username, payload.password
        )
    except HTTPException as exc:
        # 审计登录失败（账户安全：识别暴力破解 / 撞库）
        # 用独立 session 写，不污染主事务（主事务会 rollback + raise）
        async with admin_session_factory() as audit_session:
            existing = await auth_service.get_mall_user_by_username(
                audit_session, payload.username
            )
            await log_audit(
                audit_session, action="mall_user.login_failed",
                entity_type="MallUser",
                entity_id=existing.id if existing else None,
                mall_user_id=existing.id if existing else None,
                actor_type="mall_user" if existing else "anonymous",
                request=request,
                changes={
                    "username_tried": payload.username,
                    "user_exists": bool(existing),
                    "status_code": exc.status_code,
                    "reason": exc.detail,
                },
            )
            await audit_session.commit()
        raise
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

@router.post("/register", response_model=MallApplicationResponse)
async def register(
    payload: MallRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    """账密注册。**不签发 token**，账户进入 pending_approval 审批流。

    用户需凭 application_id 轮询 /application-status 查审批结果；
    审批通过后用 /login-password 登录。
    """
    user = await auth_service.register_mall_user(
        db,
        invite_code=payload.invite_code,
        username=payload.username,
        password=payload.password,
        phone=payload.phone,
        nickname=payload.nickname,
        real_name=payload.real_name,
        contact_phone=payload.contact_phone,
        delivery_address=payload.delivery_address,
        business_license_url=payload.business_license_url,
    )
    await log_audit(
        db, action="mall_user.register",
        entity_type="MallUser", entity_id=user.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "method": "password",
            "username": payload.username,
            "real_name": payload.real_name,
            "contact_phone": payload.contact_phone,
            "referrer_salesman_id": user.referrer_salesman_id,
        },
    )
    # 通知 admin/boss 待审批
    await _notify_admins_new_application(db, user)
    return MallApplicationResponse(
        application_id=user.id,
        application_status=user.application_status,
        username=user.username,
        nickname=user.nickname,
    )


async def _notify_admins_new_application(db, user):
    """通知 admin/boss 有新注册待审批。"""
    from app.services.notification_service import notify_roles
    await notify_roles(
        db, role_codes=["admin", "boss"],
        title="新用户注册待审批",
        content=f"{user.real_name or user.nickname}（{user.contact_phone}）提交了注册申请，请在『商城用户』→待审批 中处理",
        entity_type="MallUser", entity_id=user.id,
    )


# =============================================================================
# 审批状态查询（匿名）
# =============================================================================

@router.get("/application-status", response_model=MallApplicationStatusResponse)
async def get_application_status(
    application_id: str,
    db: AsyncSession = Depends(get_mall_db),
):
    """前端审批中页轮询；application_id = mall_users.id（注册时 MallApplicationResponse 返的）。

    匿名访问：用户还没 token，但 application_id 本身是 UUID 不可猜，
    加上端点只返"状态 + 驳回理由"不泄漏敏感信息（不返姓名/地址/营业执照）。
    """
    from sqlalchemy import select
    from app.models.mall.user import MallUser
    row = (await db.execute(
        select(MallUser).where(MallUser.id == application_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    return MallApplicationStatusResponse(
        application_id=row.id,
        application_status=row.application_status,
        rejection_reason=row.rejection_reason,
        approved_at=row.approved_at.isoformat() if row.approved_at else None,
    )


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
    from app.services.mall.validators import assert_mall_user_approved
    assert_mall_user_approved(user)

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

@router.post("/wechat-register")
async def wechat_register(
    payload: MallWechatRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    """扫码/首次微信注册。

    - 已注册用户：绕过审批直接登录（签 token）。邀请码不消耗
    - 新用户：建 application_status=pending 的账号，**不签 token**，返 MallApplicationResponse
      由 admin/boss 审批后才能登录
    """
    session = await auth_service.wechat_code2session(payload.code)
    openid = session.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail="微信登录失败：未获取 openid")

    # 已注册用户 → 直接登录（不消耗邀请码）
    existing = await auth_service.get_mall_user_by_openid(db, openid)
    if existing is not None:
        from app.services.mall.validators import assert_mall_user_active
        assert_mall_user_active(existing)
        # 审批状态也要过：已注册但还 pending 的复扫，拒登录
        from app.models.mall.base import MallUserApplicationStatus
        if existing.application_status != MallUserApplicationStatus.APPROVED.value:
            raise HTTPException(
                status_code=403,
                detail={
                    "reason": "application_not_approved",
                    "application_id": existing.id,
                    "application_status": existing.application_status,
                    "rejection_reason": existing.rejection_reason,
                },
            )
        await auth_service.record_login_log(
            db, user=existing, request=request,
            login_method=MallLoginMethod.WECHAT.value,
            device_info=payload.device_info,
        )
        return auth_service.issue_tokens(existing)

    user = await auth_service.register_mall_user(
        db,
        invite_code=payload.invite_code,
        openid=openid,
        unionid=session.get("unionid"),
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
        real_name=payload.real_name,
        contact_phone=payload.contact_phone,
        delivery_address=payload.delivery_address,
        business_license_url=payload.business_license_url,
    )
    await log_audit(
        db, action="mall_user.register",
        entity_type="MallUser", entity_id=user.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "method": "wechat",
            "openid_hash": openid[:8] + "***",
            "real_name": payload.real_name,
            "contact_phone": payload.contact_phone,
            "referrer_salesman_id": user.referrer_salesman_id,
        },
    )
    await _notify_admins_new_application(db, user)
    return MallApplicationResponse(
        application_id=user.id,
        application_status=user.application_status,
        username=user.username,
        nickname=user.nickname,
    )


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
