"""
Mall (小程序) ORM models.
"""
from app.models.mall.content import MallNotice
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryBarcode,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.order import (
    MallAttachment,
    MallCartItem,
    MallCustomerSkipLog,
    MallOrder,
    MallOrderClaimLog,
    MallOrderItem,
    MallPayment,
    MallShipment,
    MallSkipAlert,
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
    # inventory (M2 + M4a barcode)
    "MallWarehouse", "MallInventory", "MallInventoryFlow",
    "MallInventoryBarcode",
    # content (M2)
    "MallNotice",
    # order (M3)
    "MallCartItem", "MallOrder", "MallOrderItem", "MallOrderClaimLog",
    # fulfilment (M4a)
    "MallPayment", "MallShipment", "MallAttachment",
    "MallCustomerSkipLog", "MallSkipAlert",
]
