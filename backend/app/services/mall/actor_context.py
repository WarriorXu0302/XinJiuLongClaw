"""
ActorContext：ERP 路由和 Mall 路由共享 service 层时用的统一身份对象。

替代原有 service 层直接读 `user["employee_id"]` 的硬耦合。让 ERP 现有路由和 mall workspace
路由都能调同一个 service（打卡/请假/报销/稽查/KPI/通知）。

关键字段：
  actor_type: 'erp_user' | 'mall_user'
  erp_user_id: str | None   # ERP users.id（ERP 侧有）
  mall_user_id: str | None  # mall_users.id（mall 侧有）
  employee_id: str | None   # 最关键：ERP 路由取自 user['employee_id']；mall 路由取自 linked_employee_id
  brand_ids: list[str]      # RLS 注入用
  roles: list[str]          # erp_user 才有
  user_type: str | None     # mall_user 才有：consumer / salesman
  is_admin: bool
  can_see_master: bool
"""
# TODO(M4c):
# @dataclass
# class ActorContext:
#     actor_type: Literal['erp_user', 'mall_user']
#     erp_user_id: Optional[str] = None
#     mall_user_id: Optional[str] = None
#     employee_id: Optional[str] = None
#     brand_ids: list[str] = field(default_factory=list)
#     roles: list[str] = field(default_factory=list)
#     user_type: Optional[str] = None
#     is_admin: bool = False
#     can_see_master: bool = False
#
# def build_actor_context_from_erp_user(user: dict) -> ActorContext: ...
# def build_actor_context_from_mall_user(mall_user: MallUser) -> ActorContext: ...
