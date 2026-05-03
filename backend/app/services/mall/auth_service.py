"""
Mall 鉴权服务。

核心职责：
  - 账密登录（复用 bcrypt）
  - 微信 code2session（MP_APPID 为空走 mock，方便开发）
  - 注册：原子消费 invite_code + 建 MallUser + 绑 referrer
  - 登录拦截：status='active' + token_version 一致
  - 登录日志落库
  - bump_token_version：封禁/换绑时 +1 吊销所有在途 token
"""
import httpx
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_mall_access_token,
    create_mall_refresh_token,
    decode_mall_token,
    get_password_hash,
    verify_password,
)
from app.models.mall.base import (
    MallLoginMethod,
    MallUserStatus,
    MallUserType,
)
from app.models.mall.user import MallAddress, MallLoginLog, MallUser
from app.services.mall.invite_service import (
    consume_invite_code,
    mark_invite_used,
)
from app.services.mall.validators import (
    assert_mall_user_active,
    assert_mall_user_approved,
    assert_salesman_linked_employee_active,
    assert_salesman_linked_to_employee,
)


# =============================================================================
# 查询 helpers
# =============================================================================

async def get_mall_user_by_id(db: AsyncSession, user_id: str) -> Optional[MallUser]:
    return (
        await db.execute(select(MallUser).where(MallUser.id == user_id))
    ).scalar_one_or_none()


async def get_mall_user_by_username(db: AsyncSession, username: str) -> Optional[MallUser]:
    return (
        await db.execute(select(MallUser).where(MallUser.username == username))
    ).scalar_one_or_none()


async def get_mall_user_by_openid(db: AsyncSession, openid: str) -> Optional[MallUser]:
    return (
        await db.execute(select(MallUser).where(MallUser.openid == openid))
    ).scalar_one_or_none()


# =============================================================================
# 账密登录
# =============================================================================

async def authenticate_by_password(
    db: AsyncSession, username: str, password: str
) -> MallUser:
    """账密登录。失败 401，停用 403，未审批 403（带 application_id），linked employee 停用 403。"""
    user = await get_mall_user_by_username(db, username)
    if user is None or not user.hashed_password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    assert_mall_user_active(user)
    assert_mall_user_approved(user)
    await assert_salesman_linked_employee_active(db, user)
    return user


# =============================================================================
# 微信登录（未配 MP_APPID 时走 mock）
# =============================================================================

async def wechat_code2session(code: str) -> dict[str, Any]:
    """调 https://api.weixin.qq.com/sns/jscode2session。

    开发环境下未配 MP_APPID/MP_SECRET 时返回 mock openid，方便本地测试：
    - 如果 code 以 "devmock:" 开头，后面的字符串原样作为 openid（前端可固定传
      同一个 openid 复用账号 —— 注册/登录/换设备调试）
    - 否则用 code 前 12 位做 openid 前缀（每次 uni.login 返的 code 不同 → openid 不同，
      适合 smoke test 走"新用户注册"路径，但无法复用账号登录，dev 时用 devmock: 前缀）
    """
    if not settings.MP_APPID or not settings.MP_SECRET:
        if code.startswith("devmock:"):
            return {
                "openid": f"mock_openid_{code[len('devmock:'):]}",
                "session_key": "mock_session_key",
                "unionid": None,
            }
        return {
            "openid": f"mock_openid_{code[:12]}",
            "session_key": "mock_session_key",
            "unionid": None,
        }

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.MP_APPID,
                "secret": settings.MP_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
        data = r.json()
        if "errcode" in data and data["errcode"] != 0:
            raise HTTPException(
                status_code=400, detail=f"微信登录失败：{data.get('errmsg')}"
            )
        return data


# =============================================================================
# 注册
# =============================================================================

