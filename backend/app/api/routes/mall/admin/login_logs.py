"""
/api/mall/admin/login-logs/*

C 端 / 业务员登录日志查询。

业务场景：
  - 监控登录行为（同一 IP 多账号 / 异地登录 / 频繁 refresh）
  - 识别"频繁来查价格"的恶意扒价行为 → /stats 接口按用户聚合
  - 审计配合：登录时间 + IP + UA + device_info + client_app 全量留存
"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, distinct, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.user import MallLoginLog, MallUser

router = APIRouter()


def _user_summary(u: Optional[MallUser]) -> Optional[dict]:
    if u is None:
        return None
    return {
        "id": u.id,
        "nickname": u.nickname,
        "username": u.username,
        "phone": u.phone,
        "user_type": u.user_type,
        "status": u.status,
    }


@router.get("")
async def list_login_logs(
    user: CurrentUser,
    user_id: Optional[str] = Query(None),
    user_keyword: Optional[str] = Query(None, description="昵称/用户名/手机号 模糊"),
    login_method: Optional[str] = Query(None, description="password/wechat/refresh"),
    client_app: Optional[str] = Query(None, description="mp_weixin/h5/app_android/app_ios"),
    ip: Optional[str] = Query(None, description="IP 精确匹配"),
    user_type: Optional[str] = Query(None, description="consumer/salesman 按用户类型过滤"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    stmt = select(MallLoginLog)
    if user_id:
        stmt = stmt.where(MallLoginLog.user_id == user_id)
    if login_method:
        stmt = stmt.where(MallLoginLog.login_method == login_method)
    if client_app:
        stmt = stmt.where(MallLoginLog.client_app == client_app)
    if ip:
        stmt = stmt.where(MallLoginLog.ip_address == ip)
    if date_from:
        try:
            stmt = stmt.where(MallLoginLog.login_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from 格式 YYYY-MM-DD")
    if date_to:
        try:
            stmt = stmt.where(
                MallLoginLog.login_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to 格式 YYYY-MM-DD")
    if user_type:
        # 用子查询过滤（user_type 字段在 MallUser 上）
        sub = select(MallUser.id).where(MallUser.user_type == user_type)
        stmt = stmt.where(MallLoginLog.user_id.in_(sub))
    if user_keyword:
        kw = f"%{user_keyword}%"
        sub = select(MallUser.id).where(
            or_(
                MallUser.nickname.ilike(kw),
                MallUser.username.ilike(kw),
                MallUser.phone.ilike(kw),
            )
        )
        stmt = stmt.where(MallLoginLog.user_id.in_(sub))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(MallLoginLog.login_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    user_ids = {r.user_id for r in rows}
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    return {
        "records": [
            {
                "id": r.id,
                "user": _user_summary(user_map.get(r.user_id)),
                "login_method": r.login_method,
                "client_app": r.client_app,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "device_info": r.device_info,
                "session_id": r.session_id,
                "login_at": r.login_at,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/export")
async def export_login_logs(
    user: CurrentUser,
    user_id: Optional[str] = Query(None),
    user_keyword: Optional[str] = Query(None),
    login_method: Optional[str] = Query(None),
    client_app: Optional[str] = Query(None),
    ip: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    max_rows: int = Query(default=10000, ge=1, le=50000),
    db: AsyncSession = Depends(get_db),
):
    """导出 CSV。"""
    require_role(user, "admin", "boss")
    stmt = select(MallLoginLog)
    if user_id:
        stmt = stmt.where(MallLoginLog.user_id == user_id)
    if login_method:
        stmt = stmt.where(MallLoginLog.login_method == login_method)
    if client_app:
        stmt = stmt.where(MallLoginLog.client_app == client_app)
    if ip:
        stmt = stmt.where(MallLoginLog.ip_address == ip)
    if date_from:
        try:
            stmt = stmt.where(MallLoginLog.login_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from 格式 YYYY-MM-DD")
    if date_to:
        try:
            stmt = stmt.where(
                MallLoginLog.login_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to 格式 YYYY-MM-DD")
    if user_type:
        sub = select(MallUser.id).where(MallUser.user_type == user_type)
        stmt = stmt.where(MallLoginLog.user_id.in_(sub))
    if user_keyword:
        kw = f"%{user_keyword}%"
        sub = select(MallUser.id).where(
            or_(
                MallUser.nickname.ilike(kw),
                MallUser.username.ilike(kw),
                MallUser.phone.ilike(kw),
            )
        )
        stmt = stmt.where(MallLoginLog.user_id.in_(sub))

    rows = (await db.execute(
        stmt.order_by(MallLoginLog.login_at.desc()).limit(max_rows)
    )).scalars().all()

    user_ids = {r.user_id for r in rows}
    user_map: dict[str, MallUser] = {}
    if user_ids:
        users = (await db.execute(
            select(MallUser).where(MallUser.id.in_(user_ids))
        )).scalars().all()
        user_map = {u.id: u for u in users}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "login_at", "username", "nickname", "phone", "user_type",
        "login_method", "client_app", "ip_address", "user_agent", "device_info",
    ])
    for r in rows:
        u = user_map.get(r.user_id)
        writer.writerow([
            r.login_at.isoformat(),
            (u.username if u else "") or "",
            (u.nickname if u else "") or "",
            (u.phone if u else "") or "",
            (u.user_type if u else "") or "",
            r.login_method,
            r.client_app,
            r.ip_address or "",
            r.user_agent or "",
            json.dumps(r.device_info, ensure_ascii=False) if r.device_info else "",
        ])
    content = buf.getvalue().encode("utf-8-sig")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="mall_login_logs_{stamp}.csv"',
        },
    )


@router.get("/stats")
async def login_stats(
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90),
    top_n: int = Query(default=100, ge=10, le=500),
    min_count: int = Query(default=0, ge=0, description="按 active_logins（password+wechat）过滤"),
    order_by: str = Query(default="active", description="active|total —— 排序口径"),
    db: AsyncSession = Depends(get_db),
):
    """按用户聚合最近 N 天登录次数。

    重要口径：
      - `active_logins = password + wechat`，真实的手工登录（扒价嫌疑以此为准）
      - `refresh_count` 单独统计 —— 小程序 token 过期会自动 refresh，此数不代表用户意愿
      - 默认按 active_logins 降序；order_by=total 时按 total（含 refresh）排
    字段：user / total / active_logins / password_count / wechat_count / refresh_count /
          distinct_ips / last_login_at
    """
    require_role(user, "admin", "boss")
    since = datetime.now(timezone.utc) - timedelta(days=days)

    password_sum = sa_func.sum(case((MallLoginLog.login_method == "password", 1), else_=0))
    wechat_sum = sa_func.sum(case((MallLoginLog.login_method == "wechat", 1), else_=0))
    refresh_sum = sa_func.sum(case((MallLoginLog.login_method == "refresh", 1), else_=0))
    active_sum = sa_func.sum(
        case((MallLoginLog.login_method.in_(("password", "wechat")), 1), else_=0)
    )

    order_expr = sa_func.count(MallLoginLog.id).desc() if order_by == "total" else active_sum.desc()

    stmt = (
        select(
            MallLoginLog.user_id,
            sa_func.count(MallLoginLog.id).label("total"),
            active_sum.label("active"),
            password_sum.label("password_count"),
            wechat_sum.label("wechat_count"),
            refresh_sum.label("refresh_count"),
            sa_func.count(distinct(MallLoginLog.ip_address)).label("distinct_ips"),
            sa_func.max(MallLoginLog.login_at).label("last_login_at"),
        )
        .where(MallLoginLog.login_at >= since)
        .group_by(MallLoginLog.user_id)
        .order_by(order_expr)
        .limit(top_n)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"records": [], "days": days}

    user_ids = [r[0] for r in rows]
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    records = []
    for uid, total, active, pwd_c, wx_c, refresh_c, ips, last_at in rows:
        active_n = int(active or 0)
        if active_n < min_count:
            continue
        records.append({
            "user": _user_summary(user_map.get(uid)),
            "total_logins": int(total or 0),
            "active_logins": active_n,
            "password_count": int(pwd_c or 0),
            "wechat_count": int(wx_c or 0),
            "refresh_count": int(refresh_c or 0),
            "distinct_ips": int(ips or 0),
            "last_login_at": last_at,
        })
    return {"records": records, "days": days, "order_by": order_by}


@router.get("/ip-stats")
async def ip_stats(
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90),
    top_n: int = Query(default=100, ge=10, le=500),
    min_accounts: int = Query(default=2, ge=1, description="仅返回登录 >= 该值个不同账号的 IP"),
    db: AsyncSession = Depends(get_db),
):
    """按 IP 聚合：哪些 IP 在登录多个账号？

    业务含义：
      - 同 IP 登录 >=3 个账号 → 账号农场 / 撞号攻击 / 公共网络（公司/网吧）
      - accounts 越多越可疑，搭配 active_logins 看扫号强度
      - 本地开发 127.0.0.1 会被列出，运营自己排除
    """
    require_role(user, "admin", "boss")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    active_sum = sa_func.sum(
        case((MallLoginLog.login_method.in_(("password", "wechat")), 1), else_=0)
    )

    stmt = (
        select(
            MallLoginLog.ip_address,
            sa_func.count(distinct(MallLoginLog.user_id)).label("accounts"),
            sa_func.count(MallLoginLog.id).label("total"),
            active_sum.label("active"),
            sa_func.max(MallLoginLog.login_at).label("last_login_at"),
        )
        .where(MallLoginLog.login_at >= since)
        .where(MallLoginLog.ip_address.isnot(None))
        .group_by(MallLoginLog.ip_address)
        .having(sa_func.count(distinct(MallLoginLog.user_id)) >= min_accounts)
        .order_by(sa_func.count(distinct(MallLoginLog.user_id)).desc(),
                  sa_func.count(MallLoginLog.id).desc())
        .limit(top_n)
    )
    rows = (await db.execute(stmt)).all()
    return {
        "records": [
            {
                "ip_address": ip,
                "accounts": int(accounts or 0),
                "total_logins": int(total or 0),
                "active_logins": int(active or 0),
                "last_login_at": last_at,
            }
            for ip, accounts, total, active, last_at in rows
        ],
        "days": days,
    }


@router.get("/ip-stats/{ip_address:path}/users")
async def ip_users(
    ip_address: str,
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """某 IP 最近 N 天登录的所有账号 + 每账号登录次数。

    用 :path 避免 IP 里的点被路由截断（mostly OK，但保险起见）。
    """
    require_role(user, "admin", "boss")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    active_sum = sa_func.sum(
        case((MallLoginLog.login_method.in_(("password", "wechat")), 1), else_=0)
    )

    stmt = (
        select(
            MallLoginLog.user_id,
            sa_func.count(MallLoginLog.id).label("total"),
            active_sum.label("active"),
            sa_func.max(MallLoginLog.login_at).label("last_login_at"),
        )
        .where(MallLoginLog.login_at >= since)
        .where(MallLoginLog.ip_address == ip_address)
        .group_by(MallLoginLog.user_id)
        .order_by(sa_func.count(MallLoginLog.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"ip_address": ip_address, "records": [], "days": days}

    user_ids = [r[0] for r in rows]
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    return {
        "ip_address": ip_address,
        "records": [
            {
                "user": _user_summary(user_map.get(uid)),
                "total_logins": int(total or 0),
                "active_logins": int(active or 0),
                "last_login_at": last_at,
            }
            for uid, total, active, last_at in rows
        ],
        "days": days,
    }


@router.get("/users/{user_id}")
async def user_login_history(
    user_id: str,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """某个用户的最近登录历史（用于 C 端用户详情页侧边 tab）。"""
    require_role(user, "admin", "boss")
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    rows = (await db.execute(
        select(MallLoginLog)
        .where(MallLoginLog.user_id == user_id)
        .order_by(MallLoginLog.login_at.desc())
        .limit(limit)
    )).scalars().all()
    return {
        "user": _user_summary(u),
        "records": [
            {
                "id": r.id,
                "login_method": r.login_method,
                "client_app": r.client_app,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "device_info": r.device_info,
                "login_at": r.login_at,
            }
            for r in rows
        ],
    }
