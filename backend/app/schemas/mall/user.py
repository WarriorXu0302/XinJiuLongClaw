"""Mall 用户 / 地址 / 区域 schemas。"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Address
# =============================================================================

class MallAddressWriteRequest(BaseModel):
    """新建 / 编辑 地址。

    业务要求：省市区名称必填（业务员抢单时导航需要完整地址）；
    area_code 也必填（某些地图 SDK 需要 adcode）。
    """
    receiver: str = Field(min_length=1, max_length=50)
    mobile: str = Field(min_length=11, max_length=20, pattern=r"^1[3-9]\d{9}$")
    province_code: Optional[str] = Field(default=None, max_length=12, alias="provinceId")
    city_code: Optional[str] = Field(default=None, max_length=12, alias="cityId")
    area_code: str = Field(min_length=1, max_length=12, alias="areaId")
    province: str = Field(min_length=1, max_length=50)
    city: str = Field(min_length=1, max_length=50)
    area: str = Field(min_length=1, max_length=50)
    addr: str = Field(min_length=3, max_length=200)
    is_default: bool = Field(default=False, alias="commonAddr")

    model_config = ConfigDict(populate_by_name=True)


class MallAddressVO(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    addr_id: str = Field(alias="id", serialization_alias="addrId")
    receiver: str
    mobile: str
    province_code: Optional[str] = Field(default=None, serialization_alias="provinceId")
    city_code: Optional[str] = Field(default=None, serialization_alias="cityId")
    area_code: Optional[str] = Field(default=None, serialization_alias="areaId")
    province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    addr: str
    is_default: bool = Field(default=False, serialization_alias="commonAddr")


# =============================================================================
# User profile
# =============================================================================

class MallUserProfileVO(BaseModel):
    """当前用户简要资料。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: str = Field(alias="id", serialization_alias="userId")
    nickname: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, serialization_alias="pic")
    phone: Optional[str] = None
    user_type: str = Field(serialization_alias="userType")
    has_referrer: bool = False
