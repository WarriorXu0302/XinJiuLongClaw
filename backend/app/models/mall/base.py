"""
Mall 专属枚举。

独立于 ERP app/models/base.py，避免枚举污染；共享 `Base` 继承自 ERP base 即可。
"""
import enum


# TODO(M1): 所有枚举字符串值需和小程序前端/API 响应字段严格一致，一处错满盘错

class MallUserType(str, enum.Enum):
    """Mall 用户类型。"""
    CONSUMER = "consumer"
    SALESMAN = "salesman"


class MallUserStatus(str, enum.Enum):
    """Mall 用户状态。停用后登录被拒，仅 ERP 后台可 reactivate。"""
    ACTIVE = "active"
    DISABLED = "disabled"
    INACTIVE_ARCHIVED = "inactive_archived"


class MallProductStatus(str, enum.Enum):
    """商城商品上架状态。"""
    DRAFT = "draft"
    ON_SALE = "on_sale"
    OFF_SALE = "off_sale"


class MallOrderStatus(str, enum.Enum):
    """商城订单状态机。

    pending_assignment → assigned → shipped → delivered →
    pending_payment_confirmation → completed
                                 └→ partial_closed（60 天未全款折损）
                                 └→ cancelled / refunded
    """
    PENDING_ASSIGNMENT = "pending_assignment"
    ASSIGNED = "assigned"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    PENDING_PAYMENT_CONFIRMATION = "pending_payment_confirmation"
    COMPLETED = "completed"
    PARTIAL_CLOSED = "partial_closed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class MallPaymentApprovalStatus(str, enum.Enum):
    """商城收款凭证审批状态（对标 ERP Receipt.status）。"""
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class MallPaymentChannel(str, enum.Enum):
    """支付渠道。第一版只做 offline；wechat/alipay 预留。"""
    OFFLINE = "offline"
    WECHAT = "wechat"
    ALIPAY = "alipay"


class MallClaimAction(str, enum.Enum):
    """抢单/改派操作类型。"""
    CLAIM = "claim"
    RELEASE = "release"
    REASSIGN = "reassign"
    ADMIN_ASSIGN = "admin_assign"


class MallSkipType(str, enum.Enum):
    """业务员跳单类型。"""
    NOT_CLAIMED_IN_TIME = "not_claimed_in_time"
    RELEASED = "released"
    ADMIN_REASSIGNED = "admin_reassigned"


class MallSkipAlertStatus(str, enum.Enum):
    """跳单告警状态。"""
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class MallInventoryFlowType(str, enum.Enum):
    """库存流水类型。"""
    IN = "in"
    OUT = "out"
    ADJUST = "adjust"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    LOSS = "loss"


class MallShipmentStatus(str, enum.Enum):
    """物流状态。"""
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"


class MallNoticeStatus(str, enum.Enum):
    """公告状态。"""
    DRAFT = "draft"
    PUBLISHED = "published"


class MallLoginMethod(str, enum.Enum):
    """登录方式（用于 mall_login_logs）。"""
    PASSWORD = "password"
    WECHAT = "wechat"
    REFRESH = "refresh"


class MallLoginClientApp(str, enum.Enum):
    """客户端类型。"""
    MP_WEIXIN = "mp_weixin"
    H5 = "h5"
    APP_ANDROID = "app_android"
    APP_IOS = "app_ios"


class MallAttachmentType(str, enum.Enum):
    """附件类型。"""
    PAYMENT_VOUCHER = "payment_voucher"
    DELIVERY_PHOTO = "delivery_photo"


class MallInventoryBarcodeType(str, enum.Enum):
    """库存条码类型（对齐 ERP InventoryBarcode）。

    M4a MVP: 只用 BOTTLE（1 码 = 1 瓶）；CASE 预留给后续整箱场景。
    """
    BOTTLE = "bottle"
    CASE = "case"


class MallInventoryBarcodeStatus(str, enum.Enum):
    """条码生命周期状态。"""
    IN_STOCK = "in_stock"   # 在库可用
    OUTBOUND = "outbound"    # 已扫码出库（订单关联）
    DAMAGED = "damaged"      # 盘亏/损耗注销
