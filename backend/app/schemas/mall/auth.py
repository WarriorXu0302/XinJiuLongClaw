"""
Mall 鉴权相关 Pydantic schemas。

对应路由 /api/mall/auth/*
"""
from typing import Optional

from pydantic import BaseModel, Field


class MallLoginPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)
    device_info: Optional[dict] = None


class MallRegisterRequest(BaseModel):
    """C 端账密注册。必传 invite_code。"""
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    # 邀请码固定 8 位，但宽松接收 8-16 容忍空格；service 层会 strip+upper 归一化
    invite_code: str = Field(min_length=8, max_length=16)
    nickname: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    device_info: Optional[dict] = None


class MallWechatLoginRequest(BaseModel):
    """已注册的微信用户登录。用 code 换 openid 后匹配已有账号。"""
    code: str = Field(min_length=1, max_length=128)
    device_info: Optional[dict] = None


class MallWechatRegisterRequest(BaseModel):
    """首次微信注册。必传 invite_code。"""
    code: str = Field(min_length=1, max_length=128)
    invite_code: str = Field(min_length=8, max_length=16)
    nickname: Optional[str] = Field(default=None, max_length=100)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    device_info: Optional[dict] = None


class MallRefreshRequest(BaseModel):
    refresh_token: str


class MallTokenResponse(BaseModel):
    token: str
    refresh_token: str
    expires_in: int
    user_type: str
    user_id: str
    nickname: Optional[str] = None
    must_change_password: bool = False
