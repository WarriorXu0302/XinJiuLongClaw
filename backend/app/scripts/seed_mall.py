"""
Mall 种子数据（用于 dev / E2E）。

运行：
  source backend/.venv/bin/activate
  python -m app.scripts.seed_mall
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallNoticeStatus,
    MallProductStatus,
)
from app.models.mall.content import MallNotice
from app.models.mall.inventory import MallInventory, MallWarehouse
from app.models.mall.product import (
    MallCategory,
    MallProduct,
    MallProductSku,
    MallProductTag,
    MallProductTagRel,
)
from app.models.mall.user import MallRegion, MallUser


CATEGORIES = [
    (101, "白酒"),
    (102, "啤酒"),
    (103, "红酒"),
    (104, "茶叶"),
    (105, "特产"),
]

TAGS = [
    (1, "新品上架"),
    (2, "热卖榜"),
    (3, "限时折扣"),
]

PRODUCTS = [
    # (name, brief, category_id, min_price, max_price, sku_name, sku_price, image_id)
    ("飞天茅台 53度 500ml", "严选好酒 · 6 瓶/箱", 101, 1499, 8394, "单瓶", 1499, 1001),
    ("五粮液 普五第八代 52度 500ml", "严选好酒 · 6 瓶/箱", 101, 1099, 6071, "单瓶", 1099, 1002),
    ("剑南春 水晶剑 52度 500ml", "严选好酒 · 6 瓶/箱", 101, 429, 2314, "单瓶", 429, 1004),
    ("青岛啤酒 纯生 500ml", "24 听/箱", 102, 7, 144, "单听", 7, 2002),
    ("拉菲传奇 波尔多干红 750ml", "6 瓶/箱", 103, 298, 1608, "单瓶", 298, 3001),
    ("龙井 明前特级 250g", "绿茶礼盒", 104, 588, 588, "250g", 588, 4001),
]


async def seed():
    async with admin_session_factory() as s:
        # 分类
        for cat_id, name in CATEGORIES:
            existing = (await s.execute(select(MallCategory).where(MallCategory.id == cat_id))).scalar_one_or_none()
            if not existing:
                s.add(MallCategory(id=cat_id, name=name, status="active"))
        await s.flush()

        # 标签
        for tag_id, title in TAGS:
            existing = (await s.execute(select(MallProductTag).where(MallProductTag.id == tag_id))).scalar_one_or_none()
            if not existing:
                s.add(MallProductTag(id=tag_id, title=title, status="active"))
        await s.flush()

        # 商品 + SKU
        created_prods = []
        for name, brief, cat_id, min_p, max_p, sku_name, sku_p, img_id in PRODUCTS:
            existing = (await s.execute(select(MallProduct).where(MallProduct.name == name))).scalar_one_or_none()
            if existing:
                created_prods.append(existing)
                continue
            prod = MallProduct(
                name=name,
                brief=brief,
                category_id=cat_id,
                main_image=f"https://picsum.photos/seed/{img_id}/600/600",
                images=[f"https://picsum.photos/seed/{img_id + k}/600/600" for k in (0, 100, 200)],
                detail_html=f"<p>{name} · 严选正品，产地直发。</p>",
                min_price=Decimal(str(min_p)),
                max_price=Decimal(str(max_p)),
                total_sales=100,
                status=MallProductStatus.ON_SALE.value,
            )
            s.add(prod)
            await s.flush()
            created_prods.append(prod)

            s.add(MallProductSku(
                product_id=prod.id, spec=sku_name,
                price=Decimal(str(sku_p)), cost_price=Decimal(str(sku_p)) * Decimal("0.7"),
                image=prod.main_image, status="active",
            ))
        await s.flush()

        # 把前 3 个商品挂到"热卖榜"
        hot_tag_id = 2
        for prod in created_prods[:3]:
            dup = (await s.execute(
                select(MallProductTagRel)
                .where(MallProductTagRel.tag_id == hot_tag_id)
                .where(MallProductTagRel.product_id == prod.id)
            )).scalar_one_or_none()
            if not dup:
                s.add(MallProductTagRel(
                    id=str(uuid.uuid4()),
                    tag_id=hot_tag_id, product_id=prod.id, sort_order=0,
                ))
        await s.flush()

        # 公告
        for title, content in [
            ("店庆活动", "满 1000 减 100"),
            ("物流通知", "五一假期部分地区发货延迟"),
        ]:
            existing = (await s.execute(select(MallNotice).where(MallNotice.title == title))).scalar_one_or_none()
            if not existing:
                s.add(MallNotice(
                    title=title, content=content,
                    publish_at=datetime.now(timezone.utc),
                    status=MallNoticeStatus.PUBLISHED.value,
                ))
        await s.flush()

        # 省市区（只 seed 北京做 smoke test）
        for code, parent, name, level in [
            ("110000", None, "北京市", 1),
            ("110100", "110000", "市辖区", 2),
            ("110101", "110100", "东城区", 3),
            ("110105", "110100", "朝阳区", 3),
        ]:
            existing = (await s.execute(select(MallRegion).where(MallRegion.area_code == code))).scalar_one_or_none()
            if not existing:
                s.add(MallRegion(area_code=code, parent_code=parent, name=name, level=level))

        # 仓库 + 库存（每个 SKU 给 100 件）
        wh = (await s.execute(select(MallWarehouse).where(MallWarehouse.code == "W001"))).scalar_one_or_none()
        if not wh:
            # 找业务员当 manager
            sm = (await s.execute(
                select(MallUser).where(MallUser.username == "sm_test")
            )).scalar_one_or_none()
            wh = MallWarehouse(
                code="W001", name="主仓", address="北京主仓",
                manager_user_id=sm.id if sm else None,
                is_active=True,
            )
            s.add(wh)
            await s.flush()

        all_skus = (await s.execute(select(MallProductSku))).scalars().all()
        for sku in all_skus:
            existing = (await s.execute(
                select(MallInventory)
                .where(MallInventory.warehouse_id == wh.id)
                .where(MallInventory.sku_id == sku.id)
            )).scalar_one_or_none()
            if not existing:
                s.add(MallInventory(
                    warehouse_id=wh.id,
                    sku_id=sku.id,
                    quantity=100,
                    avg_cost_price=sku.cost_price or (sku.price * Decimal("0.7")),
                ))

        await s.commit()
        print("seed_mall: done")


if __name__ == "__main__":
    asyncio.run(seed())
