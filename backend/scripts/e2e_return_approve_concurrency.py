"""E2E：G12 退货 approve 并发保护 · FOR UPDATE + UNIQUE partial index。

验证场景：
  1. 正常 approve 一次 → 建 1 条 adjustment（store_return）
  2. 应用层 bypass 测试：直接走 DB insert 第二条 adjustment 指向同一原 commission
     → 触发 UNIQUE partial index 拒绝（m6c6）
  3. 正常 approve 不受影响（FOR UPDATE 是事务内串行化，单事务不触发 UNIQUE 冲突）

跑法：
  cd backend && python -m scripts.e2e_return_approve_concurrency
"""
import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import admin_session_factory
from app.models.audit_log import AuditLog
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.product import Brand, Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate, StoreSale, StoreSaleItem,
    StoreSaleReturn, StoreSaleReturnItem,
)
from app.models.user import Commission, Employee
from app.services import store_return_service, store_sale_service


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E G12 · 退货 approve 并发保护 + UNIQUE partial index")

    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        store = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-G12-{uuid.uuid4().hex[:4]}",
            name="E2E G12 测试店",
            warehouse_type=WarehouseType.STORE.value, is_active=True,
        )
        s.add(store)
        await s.flush()

        emp = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-G12-E-{uuid.uuid4().hex[:4]}",
            name="E2E G12 店员",
            position="cashier", status="active",
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
            code=f"E2E-G12-P-{uuid.uuid4().hex[:4]}",
            name="E2E G12 测试酒",
            category="liquor", brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            min_sale_price=Decimal("100"),
            max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()

        batch = f"E2E-G12-B-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id, warehouse_id=store.id,
            batch_no=batch, quantity=1,
            cost_price=Decimal("100"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()

        code = f"E2E-G12-BC-{uuid.uuid4().hex[:8].upper()}"
        s.add(InventoryBarcode(
            id=str(uuid.uuid4()), barcode=code, barcode_type="bottle",
            product_id=product.id, warehouse_id=store.id, batch_no=batch,
            status=InventoryBarcodeStatus.IN_STOCK.value,
        ))

        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp.id, product_id=product.id,
            rate_on_profit=Decimal("0.5"),
        )
        s.add(rate)
        await s.commit()
        fx = {
            "store_id": store.id, "emp_id": emp.id,
            "product_id": product.id, "batch": batch,
            "code": code, "rate_id": rate.id,
        }

    sale_id = None
    return_id = None
    origin_commission_id = None

    try:
        # Step 1: 收银
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_id"],
                store_id=fx["store_id"],
                customer_id=None,
                line_items=[{"barcode": fx["code"], "sale_price": Decimal("300")}],
                payment_method="cash",
            )
            await s.commit()
            sale_id = sale.id

        # Step 2: Commission → settled（模拟上月已发）
        async with admin_session_factory() as s:
            c = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_id)
            )).scalar_one()
            c.status = "settled"
            c.settled_at = datetime.now(timezone.utc) - timedelta(days=30)
            origin_commission_id = c.id
            await s.commit()

        # Step 3: 申请退货
        async with admin_session_factory() as s:
            ret = await store_return_service.apply_return(
                s, initiator_employee_id=fx["emp_id"],
                original_sale_id=sale_id, reason="G12 测试",
            )
            await s.commit()
            return_id = ret.id

        # Step 4: 正常 approve 一次 → 建 1 条 adjustment
        async with admin_session_factory() as s:
            await store_return_service.approve_return(
                s, return_id=return_id, reviewer_employee_id=fx["emp_id"],
            )
            await s.commit()
        print(f"[1] ✅ 首次 approve 完成，adjustment 已建")

        # Step 5: 再次 approve → 状态已 refunded，应该直接 409
        async with admin_session_factory() as s:
            raised_409 = False
            try:
                await store_return_service.approve_return(
                    s, return_id=return_id, reviewer_employee_id=fx["emp_id"],
                )
                await s.commit()
            except Exception as e:
                if getattr(e, 'status_code', None) == 409:
                    raised_409 = True
            assert raised_409, "重复 approve 应 409，不应再建 adjustment"
            print(f"[2] ✅ 重复 approve 被拒（409）")

        # Step 6: DB UNIQUE 兜底测试：手工再 INSERT 一条 adjustment 指向同一原 commission
        async with admin_session_factory() as s:
            existing = (await s.execute(
                select(Commission)
                .where(Commission.adjustment_source_commission_id == origin_commission_id)
            )).scalars().all()
            assert len(existing) == 1, f"应已有 1 条 adjustment 实际 {len(existing)}"

            # 尝试再造一条同 source 的 adjustment —— 应被 UNIQUE partial index 拒
            bad = Commission(
                id=str(uuid.uuid4()),
                employee_id=fx["emp_id"],
                brand_id=None,
                store_sale_id=sale_id,
                order_id=None,
                mall_order_id=None,
                commission_amount=Decimal("-99.99"),
                is_adjustment=True,
                adjustment_source_commission_id=origin_commission_id,  # 重复源
                status="pending",
                notes="E2E G12 UNIQUE 兜底测试",
            )
            s.add(bad)
            rejected_by_db = False
            try:
                await s.commit()
            except IntegrityError:
                rejected_by_db = True
                await s.rollback()
            assert rejected_by_db, "DB UNIQUE partial index 应拒绝重复 adjustment"
            print(f"[3] ✅ DB UNIQUE 兜底：重复 adjustment 被拒")

        # Step 7: 最终状态：只有 1 条 adjustment
        async with admin_session_factory() as s:
            final_count = (await s.execute(
                select(Commission)
                .where(Commission.adjustment_source_commission_id == origin_commission_id)
            )).scalars().all()
            assert len(final_count) == 1
            print(f"[4] ✅ 最终 adjustment 唯一（count=1）")

        banner("✅ G12 退货并发保护 E2E 通过")

    finally:
        async with admin_session_factory() as s:
            if return_id:
                await s.execute(delete(StoreSaleReturnItem).where(StoreSaleReturnItem.return_id == return_id))
                await s.execute(delete(StoreSaleReturn).where(StoreSaleReturn.id == return_id))
            if sale_id:
                await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id == sale_id))
                await s.execute(delete(Commission).where(Commission.store_sale_id == sale_id))
                await s.execute(delete(StoreSale).where(StoreSale.id == sale_id))
                await s.execute(delete(AuditLog).where(AuditLog.entity_id == sale_id))
            await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode == fx["code"]))
            await s.execute(delete(StockFlow).where(StockFlow.batch_no == fx["batch"]))
            await s.execute(delete(Inventory).where(Inventory.batch_no == fx["batch"]))
            await s.execute(delete(RetailCommissionRate).where(RetailCommissionRate.id == fx["rate_id"]))
            await s.execute(delete(Employee).where(Employee.id == fx["emp_id"]))
            await s.execute(delete(Warehouse).where(Warehouse.id == fx["store_id"]))
            await s.execute(delete(Product).where(Product.id == fx["product_id"]))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
