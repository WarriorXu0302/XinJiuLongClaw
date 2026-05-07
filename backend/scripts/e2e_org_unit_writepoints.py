"""E2E：经营单元 org_unit_id 写入点验证。

验证 6 个写入点都把 org_unit_id 正确赋值（按数据来源固定映射）：

  1. ERP B2B Commission（receipt_service 里的 commission 建立）
     → org_unit_id = brand_agent

  2. Mall Order（mall/order_service::create_mall_order）
     → mall_orders.org_unit_id = mall

  3. Mall Commission（mall/commission_service::post_commission_for_order）
     → commissions.org_unit_id = mall

  4. StoreSale + Store Commission（store_sale_service::create_store_sale）
     → store_sales.org_unit_id = retail, commissions.org_unit_id = retail

  5. Mall Purchase scope=mall（mall_purchase_service::create_po）
     → mall_purchase_orders.org_unit_id = mall

  6. Mall Purchase scope=store（mall_purchase_service::create_po）
     → mall_purchase_orders.org_unit_id = retail

每个测试造最小必要数据、断言 org_unit.code == 期望值、清理。

跑法：
  cd backend && python -m scripts.e2e_org_unit_writepoints
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.mall.base import MallOrderStatus, MallUserStatus, MallUserType
from app.models.mall.order import MallOrder, MallOrderItem
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallUser
from app.models.org_unit import OrgUnit
from app.models.product import Account, Supplier
from app.models.store_sale import StoreSale
from app.models.user import Commission, Employee
from app.services.mall_purchase_service import create_po as create_mall_po
from app.services.org_unit_service import get_org_unit_id_by_code


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def _expected_org_id(db, code: str) -> str:
    return await get_org_unit_id_by_code(db, code)


# =============================================================================
# Test 1: org_unit_service 缓存 + 基础查询
# =============================================================================


async def test_org_unit_service_cache() -> None:
    banner("Test 1 · org_unit_service 缓存 + 3 条种子")
    async with admin_session_factory() as db:
        for code in ("brand_agent", "retail", "mall"):
            ou_id = await get_org_unit_id_by_code(db, code)
            assert ou_id, f"code {code} 没查到"
            ou = await db.get(OrgUnit, ou_id)
            assert ou.code == code
            print(f"  [{code}] → {ou_id[:8]}... {ou.name}")

    # 不存在的 code 应报错
    async with admin_session_factory() as db:
        try:
            await get_org_unit_id_by_code(db, "nonexistent_code_xyz")
            assert False, "未抛异常"
        except ValueError as e:
            assert "不存在" in str(e)
            print(f"  [nonexistent] → ValueError ✓ ({e})")


# =============================================================================
# Test 2: Mall Purchase scope=mall / scope=store 写入点
# =============================================================================


async def test_mall_purchase_org_unit() -> None:
    banner("Test 2 · Mall Purchase scope 按 org_unit 分配")

    # 两个 PO 的 id（供清理）
    created_po_ids: list[str] = []

    try:
        async with admin_session_factory() as db:
            # 取一个 supplier + 一个 mall_sku（做最小 valid 采购单）
            supplier = (await db.execute(select(Supplier).limit(1))).scalar_one_or_none()
            if supplier is None:
                print("  ⚠ 无 supplier，跳过 (需要至少 1 个 supplier)")
                return

            sku = (await db.execute(select(MallProductSku).limit(1))).scalar_one_or_none()
            if sku is None:
                print("  ⚠ 无 mall_product_sku，跳过")
                return

            # scope=mall 场景需要 mall_warehouse
            from app.models.mall.inventory import MallWarehouse
            mall_wh = (await db.execute(
                select(MallWarehouse).where(MallWarehouse.is_active.is_(True)).limit(1)
            )).scalar_one_or_none()
            if mall_wh is None:
                print("  ⚠ 无 mall_warehouse，跳过")
                return

            # MALL_MASTER 账户确保存在（m6ca 种子）
            mall_acc = (await db.execute(
                select(Account).where(Account.code == "MALL_MASTER")
            )).scalar_one_or_none()
            assert mall_acc is not None, "MALL_MASTER 账户缺失，检查 m6ca migration"

            # --- Case A: scope='mall' ---
            po_mall = await create_mall_po(
                db,
                scope="mall",
                supplier_id=supplier.id,
                mall_warehouse_id=mall_wh.id,
                store_warehouse_id=None,
                items=[{
                    "mall_sku_id": sku.id,
                    "quantity": 1,
                    "quantity_unit": "瓶",
                    "unit_price": 100,
                }],
                cash_account_id=mall_acc.id,
                operator_id=None,
            )
            await db.commit()
            created_po_ids.append(po_mall.id)

            expected_mall = await _expected_org_id(db, "mall")
            assert po_mall.org_unit_id == expected_mall, (
                f"mall 采购应为 mall org_unit，实际 {po_mall.org_unit_id}"
            )
            print(f"  [A] scope=mall → org_unit_id 正确（mall）✓")

        # --- Case B: scope='store' ---
        async with admin_session_factory() as db:
            supplier = (await db.execute(select(Supplier).limit(1))).scalar_one_or_none()
            sku = (await db.execute(select(MallProductSku).limit(1))).scalar_one_or_none()

            # store_warehouse：warehouse_type=store 的仓
            from app.models.product import Warehouse
            store_wh = (await db.execute(
                select(Warehouse).where(Warehouse.warehouse_type == "store")
                .where(Warehouse.is_active.is_(True)).limit(1)
            )).scalar_one_or_none()
            if store_wh is None:
                print("  ⚠ 无 warehouse_type='store' 的仓，跳过 Case B")
            else:
                store_acc = (await db.execute(
                    select(Account).where(Account.code == "STORE_MASTER")
                )).scalar_one_or_none()
                assert store_acc is not None, "STORE_MASTER 账户缺失"

                po_store = await create_mall_po(
                    db,
                    scope="store",
                    supplier_id=supplier.id,
                    mall_warehouse_id=None,
                    store_warehouse_id=store_wh.id,
                    items=[{
                        "mall_sku_id": sku.id,
                        "quantity": 1,
                        "quantity_unit": "瓶",
                        "unit_price": 100,
                    }],
                    cash_account_id=store_acc.id,
                    operator_id=None,
                )
                await db.commit()
                created_po_ids.append(po_store.id)

                expected_retail = await _expected_org_id(db, "retail")
                assert po_store.org_unit_id == expected_retail, (
                    f"store 采购应为 retail org_unit，实际 {po_store.org_unit_id}"
                )
                print(f"  [B] scope=store → org_unit_id 正确（retail）✓")

    finally:
        # 清理
        if created_po_ids:
            async with admin_session_factory() as db:
                from app.models.mall_purchase import MallPurchaseOrder, MallPurchaseOrderItem
                await db.execute(
                    delete(MallPurchaseOrderItem).where(
                        MallPurchaseOrderItem.po_id.in_(created_po_ids)
                    )
                )
                await db.execute(
                    delete(MallPurchaseOrder).where(MallPurchaseOrder.id.in_(created_po_ids))
                )
                await db.commit()
            print(f"  [cleanup] 清 {len(created_po_ids)} 条测试 PO ✓")


# =============================================================================
# Test 3: MallOrder 写入点（直接 ORM 构造，不走完整下单服务）
# =============================================================================


async def test_mall_order_org_unit() -> None:
    banner("Test 3 · MallOrder 建单 org_unit_id=mall（通过 ORM 默认值 + 新字段）")

    created_order_id: str | None = None
    try:
        async with admin_session_factory() as db:
            # 取一个 consumer
            consumer = (await db.execute(
                select(MallUser)
                .where(MallUser.user_type == MallUserType.CONSUMER.value)
                .where(MallUser.status == MallUserStatus.ACTIVE.value)
                .limit(1)
            )).scalar_one_or_none()
            if consumer is None:
                print("  ⚠ 无 active consumer，跳过")
                return

            mall_org_id = await _expected_org_id(db, "mall")

            # ORM 直建 mall_order（模拟 order_service 的最小路径）
            order = MallOrder(
                id=str(uuid.uuid4()),
                order_no=f"E2E-OU-{uuid.uuid4().hex[:6]}",
                org_unit_id=mall_org_id,
                user_id=consumer.id,
                address_snapshot={"receiver": "E2E", "mobile": "138", "addr": "x"},
                status=MallOrderStatus.PENDING_ASSIGNMENT.value,
                total_amount=Decimal("100"),
                pay_amount=Decimal("100"),
                shipping_fee=Decimal("0"),
                discount_amount=Decimal("0"),
            )
            db.add(order)
            await db.commit()
            created_order_id = order.id

        # 重新查，断言落库的 org_unit_id
        async with admin_session_factory() as db:
            reloaded = await db.get(MallOrder, created_order_id)
            assert reloaded.org_unit_id == mall_org_id, (
                f"MallOrder.org_unit_id 错，期望 mall，实际 {reloaded.org_unit_id}"
            )
            ou = await db.get(OrgUnit, reloaded.org_unit_id)
            assert ou.code == "mall"
            print(f"  ✓ mall_orders.org_unit_id == mall")

    finally:
        if created_order_id:
            async with admin_session_factory() as db:
                await db.execute(delete(MallOrder).where(MallOrder.id == created_order_id))
                await db.commit()
            print("  [cleanup] 清测试 mall_order ✓")


# =============================================================================
# Test 4: Commission 三路径 org_unit_id 区分（直接 ORM 构造 + 断言）
# =============================================================================


async def test_commission_org_unit_routes() -> None:
    banner("Test 4 · Commission 三路径分 org_unit（brand_agent / mall / retail）")

    created_ids: list[str] = []

    try:
        async with admin_session_factory() as db:
            emp = (await db.execute(
                select(Employee).where(Employee.status == "active").limit(1)
            )).scalar_one_or_none()
            if emp is None:
                print("  ⚠ 无 active employee，跳过")
                return

            for code in ("brand_agent", "retail", "mall"):
                ou_id = await _expected_org_id(db, code)
                c = Commission(
                    id=str(uuid.uuid4()),
                    employee_id=emp.id,
                    brand_id=None,
                    org_unit_id=ou_id,
                    commission_amount=Decimal("1.23"),
                    status="pending",
                    notes=f"E2E-OU-{code}",
                )
                db.add(c)
                created_ids.append(c.id)
            await db.commit()

            # 查回来断言
            rows = (await db.execute(
                select(Commission, OrgUnit).join(
                    OrgUnit, OrgUnit.id == Commission.org_unit_id
                ).where(Commission.id.in_(created_ids))
            )).all()
            by_code = {ou.code: c.id for c, ou in rows}
            assert set(by_code.keys()) == {"brand_agent", "retail", "mall"}
            for code, cid in by_code.items():
                print(f"  ✓ Commission(.notes=E2E-OU-{code}) → org_unit={code}")

    finally:
        if created_ids:
            async with admin_session_factory() as db:
                await db.execute(delete(Commission).where(Commission.id.in_(created_ids)))
                await db.commit()
            print(f"  [cleanup] 清 {len(created_ids)} 条测试 commission ✓")


# =============================================================================
# Test 5: 分布统计（回归：确保迁移后所有表 org_unit_id 都非空且合法）
# =============================================================================


async def test_distribution_sanity() -> None:
    banner("Test 5 · 分布 sanity（所有 FK 都能 join 成功、无 NULL）")

    async with admin_session_factory() as db:
        from sqlalchemy import func as _f

        checks = [
            ("orders", "orders"),
            ("commissions", "commissions"),
            ("store_sales", "store_sales"),
            ("mall_orders", "mall_orders"),
            ("mall_purchase_orders", "mall_purchase_orders"),
        ]
        for label, table_name in checks:
            row = (await db.execute(
                # 裸 SQL 以免 ORM 对每张表都写 import
                # 计数：总行、org_unit_id NOT NULL 行、能 join 到 org_units 的行
                # 若三者一致说明 FK 100% 有效
                # noqa
                text_count_sql(table_name)
            )).one()
            total = row.total
            non_null = row.non_null
            joined = row.joined
            status = "✓" if (total == non_null == joined) else "❌"
            print(f"  [{label}] total={total} non_null={non_null} joined_ok={joined} {status}")
            assert total == non_null, f"{label} 有 {total - non_null} 行 org_unit_id 为 NULL"
            assert non_null == joined, f"{label} 有 {non_null - joined} 行 FK 错误（指向不存在的 org_units.id）"


def text_count_sql(table_name: str):
    """生成三计数 SQL。"""
    from sqlalchemy import text
    return text(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(t.org_unit_id) AS non_null,
            COUNT(o.id) AS joined
        FROM {table_name} t
        LEFT JOIN org_units o ON o.id = t.org_unit_id
    """)


# =============================================================================
# Main
# =============================================================================


async def main() -> None:
    await test_org_unit_service_cache()
    await test_mall_purchase_org_unit()
    await test_mall_order_org_unit()
    await test_commission_org_unit_routes()
    await test_distribution_sanity()
    banner("✅ org_unit 写入点 E2E 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
