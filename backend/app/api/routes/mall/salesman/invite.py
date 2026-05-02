"""
/api/mall/salesman/invite-codes

POST /                 签发邀请码
GET  /history?limit=   最近邀请码（含已用/已过期）
POST /{id}/invalidate  业务员作废未用邀请码
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.services.mall import auth_service, invite_service

router = APIRouter()


def _require_salesman(current):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")


def _build_qr_svg(code: str) -> tuple[str, str]:
    """为邀请码生成 SVG 二维码 + 深链接。

    深链接：微信扫码 → 跳 H5 注册页 → 自动填 code。
    SVG 前端可直接 v-html 渲染，不依赖小程序端 QR 库。
    """
    import io
    import qrcode
    import qrcode.image.svg

    base = settings.MALL_INVITE_DEEPLINK_BASE or "https://mall.xinjiulong.com/register"
    url = f"{base}?code={code}"
    qr = qrcode.QRCode(
        version=None,  # 自动选版本
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8"), url


def _invite_to_dict(row) -> dict:
    if row.invalidated_at is not None:
        status = "invalidated"
    elif row.used_at is not None:
        status = "used"
    else:
        status = "expired" if row.expires_at <= datetime.now(timezone.utc) else "pending"
    return {
        "id": row.id,
        "code": row.code,
        "expires_at": row.expires_at,
        "used_at": row.used_at,
        "used_by_user_id": row.used_by_user_id,
        "invalidated_at": row.invalidated_at,
        "created_at": row.created_at,
        "status": status,
    }


@router.post("")
async def create(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    invite = await invite_service.generate_invite_code(db, user)
    # 附带"今日剩余额度"给前端展示
    today_used = await invite_service._count_today_codes(db, user.id)
    result = _invite_to_dict(invite)
    result["remaining_today"] = max(
        0, settings.MALL_INVITE_CODE_DAILY_LIMIT - today_used,
    )
    qr_svg, deeplink = _build_qr_svg(invite.code)
    result["qr_svg"] = qr_svg
    result["deeplink"] = deeplink
    return result


@router.get("/history")
async def history(
    current: CurrentMallUser,
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = await invite_service.list_recent_codes(db, user, limit=limit)
    # 批量拉使用人昵称
    from sqlalchemy import select
    from app.models.mall.user import MallUser
    used_by_ids = list({r.used_by_user_id for r in rows if r.used_by_user_id})
    nick_map: dict[str, str] = {}
    if used_by_ids:
        users = (await db.execute(
            select(MallUser.id, MallUser.nickname, MallUser.username)
            .where(MallUser.id.in_(used_by_ids))
        )).all()
        nick_map = {u.id: (u.nickname or u.username) for u in users}
    records = []
    for r in rows:
        d = _invite_to_dict(r)
        d["used_by_nick"] = nick_map.get(r.used_by_user_id) if r.used_by_user_id else None
        records.append(d)
    return {"records": records}


@router.get("/{code_id}/qr-mp")
async def get_mp_qrcode(
    code_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    """为指定邀请码生成**小程序码** PNG。

    使用场景：业务员点"下载海报/分享二维码"，客户用微信扫 → 直接打开小程序
    `pages/register-by-scan` → 客户确认授权 → 后端拿到 scene=<code> + wx_code
    → 调 /api/mall/auth/wechat-register 完成一键注册。

    未配 MP_APPID 时返 mock 占位 PNG（跑通前端流程用）。
    """
    from fastapi import Response
    from sqlalchemy import select
    from app.models.mall.user import MallInviteCode
    from app.services.mall.wechat_service import get_mp_unlimited_qrcode

    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    row = (await db.execute(
        select(MallInviteCode).where(MallInviteCode.id == code_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    if row.issuer_salesman_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问他人邀请码")
    if row.used_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已使用")
    if row.invalidated_at is not None:
        raise HTTPException(status_code=400, detail="邀请码已作废")
    if row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="邀请码已过期")

    png = await get_mp_unlimited_qrcode(
        scene=row.code,
        page=settings.MALL_INVITE_SCAN_PAGE,
    )
    return Response(content=png, media_type="image/png", headers={
        "Cache-Control": "private, max-age=300",  # 客户端缓存 5 分钟
    })


class _InvalidateBody(BaseModel):
    reason: Optional[str] = None


@router.post("/{code_id}/invalidate")
async def invalidate(
    code_id: str,
    current: CurrentMallUser,
    request: Request,
    body: Optional[_InvalidateBody] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    _require_salesman(current)
    user = await auth_service.verify_token_and_load_user(db, current)
    row = await invite_service.invalidate_invite_code(
        db, user, code_id, reason=body.reason if body else None,
        request=request,
    )
    return _invite_to_dict(row)
