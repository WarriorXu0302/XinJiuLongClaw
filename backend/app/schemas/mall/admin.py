"""Mall 管理后台（ERP 前端《商城》）schemas。"""
# TODO(M5):
# class MallAdminOrderListItem(BaseModel): ...
# class MallAdminOrderReassignRequest(BaseModel):
#     target_salesman_user_id: str
#     reason: str
# class MallAdminUserListItem(BaseModel): ...
# class MallAdminReferrerUpdateRequest(BaseModel):
#     new_referrer_salesman_id: Optional[str]  # None = 解绑
#     reason: str
# class MallAdminSalesmanCreateRequest(BaseModel):
#     username: str
#     initial_password: Optional[str]  # None 时后端自动生成
#     linked_employee_id: str  # 必填
#     assigned_brand_id: Optional[str]
#     phone: Optional[str]
#     nickname: Optional[str]
# class MallAdminSkipAlertResolveRequest(BaseModel):
#     status: str  # 'resolved' | 'dismissed'
#     note: str
# class MallAdminInventoryTransferRequest(BaseModel):
#     from_erp_warehouse_id: str
#     to_mall_warehouse_id: str
#     items: list[dict]  # [{sku_id, quantity}]
# class MallAdminLoginLogStatsResponse(BaseModel): ...
