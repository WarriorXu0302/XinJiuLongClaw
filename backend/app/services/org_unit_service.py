"""org_units 查询辅助 —— code → id 缓存。

为什么缓存：
  - 业务写入时写死的 code（brand_agent / retail / mall），实际要落 UUID。
  - 如果每次建单都 SELECT 一次，会给热路径加一次 DB round trip。
  - org_units 表极少变动（admin 加新单元也只改 id 分配），缓存安全。

缓存失效：
  - 进程重启清空
  - admin 改 org_unit 的 code（不推荐，UI 限制 code 只读）后，建议滚动重启 backend
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_unit import OrgUnit


_CODE_TO_ID: dict[str, str] = {}


async def get_org_unit_id_by_code(db: AsyncSession, code: str) -> str:
    """返回 code 对应的 org_unit.id，进程内缓存。"""
    if code in _CODE_TO_ID:
        return _CODE_TO_ID[code]

    ou = (await db.execute(
        select(OrgUnit).where(OrgUnit.code == code)
    )).scalar_one_or_none()
    if ou is None:
        raise ValueError(
            f"org_unit code '{code}' 不存在，请先在 /system/org-units 建单元"
        )
    _CODE_TO_ID[code] = ou.id
    return ou.id


def clear_cache() -> None:
    """测试 / admin CRUD 后手动清缓存用。"""
    _CODE_TO_ID.clear()