async def register_mall_user(
    db: AsyncSession,
    *,
    invite_code: str,
    real_name: str,
    contact_phone: str,
    delivery_address: str,
    business_license_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    openid: Optional[str] = None,
    unionid: Optional[str] = None,
    phone: Optional[str] = None,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
    address_parts: Optional[dict] = None,
) -> MallUser:
    """事务内原子：消费邀请码 + 建 MallUser（application_status=pending）+ 绑定推荐人。

    新账号进入 pending_approval 状态，由 ERP 管理员审批后才能登录。
    username / openid 必须至少一个；有 username 时 password 必传。
    审批资料（real_name / contact_phone / delivery_address / business_license_url）必填。
    """
    from app.models.mall.base import MallUserApplicationStatus

    if not invite_code:
        raise HTTPException(status_code=400, detail="邀请码必填")
    if not (username or openid):
        raise HTTPException(status_code=400, detail="必须提供账号或微信 openid")
    if username and not password:
        raise HTTPException(status_code=400, detail="账密注册必须带密码")
    if not (real_name and contact_phone and delivery_address and business_license_url):
        raise HTTPException(status_code=400, detail="姓名/电话/配送地址/营业执照均必填")

    # 1. 前置软查（友好错误提示，不作为并发保护，并发保护靠 DB 唯一约束）
    if username and await get_mall_user_by_username(db, username):
        raise HTTPException(status_code=409, detail="账号已存在")
    if openid and await get_mall_user_by_openid(db, openid):
        raise HTTPException(status_code=409, detail="该微信已注册")

    # 2. 锁定邀请码（FOR UPDATE），校验合法性
    invite = await consume_invite_code(db, invite_code)

    # 3. 建用户。pending 审批中，token_version=0 表示无有效 token（不会被签发）
    user = MallUser(
        username=username,
        hashed_password=get_password_hash(password) if password else None,
        openid=openid,
        unionid=unionid,
        phone=phone,
        nickname=nickname or username or real_name or "新用户",
        avatar_url=avatar_url,
        status=MallUserStatus.ACTIVE.value,
        user_type=MallUserType.CONSUMER.value,
        token_version=1,
        referrer_salesman_id=invite.issuer_salesman_id,
        referrer_bound_at=datetime.now(timezone.utc),
        # ─── 审批相关字段 ───
        application_status=MallUserApplicationStatus.PENDING.value,
        real_name=real_name,
        contact_phone=contact_phone,
        delivery_address=delivery_address,
        business_license_url=business_license_url,
    )
    db.add(user)
    try:
        await db.flush()  # 拿 id；并发唯一撞库在这里抛
    except IntegrityError as e:
        # 不手动 rollback —— get_mall_db 依赖在请求结束时会统一 rollback；
        # 手动 rollback 会释放 consume_invite_code 的 FOR UPDATE 锁，
        # 让并发注册拿到同一张邀请码
        msg = str(e.orig) if e.orig else str(e)
        if "uq_mall_users_username" in msg or "mall_users_username" in msg:
            raise HTTPException(status_code=409, detail="账号已存在") from e
        if "ix_mall_users_openid" in msg or "mall_users_openid" in msg:
            raise HTTPException(status_code=409, detail="该微信已注册") from e
        raise HTTPException(status_code=409, detail="注册冲突，请稍后重试") from e

    # 4. 回填邀请码 used 状态
    await mark_invite_used(db, invite, user.id)

    # 5. 自动生成默认收货地址（审批未通过也写；通过后登录即可直接用）
    #    没传 address_parts 时按 delivery_address 字段兜底存为 addr
    parts = address_parts or {}
    # pydantic model 和 dict 都兼容
    if hasattr(parts, "model_dump"):
        parts = parts.model_dump()
    addr = MallAddress(
        user_id=user.id,
        receiver=real_name,
        mobile=contact_phone,
        province_code=parts.get("provinceCode") if parts else None,
        city_code=parts.get("cityCode") if parts else None,
        area_code=parts.get("areaCode") if parts else None,
        province=parts.get("province") if parts else None,
        city=parts.get("city") if parts else None,
        area=parts.get("area") if parts else None,
        addr=(parts.get("detail") or delivery_address)[:200] if parts else delivery_address[:200],
        is_default=True,
    )
    db.add(addr)
    await db.flush()

    return user


# =============================================================================
# Token 签发（带 version 校验）
# =============================================================================

def issue_tokens(user: MallUser) -> dict[str, Any]:
    """签发 access + refresh，返回响应字典。"""
    return {
        "token": create_mall_access_token(user),
        "refresh_token": create_mall_refresh_token(user),
        "expires_in": settings.MALL_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user_type": user.user_type,
        "user_id": user.id,
        "nickname": user.nickname,
        "must_change_password": user.must_change_password,
        # 门店店员标记（前端据此显示收银入口；非店员为 null）
        "assigned_store_id": user.assigned_store_id,
    }


async def verify_token_and_load_user(
    db: AsyncSession, payload: dict[str, Any]
) -> MallUser:
    """从 payload（已 decode_mall_token 校验过 JWT 本身）加载 user 并校验 token_version / status。

    注意：业务路由里从 CurrentMallUser payload 拿 sub 后调用此函数获取"新鲜"的 user 对象。
    """
    user = await get_mall_user_by_id(db, payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在")
    if user.token_version != payload.get("token_version"):
        raise HTTPException(
            status_code=401, detail="Token 已失效，请重新登录"
        )
    assert_mall_user_active(user)
    return user


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> dict[str, Any]:
    """用 refresh_token 换新一对 token。"""
    payload = decode_mall_token(refresh_token, expected_type="mall_refresh")
    user = await verify_token_and_load_user(db, payload)
    # 业务员额外校验：绑定关系存在 + linked employee 仍是 active
    assert_salesman_linked_to_employee(user)
    await assert_salesman_linked_employee_active(db, user)
    return issue_tokens(user)


async def bump_token_version(db: AsyncSession, user_id: str) -> None:
    """封禁/换绑/停用时 +1。所有在途 JWT 下一次解码立即失效。"""
    user = await get_mall_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.token_version = (user.token_version or 0) + 1
    await db.flush()


# =============================================================================
# 登录日志
# =============================================================================

def _extract_client_app(request: Optional[Request], explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    if request is None:
        return "h5"
    ua = (request.headers.get("user-agent") or "").lower()
    if "micromessenger" in ua:
        return "mp_weixin"
    if "android" in ua:
        return "app_android"
    if "iphone" in ua or "ios" in ua:
        return "app_ios"
    return "h5"


async def record_login_log(
    db: AsyncSession,
    *,
    user: MallUser,
    request: Optional[Request] = None,
    login_method: str = MallLoginMethod.PASSWORD.value,
    client_app: Optional[str] = None,
    device_info: Optional[dict] = None,
) -> None:
    """登录日志 + last_active_at 更新。

    日志写入失败**不阻塞登录**：任何异常都被吞掉 + 打 warn 日志。
    """
    import logging
    logger = logging.getLogger(__name__)

    ip = None
    ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")

    # 用 SAVEPOINT 包住，日志/last_active_at 出错只回滚这一段，不影响登录主流程
    try:
        async with db.begin_nested():
            log = MallLoginLog(
                user_id=user.id,
                login_method=login_method,
                client_app=_extract_client_app(request, client_app),
                ip_address=ip,
                user_agent=(ua or "")[:500] or None,
                device_info=device_info,
            )
            db.add(log)
            user.last_active_at = datetime.now(timezone.utc)
            # begin_nested 退出时自动 flush + release savepoint
    except Exception as exc:
        logger.warning("mall_login_log 写入失败，忽略不阻塞登录: %s", exc)
