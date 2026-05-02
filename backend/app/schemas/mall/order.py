"""Mall 订单 schemas。"""
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.mall.pricing_service import mask_price


# =============================================================================
# Requests
# =============================================================================

class MallOrderPreviewItem(BaseModel):
    sku_id: int = Field(alias="skuId")
    quantity: int = Field(alias="count")
    model_config = ConfigDict(populate_by_name=True)


class MallOrderPreviewRequest(BaseModel):
    items: List[MallOrderPreviewItem]
    address_id: Optional[str] = Field(default=None, alias="addrId")
    model_config = ConfigDict(populate_by_name=True)


class MallOrderCreateRequest(BaseModel):
    items: List[MallOrderPreviewItem]
    address_id: str = Field(alias="addrId")
    remarks: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)


class MallOrderCancelRequest(BaseModel):
    reason: Optional[str] = None


# =============================================================================
# Responses
# =============================================================================

class MallOrderItemVO(BaseModel):
    """订单项。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    prod_id: int = Field(alias="product_id", serialization_alias="prodId")
    sku_id: int = Field(serialization_alias="skuId")
    prod_name: Optional[str] = Field(default=None, serialization_alias="prodName")
    sku_name: Optional[str] = Field(default=None, serialization_alias="skuName")
    pic: Optional[str] = None
    price: Optional[Decimal] = None
    quantity: int = Field(serialization_alias="count")
    subtotal: Optional[Decimal] = None

    @field_serializer("price", "subtotal", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


class MallOrderPreviewResponse(BaseModel):
    items: List[dict]  # 直接返 service 算好的 list
    total_amount: Optional[Decimal] = Field(default=None, serialization_alias="totalAmount")
    shipping_fee: Optional[Decimal] = Field(default=None, serialization_alias="shippingFee")
    discount_amount: Optional[Decimal] = Field(default=None, serialization_alias="discountAmount")
    pay_amount: Optional[Decimal] = Field(default=None, serialization_alias="payAmount")
    address: Optional[dict] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_serializer("total_amount", "shipping_fee", "discount_amount", "pay_amount", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


class MallOrderListItemVO(BaseModel):
    """订单列表项。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # 订单 PK（供业务员抢单池等场景用 order_id 调 claim/release/ship/deliver/…）
    order_id: str = Field(alias="id", serialization_alias="orderId")
    order_no: str = Field(serialization_alias="orderNo")
    status: str
    payment_status: str = Field(serialization_alias="paymentStatus")
    pay_amount: Optional[Decimal] = Field(default=None, serialization_alias="payAmount")
    total_amount: Optional[Decimal] = Field(default=None, serialization_alias="totalAmount")
    created_at: Optional[Any] = Field(default=None, serialization_alias="createTime")
    remarks: Optional[str] = None

    # 业务员工作台列表展示字段（None 时前端显示空即可）
    customer_nick: Optional[str] = None
    masked_phone: Optional[str] = None
    brief_address: Optional[str] = None
    items_brief: Optional[str] = None
    expires_at: Optional[Any] = Field(default=None, serialization_alias="expiresAt")

    @field_serializer("pay_amount", "total_amount", when_used="always")
    def _mask_price(self, v):
        return mask_price(v)


class MallCourierVO(BaseModel):
    """订单配送员信息（C 端订单详情 / "联系配送员"入口用）。

    mall 没有第三方物流，业务员自提自送 → "物流"信息 = 配送业务员本人。
    """
    nickname: Optional[str] = None
    mobile: Optional[str] = None
    wechat_qr_url: Optional[str] = Field(default=None, serialization_alias="wechatQrUrl")
    alipay_qr_url: Optional[str] = Field(default=None, serialization_alias="alipayQrUrl")

    model_config = ConfigDict(populate_by_name=True)


class MallOrderDetailVO(MallOrderListItemVO):
    """订单详情。"""
    address: Optional[dict] = Field(
        default=None, alias="address_snapshot", serialization_alias="address"
    )
    items: List[MallOrderItemVO] = Field(default_factory=list)
    claimed_at: Optional[Any] = Field(default=None, serialization_alias="claimedAt")
    shipped_at: Optional[Any] = Field(default=None, serialization_alias="shippedAt")
    delivered_at: Optional[Any] = Field(default=None, serialization_alias="deliveredAt")
    paid_at: Optional[Any] = Field(default=None, serialization_alias="paidAt")
    completed_at: Optional[Any] = Field(default=None, serialization_alias="completedAt")
    cancelled_at: Optional[Any] = Field(default=None, serialization_alias="cancelledAt")
    customer_confirmed_at: Optional[Any] = Field(
        default=None, serialization_alias="customerConfirmedAt"
    )

    # 配送员信息：pending_assignment 时为 null（还没人接单）
    courier: Optional[MallCourierVO] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MallOrderStatsVO(BaseModel):
    """对齐 /p/myOrder/orderCount。"""
    unPay: int = 0
    payed: int = 0
    consignment: int = 0
    unComment: int = 0
