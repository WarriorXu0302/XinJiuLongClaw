"""E2E：门店退货（桥 B12 延伸）端到端。

场景：
  1. 先走一遍正常收银造一单 StoreSale（2 瓶 @ ¥250，利润 150/瓶，提成 22.5/瓶）
  2. 店员发起退货 → pending
  3. 非本店店员不能发起（403）
  4. 同一单不能重复发起活跃退货（409）
  5. admin 批准退货 → 断言 6 处一致性：
     - StoreSaleReturn.status = refunded
     - StoreSale.status = refunded
     - InventoryBarcode 2 瓶 → IN_STOCK
     - Inventory 数量回加 2
     - StockFlow 新增 retail_return 1 条
     - Commission reversed（原 pending 状态的）

跑法：
  cd backend && python -m scripts.e2e_store_return
"""
import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
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


def step(n, label) -> None:
    print(f"\n[{n}] {label}")


async def main() -> None:
    banner("E2E 门店退货（桥 B12 延伸）")

    # ── fixture ──
    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        store_a = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-SR-{uuid.uuid4().hex[:4]}",
            name="E2E 退货测试门店",
            warehouse_type=WarehouseType.STORE.value,
            is_active=True,
        )
        store_b = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-SR2-{uuid.uuid4().hex[:4]}",
            name="E2E 退货别店",
            warehouse_type=WarehouseType.STORE.value,
            is_active=True,
        )
        s.add_all([store_a, store_b])
        await s.flush()

        emp_a = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-SR-CA-{uuid.uuid4().hex[:4]}",
            name="E2E 退货店员 A",
            position="cashier", status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=store_a.id,
        )
        emp_b = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-SR-CB-{uuid.uuid4().hex[:4]}",
            name="E2E 退货店员 B",
            position="cashier", status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=store_b.id,
        )
        s.add_all([emp_a, emp_b])
        await s.flush()

        cust = (await s.execute(
            select(MallUser)
            .where(MallUser.user_type == MallUserType.CONSUMER.value)
            .where(MallUser.status == MallUserStatus.ACTIVE.value)
            .limit(1)
        )).scalar_one()

        product = Product(
            id=str(uuid.uuid4()),
            code=f"E2E-SR-P-{uuid.uuid4().hex[:4]}",
            name="E2E 退货测试酒",
            category="liquor",
            brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            purchase_price=Decimal("100.00"),
            sale_price=Decimal("200.00"),
            min_sale_price=Decimal("180.00"),
            max_sale_price=Decimal("300.00"),
            status="active",
        )
        s.add(product)
        await s.flush()

        batch_no = f"E2E-SRB-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id,
            warehouse_id=store_a.id,
            batch_no=batch_no,
            quantity=5,
            cost_price=Decimal("100.00"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()

        codes = []
        for i in range(2):
            code = f"E2E-SR-C-{uuid.uuid4().hex[:10].upper()}"
            s.add(InventoryBarcode(
                id=str(uuid.uuid4()),
                barcode=code,
                barcode_type="bottle",
                product_id=product.id,
                warehouse_id=store_a.id,
                batch_no=batch_no,
                status=InventoryBarcodeStatus.IN_STOCK.value,
            ))
            codes.append(code)

        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp_a.id,
            product_id=product.id,
            rate_on_profit=Decimal("0.15"),
            notes="E2E_RET",
        )
        s.add(rate)
        await s.commit()

        fx = {
            "store_a_id": store_a.id, "store_b_id": store_b.id,
            "emp_a_id": emp_a.id, "emp_b_id": emp_b.id,
            "customer_id": cust.id, "product_id": product.id,
            "batch_no": batch_no, "codes": codes, "rate_id": rate.id,
        }
        print(f"fixture 已建：store_a={store_a.id[:8]} emp_a={emp_a.id[:8]} emp_b={emp_b.id[:8]}")
        print(f"  2 瓶 @ 店 A，原单成本 100/瓶，售价 250/瓶，提成率 15%")

    sale_id_holder = {}
    return_id_holder = {}

    try:
        # ── Step 1：造原销售单 ──
        step(1, "店员 A 卖出 2 瓶 @ ¥250（利润 300 / 提成 45）")
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_a_id"],
                store_id=fx["store_a_id"],
                customer_id=fx["customer_id"],
                line_items=[
                    {"barcode": fx["codes"][0], "sale_price": Decimal("250.00")},
                    {"barcode": fx["codes"][1], "sale_price": Decimal("250.00")},
                ],
                payment_method="cash",
            )
            sale_id_holder["id"] = sale.id
            await s.commit()
            assert sale.total_sale_amount == Decimal("500.00")
            assert sale.total_commission == Decimal("45.00")
            print(f"   ✅ {sale.sale_no}  总销售¥500  利润¥300  提成¥45")

        # ── Step 2：店员 A 发起退货 ──
        step(2, "店员 A 发起整单退货（pending）")
        async with admin_session_factory() as s:
            ret = await store_return_service.apply_return(
                s,
                initiator_employee_id=fx["emp_a_id"],
                original_sale_id=sale_id_holder["id"],
                reason="E2E 测试客户要求退货",
            )
            return_id_holder["id"] = ret.id
            await s.commit()
            assert ret.status == "pending"
            assert ret.refund_amount == Decimal("500.00")
            assert ret.commission_reversal_amount == Decimal("45.00")
            assert ret.total_bottles == 2
            print(f"   ✅ {ret.return_no}  status=pending  refund=¥500  提成冲销=¥45  2 瓶")

        # ── Step 3：非本店店员不能发起 ──
        step(3, "店员 B 不能对 A 店的单发起退货（应 403）")
        async with admin_session_factory() as s:
            try:
                await store_return_service.apply_return(
                    s,
                    initiator_employee_id=fx["emp_b_id"],
                    original_sale_id=sale_id_holder["id"],
                )
                assert False, "应被拒"
            except HTTPException as e:
                assert "非本店店员" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        # ── Step 4：不能重复发起 ──
        step(4, "同一单重复发起退货应 409")
        async with admin_session_factory() as s:
            try:
                await store_return_service.apply_return(
                    s,
                    initiator_employee_id=fx["emp_a_id"],
                    original_sale_id=sale_id_holder["id"],
                )
                assert False, "应被拒"
            except HTTPException as e:
                assert "活跃退货单" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        # ── Step 5：admin 批准 + 断言 6 处一致 ──
        step(5, "admin 批准退货，执行条码回池 / 库存回加 / 提成冲销 / 原单 refunded")
        async with admin_session_factory() as s:
            ret = await store_return_service.approve_return(
                s,
                return_id=return_id_holder["id"],
                reviewer_employee_id=fx["emp_a_id"],  # 测试用 emp_a 当审批人
            )
            await s.commit()
            assert ret.status == "refunded"
            print(f"   ✅ StoreSaleReturn.status = refunded")

        async with admin_session_factory() as s:
            # 1) 原 StoreSale.status = refunded
            sale = await s.get(StoreSale, sale_id_holder["id"])
            assert sale.status == "refunded", f"期望 refunded, 实际 {sale.status}"
            print(f"   ✅ StoreSale.status = refunded")

            # 2) 2 瓶条码 IN_STOCK
            bcs = (await s.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode.in_(fx["codes"]))
            )).scalars().all()
            assert len(bcs) == 2
            for bc in bcs:
                assert bc.status == InventoryBarcodeStatus.IN_STOCK.value
            print(f"   ✅ 2 瓶条码 → IN_STOCK")

            # 3) Inventory 回加（5 - 2 扣出, 现在 + 2 回来 = 5）
            inv = (await s.execute(
                select(Inventory)
                .where(Inventory.warehouse_id == fx["store_a_id"])
                .where(Inventory.batch_no == fx["batch_no"])
            )).scalar_one()
            assert inv.quantity == 5, f"应 5, 实际 {inv.quantity}"
            print(f"   ✅ Inventory 数量回加到 {inv.quantity}")

            # 4) StockFlow retail_return 新增
            flows = (await s.execute(
                select(StockFlow).where(StockFlow.reference_no == ret.return_no)
            )).scalars().all()
            assert len(flows) == 1
            assert flows[0].flow_type == "retail_return"
            assert flows[0].quantity == 2
            print(f"   ✅ StockFlow: flow_type=retail_return qty={flows[0].quantity}")

            # 5) Commission status=reversed
            coms = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_id_holder["id"])
            )).scalars().all()
            assert len(coms) == 1
            assert coms[0].status == "reversed"
            print(f"   ✅ Commission status=reversed, 金额 ¥{coms[0].commission_amount}")

            # 6) StoreSaleReturn 状态 refunded + reviewer 填了
            r = await s.get(StoreSaleReturn, return_id_holder["id"])
            assert r.reviewer_employee_id == fx["emp_a_id"]
            assert r.reviewed_at is not None
            print(f"   ✅ StoreSaleReturn.reviewed_at 填了")

        banner("✅ 门店退货 E2E 5 场景全部通过")

    finally:
        # 清理
        step(99, "清理 fixture")
        async with admin_session_factory() as s:
            # FK 顺序：return_items → return → sale_items → commissions → sale
            ret_id = return_id_holder.get("id")
            sale_id = sale_id_holder.get("id")
            if ret_id:
                await s.execute(delete(StoreSaleReturnItem).where(StoreSaleReturnItem.return_id == ret_id))
                await s.execute(delete(StoreSaleReturn).where(StoreSaleReturn.id == ret_id))
            if sale_id:
                await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id == sale_id))
                await s.execute(delete(Commission).where(Commission.store_sale_id == sale_id))
                await s.execute(delete(StoreSale).where(StoreSale.id == sale_id))
            await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode.in_(fx["codes"])))
            await s.execute(delete(StockFlow).where(StockFlow.batch_no == fx["batch_no"]))
            await s.execute(delete(Inventory).where(Inventory.batch_no == fx["batch_no"]))
            await s.execute(delete(RetailCommissionRate).where(RetailCommissionRate.id == fx["rate_id"]))
            await s.execute(delete(Employee).where(Employee.id.in_([fx["emp_a_id"], fx["emp_b_id"]])))
            await s.execute(delete(Warehouse).where(Warehouse.id.in_([fx["store_a_id"], fx["store_b_id"]])))
            await s.execute(delete(Product).where(Product.id == fx["product_id"]))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
