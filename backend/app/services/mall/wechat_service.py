"""
微信小程序 API 封装：
  - access_token 获取 + 进程内缓存（7200s TTL，留 5min 余量）
  - wxacode.getUnlimited：生成小程序码（邀请码 scene）

未配 MP_APPID / MP_SECRET 时返回 mock 数据（同 wechat_code2session 的兼容策略）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── access_token 进程内缓存 ──────────────────────────────
# 生产部署多实例时建议换 Redis，单实例先用内存
_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


async def _get_access_token() -> str:
    """获取 access_token。进程缓存 + 并发锁，避免同时多个请求去拉。"""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 300:
        return _token_cache["token"]
    async with _token_lock:
        # double-check：另一个协程可能已经更新了
        now = time.time()
        if _token_cache["token"] and _token_cache["expires_at"] > now + 300:
            return _token_cache["token"]
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": settings.MP_APPID,
                    "secret": settings.MP_SECRET,
                },
            )
            data = r.json()
        if "access_token" not in data:
            raise HTTPException(
                status_code=502,
                detail=f"微信 access_token 获取失败：{data}",
            )
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 7200))
        return _token_cache["token"]


async def get_mp_unlimited_qrcode(
    *,
    scene: str,
    page: str = "pages/accountLogin/accountLogin",
    width: int = 430,
    env_version: str = "release",
) -> bytes:
    """调 wxacode.getUnlimited 生成小程序码（PNG 字节）。

    参数：
      scene         最多 32 字符，只能字母数字 + `!#$&'()*+,/:;=?@-._~`，业务侧传邀请码
      page          扫码打开的小程序页面路径。**不能带 query**，scene 在小程序端靠 uni.getLaunchOptionsSync 读
      width         图大小（280-1280），默认 430
      env_version   release / trial / develop

    dev mock：未配 MP_APPID 时返回一个占位 PNG（单色方块），前端依旧能下载 / 展示流程跑通。
    """
    # dev mock：无真实 APPID 时返 1x1 透明 PNG，让开发联调不炸
    if not settings.MP_APPID or not settings.MP_SECRET:
        return _mock_png()

    if not scene or len(scene) > 32:
        raise HTTPException(status_code=400, detail="scene 必须 1-32 字符")

    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"https://api.weixin.qq.com/wxa/getwxacodeunlimit?access_token={token}",
            json={
                "scene": scene,
                "page": page,
                "width": width,
                "env_version": env_version,
                "check_path": False,  # dev/trial 版 page 可能还没发布审核通过
            },
        )
    # 成功返回 image/png；失败返回 JSON
    content_type = r.headers.get("content-type", "")
    if "application/json" in content_type:
        err = r.json()
        raise HTTPException(
            status_code=502,
            detail=f"小程序码生成失败：{err}",
        )
    return r.content


def _mock_png() -> bytes:
    """极简 1x1 透明 PNG 占位（base64 解码）。真实开发接 APPID 后替换为真图。"""
    import base64
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )
