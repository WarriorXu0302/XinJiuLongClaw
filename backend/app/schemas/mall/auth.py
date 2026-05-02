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
    """C 端账密注册。必传 invite_code + 审批资料。

    注册成功不签发 token（account 进入 application_status=pending），
    由 ERP 管理员审批通过后才能登录。
    """
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    invite_code: str = Field(min_length=8, max_length=16)
    # ─── 审批必填 ───
    real_name: str = Field(min_length=1, max_length=50)
    contact_phone: str = Field(min_length=7, max_length=20)
    delivery_address: str = Field(min_length=5, max_length=500)
    business_license_url: str = Field(min_length=1, max_length=500)

    nickname: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    device_info: Optional[dict] = None


class MallWechatLoginRequest(BaseModel):
    """已注册的微信用户登录。用 code 换 openid 后匹配已有账号。"""
    code: str = Field(min_length=1, max_length=128)
    device_info: Optional[dict] = None


class MallWechatRegisterRequest(BaseModel):
    """首次微信注册。必传 invite_code + 审批资料。"""
    code: str = Field(min_length=1, max_length=128)
    invite_code: str = Field(min_length=8, max_length=16)
    # ─── 审批必填 ───
    real_name: str = Field(min_length=1, max_length=50)
    contact_phone: str = Field(min_length=7, max_length=20)
    delivery_address: str = Field(min_length=5, max_length=500)
    business_license_url: str = Field(min_length=1, max_length=500)

    nickname: Optional[str] = Field(default=None, max_length=100)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    device_info: Optional[dict] = None


class MallApplicationResponse(BaseModel):
    """注册提交成功响应。不签 token，前端轮询状态查询端点判断审批结果。"""
    application_id: str
    application_status: str
    username: Optional[str] = None
    nickname: Optional[str] = None


class MallApplicationStatusResponse(BaseModel):
    """审批状态查询响应。"""
    application_id: str
    application_status: str
    rejection_reason: Optional[str] = None
    approved_at: Optional[str] = None


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
