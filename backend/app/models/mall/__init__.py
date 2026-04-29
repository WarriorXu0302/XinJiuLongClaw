"""
Mall (小程序) ORM models.
"""
from app.models.mall.content import MallNotice
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import (
    MallCategory,
    MallCollection,
    MallProduct,
    MallProductSku,
    MallProductTag,
    MallProductTagRel,
)
from app.models.mall.user import (
    MallAddress,
    MallInviteCode,
    MallLoginLog,
    MallRegion,
    MallUser,
)

__all__ = [
    # user (M1)
    "MallUser", "MallAddress", "MallRegion", "MallInviteCode", "MallLoginLog",
    # product (M2)
    "MallCategory", "MallProductTag", "MallProductTagRel",
    "MallProduct", "MallProductSku", "MallCollection",
    # inventory (M2)
    "MallWarehouse", "MallInventory", "MallInventoryFlow",
    # content (M2)
    "MallNotice",
]
