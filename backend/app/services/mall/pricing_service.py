"""
价格脱敏服务。

规则（plan 决策 #7）：C 端用户必须登录 + 绑定推荐人（referrer_salesman_id IS NOT NULL）
才能看到商品价格。不满足时所有价格字段返回 null，前端显示"联系业务员了解价格"。

技术方案（plan 决策 #14）：ContextVar + Pydantic model_serializer 在 Response 出库前判定。
路由入口调 `set_price_visible(...)` 设置 ContextVar，Pydantic schema 在 serializer 里读。
业务员（user_type='salesman'）永远可见。
"""
from contextvars import ContextVar
from typing import Optional

# Default False：未设置时按"不可见"处理（更安全）
_price_visible_ctx: ContextVar[bool] = ContextVar("mall_price_visible", default=False)


def set_price_visible(visible: bool) -> None:
    _price_visible_ctx.set(visible)


def is_price_visible() -> bool:
    return _price_visible_ctx.get()


def mask_price(value):
    """Pydantic field serializer 用的统一脱敏函数。"""
    return value if _price_visible_ctx.get() else None


def compute_visibility_for_user(user: Optional[dict]) -> bool:
    """
    user 是 CurrentMallUser payload dict（或 None 表示未登录）。

    可见条件：
      - 已登录
      - 用户类型是 salesman；或已绑定 referrer_salesman_id（需要 DB 查询）
    注意：C 端消费者的 referrer 绑定字段不在 JWT payload 里，业务代码需在路由内
    通过 auth_service.verify_token_and_load_user 拿到 MallUser 后再设置。
    本函数是快速路径：业务员 token 一看就知道可见。
    """
    if user is None:
        return False
    return user.get("user_type") == "salesman"


def compute_visibility_for_mall_user(mall_user) -> bool:
    """
    mall_user 是已加载的 MallUser ORM 实例。更可靠的判定。
    """
    if mall_user is None:
        return False
    if mall_user.user_type == "salesman":
        return True
    return bool(mall_user.referrer_salesman_id)


async def apply_price_visibility(current, db) -> None:
    """浏览类端点统一入口：按当前 JWT + DB 状态设置 price 可见性。

    - 匿名 / 坏 token → 不可见
    - 账号 status != 'active' → 不可见
    - token_version 不匹配 → 不可见（被 logout / 封禁吊销的老 token）
    - 业务员 → 可见
    - 消费者已绑 referrer → 可见
    """
    from app.services.mall.auth_service import get_mall_user_by_id

    if current is None:
        set_price_visible(False)
        return
    user = await get_mall_user_by_id(db, current["sub"])
    if (
        user is None
        or user.status != "active"
        or user.token_version != current.get("token_version")
    ):
        set_price_visible(False)
        return
    set_price_visible(compute_visibility_for_mall_user(user))
