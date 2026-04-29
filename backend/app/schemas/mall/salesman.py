"""Mall 业务员工作台 schemas。"""
# TODO(M4):
# class MallSalesmanInviteCodeCreateResponse(BaseModel):
#     code: str
#     expires_at: datetime
#     remaining_today: int
# class MallSalesmanOrderPoolItem(BaseModel):
#     order_no: str
#     customer_nick: str
#     masked_phone: str  # 138****1234
#     brief_address: str  # 省市区+街道，不含门牌号
#     amount: Decimal
#     is_my_referral: bool  # 是否我推荐的客户（推荐人排序用）
#     created_at: datetime
# class MallSalesmanStatsResponse(BaseModel): ...
# class MallSalesmanBadgeResponse(BaseModel):
#     my_pool: int
#     in_transit: int
#     awaiting_finance: int
# class MallSalesmanSkipAlertItem(BaseModel): ...  # 可申诉入口
