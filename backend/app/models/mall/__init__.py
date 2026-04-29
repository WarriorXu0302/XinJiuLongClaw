"""
Mall (小程序) ORM models.
"""
from app.models.mall.user import (
    MallAddress,
    MallInviteCode,
    MallLoginLog,
    MallRegion,
    MallUser,
)

__all__ = [
    "MallUser", "MallAddress", "MallRegion", "MallInviteCode", "MallLoginLog",
]
