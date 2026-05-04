"""E2E：决策 #3 门店散客（walk-in）收银端到端。

场景：
  1. 收银单 customer_id=None + 提供 walk_in_name/phone
     → StoreSale 建成功（customer_id 为 NULL，walk_in_* 快照）
     → Commission 正常计提（不依赖 customer_id）
     → StoreSaleItem / Inventory / 条码状态一致
  2. 收银单 customer_id=None + 不提供 walk_in 信息
     → 纯匿名，依然成功
  3. 散客退货：整单退 approve → 条码回 in_stock，Commission reversed
     （确认 customer_id NULL 不影响退货流程）

跑法：
  cd backend && python -m scripts.e2e_store_walk_in
"""
import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.product import Brand, Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate,
    StoreSale,
    StoreSaleItem,
    StoreSaleReturn,
    StoreSaleReturnItem,
)
from app.models.user import Commission, Employee
from app.services import store_return_service, store_sale_service


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E 决策 #3 门店散客 walk-in 收银")

    # ── fixture ──
    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()

        store = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-WK-{uuid.uuid4().hex[:4]}",
            name="E2E 散客测试门店",
            warehouse_type=WarehouseType.STORE.value,
            is_active=True,
        )
        s.add(store)
        await s.flush()

        emp = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-WK-E-{uuid.uuid4().hex[:4]}",
            name="E2E 散客测试店员",
            position="cashier",
            status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=store.id,
        )
        s.add(emp)
        await s.flush()

        product = Product(
            id=str(uuid.uuid4()),
            code=f"E2E-WK-P-{uuid.uuid4().hex[:4]}",
            name="E2E 散客测试酒",
            category="liquor",
            brand_id=brand.id,
            unit="瓶",
            bottles_per_case=6,
            min_sale_price=Decimal("180"),
            max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()

        batch_no = f"E2E-WK-B-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id,
            warehouse_id=store.id,
            batch_no=batch_no,
            quantity=3,
            cost_price=Decimal("100"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()

        codes = []
        for _ in range(3):
            c = f"E2E-WK-BC-{uuid.uuid4().hex[:8].upper()}"
            s.add(InventoryBarcode(
                id=str(uuid.uuid4()),
                barcode=c,
                barcode_type="bottle",
                product_id=product.id,
                warehouse_id=store.id,
                batch_no=batch_no,
                status=InventoryBarcodeStatus.IN_STOCK.value,
            ))
            codes.append(c)

        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp.id,
            product_id=product.id,
            rate_on_profit=Decimal("0.5"),
            notes="E2E_WK",
        )
        s.add(rate)
        await s.commit()

        fx = {
            "store_id": store.id,
            "emp_id": emp.id,
            "product_id": product.id,
            "batch_no": batch_no,
            "codes": codes,
            "rate_id": rate.id,
        }

    sale_named_id = None
    sale_anon_id = None
    return_id = None

    try:
        # ── Step 1: 散客 + walk_in 姓名手机号 ──
        print("\n[1] 散客有留名+手机")
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_id"],
                store_id=fx["store_id"],
                customer_id=None,
                customer_walk_in_name="张三",
                customer_walk_in_phone="13800001234",
                line_items=[{"barcode": fx["codes"][0], "sale_price": Decimal("250")}],
                payment_method="cash",
            )
            await s.commit()
            sale_named_id = sale.id

        async with admin_session_factory() as s:
            sale = await s.get(StoreSale, sale_named_id)
            assert sale.customer_id is None, "customer_id 应为 None"
            assert sale.customer_walk_in_name == "张三"
            assert sale.customer_walk_in_phone == "13800001234"
            assert sale.total_commission == Decimal("75.00"), (
                f"提成应为 (250-100)*0.5=75，实际 {sale.total_commission}"
            )
            # Commission 不依赖 customer_id
            c = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_named_id)
            )).scalar_one()
            assert c.commission_amount == Decimal("75.00")
            # 条码 outbound
            bc = (await s.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode == fx["codes"][0])
            )).scalar_one()
            assert bc.status == InventoryBarcodeStatus.OUTBOUND.value
            print(f"    ✅ sale_no={sale.sale_no} 散客「张三 13800001234」提成 75")

        # ── Step 2: 纯匿名散客 ──
        print("\n[2] 纯匿名散客（不填姓名手机号）")
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_id"],
                store_id=fx["store_id"],
                customer_id=None,
                line_items=[{"barcode": fx["codes"][1], "sale_price": Decimal("220")}],
                payment_method="wechat",
            )
            await s.commit()
            sale_anon_id = sale.id

        async with admin_session_factory() as s:
            sale = await s.get(StoreSale, sale_anon_id)
            assert sale.customer_id is None
            assert sale.customer_walk_in_name is None
            assert sale.customer_walk_in_phone is None
            # 提成 = (220-100)*0.5 = 60
            assert sale.total_commission == Decimal("60.00")
            print(f"    ✅ sale_no={sale.sale_no} 纯匿名 提成 60")

        # ── Step 3: 散客退货流程 ──
        print("\n[3] 散客单退货 apply + approve")
        async with admin_session_factory() as s:
            ret = await store_return_service.apply_return(
                s,
                initiator_employee_id=fx["emp_id"],
                original_sale_id=sale_named_id,
                reason="散客退货测试",
            )
            await s.commit()
            return_id = ret.id
            assert ret.customer_id is None, "散客退货单 customer_id 应也为 None"

        async with admin_session_factory() as s:
            await store_return_service.approve_return(
                s,
                return_id=return_id,
                reviewer_employee_id=fx["emp_id"],
            )
            await s.commit()

        async with admin_session_factory() as s:
            # 条码回 in_stock
            bc = (await s.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode == fx["codes"][0])
            )).scalar_one()
            assert bc.status == InventoryBarcodeStatus.IN_STOCK.value, (
                f"退货后条码应 IN_STOCK，实际 {bc.status}"
            )
            # Commission reversed
            c = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_named_id)
            )).scalar_one()
            assert c.status == "reversed"
            # StoreSale refunded
            sale = await s.get(StoreSale, sale_named_id)
            assert sale.status == "refunded"
            print(f"    ✅ 散客退货成功 条码回 IN_STOCK，Commission reversed，StoreSale refunded")

        banner("✅ 决策 #3 散客支持 E2E 通过")

    finally:
        # 清理
        async with admin_session_factory() as s:
            if return_id:
                await s.execute(delete(StoreSaleReturnItem).where(StoreSaleReturnItem.return_id == return_id))
                await s.execute(delete(StoreSaleReturn).where(StoreSaleReturn.id == return_id))
            for sid in [sale_named_id, sale_anon_id]:
                if sid:
                    await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id == sid))
                    await s.execute(delete(Commission).where(Commission.store_sale_id == sid))
                    await s.execute(delete(StoreSale).where(StoreSale.id == sid))
            for c in fx["codes"]:
                await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode == c))
            await s.execute(delete(StockFlow).where(StockFlow.batch_no == fx["batch_no"]))
            await s.execute(delete(Inventory).where(Inventory.batch_no == fx["batch_no"]))
            await s.execute(delete(RetailCommissionRate).where(RetailCommissionRate.id == fx["rate_id"]))
            await s.execute(delete(Employee).where(Employee.id == fx["emp_id"]))
            await s.execute(delete(Warehouse).where(Warehouse.id == fx["store_id"]))
            await s.execute(delete(Product).where(Product.id == fx["product_id"]))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
