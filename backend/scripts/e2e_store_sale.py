"""E2E：门店零售收银（桥 B12）端到端。

覆盖 5 个场景：
  1. 正常收银闭环（扫码 → 输售价 → 提交）→ 断言 6 处一致性
     StoreSale / StoreSaleItem / Commission / Inventory / InventoryBarcode / StockFlow
  2. 售价超出区间被拒（max_sale_price + 1）
  3. 没配提成率被拒（未建 retail_commission_rates）
  4. 付款方式 credit 被拒（白酒业务规矩不赊账）
  5. 非本店店员越权被拒（店员 A 用店 B 的仓扫码）

fixture 幂等可重跑。
跑法：
  cd backend && python -m scripts.e2e_store_sale
"""
import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import MallUserApplicationStatus, MallUserStatus, MallUserType
from app.models.mall.user import MallUser
from app.models.product import Brand, Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate,
    StoreSale,
    StoreSaleItem,
)
from app.models.user import Commission, Employee
from app.services import store_sale_service


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


def step(n, label) -> None:
    print(f"\n[{n}] {label}")


async def _seed_fixture() -> dict:
    """造 2 家店 + 2 个店员 + 1 个客户 + 1 个商品 + 5 瓶条码。"""
    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()

        # 2 家门店（都是 warehouse_type=store）
        store_a = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-SA-{uuid.uuid4().hex[:4]}",
            name="E2E 门店 A",
            warehouse_type=WarehouseType.STORE.value,
            is_active=True,
        )
        store_b = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-SB-{uuid.uuid4().hex[:4]}",
            name="E2E 门店 B",
            warehouse_type=WarehouseType.STORE.value,
            is_active=True,
        )
        s.add_all([store_a, store_b])
        await s.flush()

        # 2 个店员（A 店 + B 店）
        emp_a = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-CA-{uuid.uuid4().hex[:4]}",
            name="E2E 店员 A",
            position="cashier",
            status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=store_a.id,
        )
        emp_b = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-CB-{uuid.uuid4().hex[:4]}",
            name="E2E 店员 B",
            position="cashier",
            status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=store_b.id,
        )
        s.add_all([emp_a, emp_b])
        await s.flush()

        # 1 个 consumer（客户）
        cust = (await s.execute(
            select(MallUser)
            .where(MallUser.user_type == MallUserType.CONSUMER.value)
            .where(MallUser.status == MallUserStatus.ACTIVE.value)
            .limit(1)
        )).scalar_one()

        # 1 个 product 带售价区间
        product = Product(
            id=str(uuid.uuid4()),
            code=f"E2E-PRD-{uuid.uuid4().hex[:4]}",
            name="E2E 测试酒",
            category="liquor",
            brand_id=brand.id,
            unit="瓶",
            bottles_per_case=6,
            purchase_price=Decimal("100.00"),
            sale_price=Decimal("200.00"),
            min_sale_price=Decimal("180.00"),
            max_sale_price=Decimal("300.00"),
            status="active",
        )
        s.add(product)
        await s.flush()

        # Inventory + 5 瓶条码（店 A）
        batch_no = f"E2E-SB-{uuid.uuid4().hex[:6]}"
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
        for i in range(5):
            code = f"E2E-STORE-{uuid.uuid4().hex[:10].upper()}"
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
        await s.flush()

        # 提成率：店员 A 对此商品 15%
        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp_a.id,
            product_id=product.id,
            rate_on_profit=Decimal("0.15"),
            notes="E2E",
        )
        s.add(rate)
        await s.commit()

        return {
            "store_a_id": store_a.id,
            "store_b_id": store_b.id,
            "emp_a_id": emp_a.id,
            "emp_b_id": emp_b.id,
            "customer_id": cust.id,
            "product_id": product.id,
            "batch_no": batch_no,
            "codes": codes,
            "rate_id": rate.id,
        }


async def _cleanup(fx: dict) -> None:
    """按 FK 顺序清理。

    FK 链：store_sale_items.commission_id → commissions.id
          store_sale_items.sale_id → store_sales.id
          commissions.store_sale_id → store_sales.id
    → 先 items 再 commissions 再 store_sales
    """
    async with admin_session_factory() as s:
        sale_ids_q = select(StoreSale.id).where(
            StoreSale.store_id.in_([fx["store_a_id"], fx["store_b_id"]])
        )
        # 1) 先 items（它引用 commissions + store_sales 两头）
        await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id.in_(sale_ids_q)))
        # 2) 再 commissions（此时 items 已删，不再引用 commission_id）
        await s.execute(
            delete(Commission).where(Commission.employee_id.in_([fx["emp_a_id"], fx["emp_b_id"]]))
        )
        # 3) 再 store_sales
        await s.execute(
            delete(StoreSale).where(StoreSale.store_id.in_([fx["store_a_id"], fx["store_b_id"]]))
        )
        # 删 barcode / inventory / stock_flow
        await s.execute(
            delete(InventoryBarcode).where(InventoryBarcode.barcode.in_(fx["codes"]))
        )
        await s.execute(
            delete(StockFlow).where(StockFlow.batch_no == fx["batch_no"])
        )
        await s.execute(
            delete(Inventory).where(Inventory.batch_no == fx["batch_no"])
        )
        # 删提成率
        await s.execute(
            delete(RetailCommissionRate).where(RetailCommissionRate.id == fx["rate_id"])
        )
        # 删员工（先断 employees.assigned_store_id 指向）
        await s.execute(
            delete(Employee).where(Employee.id.in_([fx["emp_a_id"], fx["emp_b_id"]]))
        )
        # 删门店仓
        await s.execute(
            delete(Warehouse).where(Warehouse.id.in_([fx["store_a_id"], fx["store_b_id"]]))
        )
        # 删 product
        await s.execute(delete(Product).where(Product.id == fx["product_id"]))
        await s.commit()


async def main() -> None:
    banner("E2E 门店零售收银（桥 B12）")

    fx = await _seed_fixture()
    print(f"fixture 已建：")
    print(f"  门店 A={fx['store_a_id'][:8]}，门店 B={fx['store_b_id'][:8]}")
    print(f"  店员 A={fx['emp_a_id'][:8]}，店员 B={fx['emp_b_id'][:8]}")
    print(f"  客户={fx['customer_id'][:8]}，商品={fx['product_id'][:8]}")
    print(f"  5 瓶条码 @ 店 A + 15% 提成率（A 对此商品）")

    sale_id_holder: dict = {}

    try:
        # ── Step 1：正常收银闭环 ──
        step(1, "正常收银（店员 A 在店 A 卖 2 瓶 @ ¥250）")
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
            # 预期：销售 500，成本 200，利润 300，提成 45（300*0.15）
            assert sale.total_sale_amount == Decimal("500.00"), f"销售额 {sale.total_sale_amount}"
            assert sale.total_cost == Decimal("200.00"), f"成本 {sale.total_cost}"
            assert sale.total_profit == Decimal("300.00"), f"利润 {sale.total_profit}"
            assert sale.total_commission == Decimal("45.00"), f"提成 {sale.total_commission}"
            assert sale.total_bottles == 2
            print(f"   销售 ¥{sale.total_sale_amount} 利润 ¥{sale.total_profit} 提成 ¥{sale.total_commission}")
            print(f"   ✅ StoreSale 金额/瓶数正确")

        # 断言 6 处一致性
        async with admin_session_factory() as s:
            sale_id = sale_id_holder["id"]

            # 1) store_sale_items 2 行
            items = (await s.execute(
                select(StoreSaleItem).where(StoreSaleItem.sale_id == sale_id)
            )).scalars().all()
            assert len(items) == 2
            for it in items:
                assert it.sale_price == Decimal("250.00")
                assert it.cost_price_snapshot == Decimal("100.00")
                assert it.profit == Decimal("150.00")
                assert it.commission_amount == Decimal("22.50")
                assert it.rate_on_profit_snapshot == Decimal("0.1500")
                assert it.commission_id is not None
            print(f"   ✅ 2 条 StoreSaleItem，每条 profit=150 commission=22.50 commission_id 已回填")

            # 2) Commission 一条 (店员A × 此订单 × brand × 45 × pending)
            coms = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_id)
            )).scalars().all()
            assert len(coms) == 1
            assert coms[0].employee_id == fx["emp_a_id"]
            assert coms[0].commission_amount == Decimal("45.00")
            assert coms[0].status == "pending"
            assert coms[0].mall_order_id is None
            assert coms[0].order_id is None
            print(f"   ✅ Commission 一条，归店员 A，¥{coms[0].commission_amount}，pending，store_sale_id 挂对")

            # 3) Inventory 扣了 2（5→3）
            inv = (await s.execute(
                select(Inventory)
                .where(Inventory.warehouse_id == fx["store_a_id"])
                .where(Inventory.batch_no == fx["batch_no"])
            )).scalar_one()
            assert inv.quantity == 3, f"Inventory 应 5-2=3, 实际 {inv.quantity}"
            print(f"   ✅ Inventory qty={inv.quantity}")

            # 4) 前 2 瓶条码 → outbound
            bcs = (await s.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode.in_(fx["codes"][:2]))
            )).scalars().all()
            for b in bcs:
                assert b.status == InventoryBarcodeStatus.OUTBOUND.value, f"条码 {b.barcode} status={b.status}"
            print(f"   ✅ 2 瓶条码 → outbound")

            # 5) StockFlow 一条 retail_sale（按 product+batch 聚合）
            flows = (await s.execute(
                select(StockFlow).where(StockFlow.reference_no == sale.sale_no)
            )).scalars().all()
            assert len(flows) == 1
            assert flows[0].flow_type == "retail_sale"
            assert flows[0].quantity == -2
            print(f"   ✅ StockFlow 1 条：flow_type=retail_sale qty=-2")

            # 6) 剩 3 瓶还 in_stock
            still_in_stock = (await s.execute(
                select(InventoryBarcode).where(InventoryBarcode.barcode.in_(fx["codes"][2:]))
            )).scalars().all()
            for b in still_in_stock:
                assert b.status == InventoryBarcodeStatus.IN_STOCK.value
            print(f"   ✅ 剩余 3 瓶条码仍 in_stock")

        # ── Step 2：售价越界被拒 ──
        step(2, "售价越界被拒（超过 max_sale_price=300）")
        async with admin_session_factory() as s:
            try:
                await store_sale_service.create_store_sale(
                    s,
                    cashier_employee_id=fx["emp_a_id"],
                    store_id=fx["store_a_id"],
                    customer_id=fx["customer_id"],
                    line_items=[
                        {"barcode": fx["codes"][2], "sale_price": Decimal("301.00")},  # 超 300
                    ],
                    payment_method="cash",
                )
                assert False, "应被拒"
            except HTTPException as e:
                assert "超出区间" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        # ── Step 3：付款方式 credit 被拒 ──
        step(3, "付款方式 credit 被拒（不允许赊账）")
        async with admin_session_factory() as s:
            try:
                await store_sale_service.create_store_sale(
                    s,
                    cashier_employee_id=fx["emp_a_id"],
                    store_id=fx["store_a_id"],
                    customer_id=fx["customer_id"],
                    line_items=[
                        {"barcode": fx["codes"][2], "sale_price": Decimal("250.00")},
                    ],
                    payment_method="credit",
                )
                assert False, "应被拒"
            except HTTPException as e:
                assert "付款方式非法" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        # ── Step 4：非本店店员越权被拒 ──
        step(4, "非本店店员（店员 B 操作店 A 的仓）被拒")
        async with admin_session_factory() as s:
            try:
                await store_sale_service.create_store_sale(
                    s,
                    cashier_employee_id=fx["emp_b_id"],  # B 店店员
                    store_id=fx["store_a_id"],           # 操作 A 店
                    customer_id=fx["customer_id"],
                    line_items=[
                        {"barcode": fx["codes"][2], "sale_price": Decimal("250.00")},
                    ],
                    payment_method="cash",
                )
                assert False, "应被拒"
            except HTTPException as e:
                assert "不属于门店" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        # ── Step 5：无提成率配置被拒 ──
        step(5, "无提成率配置被拒（店员 B 没给此商品配提成率）")
        async with admin_session_factory() as s:
            try:
                # 用店员 B 在店 B 操作（合法授权），但没给 B 配提成率
                # 先给店 B 加一瓶条码
                batch_no_b = f"E2E-SBB-{uuid.uuid4().hex[:6]}"
                inv_b = Inventory(
                    product_id=fx["product_id"],
                    warehouse_id=fx["store_b_id"],
                    batch_no=batch_no_b,
                    quantity=1,
                    cost_price=Decimal("100.00"),
                    stock_in_date=datetime.now(timezone.utc),
                )
                s.add(inv_b)
                code_b = f"E2E-STORE-B-{uuid.uuid4().hex[:8].upper()}"
                s.add(InventoryBarcode(
                    id=str(uuid.uuid4()),
                    barcode=code_b,
                    barcode_type="bottle",
                    product_id=fx["product_id"],
                    warehouse_id=fx["store_b_id"],
                    batch_no=batch_no_b,
                    status=InventoryBarcodeStatus.IN_STOCK.value,
                ))
                await s.commit()

                # 记下 code_b/batch_b 让清理能删
                fx["codes"].append(code_b)
                fx["batch_no_b"] = batch_no_b

            except Exception as e:
                print(f"   ⚠️ 加店 B 条码失败：{e}")
                raise

        async with admin_session_factory() as s:
            try:
                await store_sale_service.create_store_sale(
                    s,
                    cashier_employee_id=fx["emp_b_id"],
                    store_id=fx["store_b_id"],
                    customer_id=fx["customer_id"],
                    line_items=[
                        {"barcode": fx["codes"][-1], "sale_price": Decimal("250.00")},
                    ],
                    payment_method="cash",
                )
                assert False, "应被拒（B 对此商品没配提成率）"
            except HTTPException as e:
                assert "未配置商品" in e.detail and "提成率" in e.detail, e.detail
                print(f"   ✅ 拒绝：{e.detail}")

        banner("✅ 门店零售 E2E 5 个场景全部通过")

    finally:
        # 清理：Step 5 里加的 batch_no_b 也得清
        step(99, "清理 fixture")
        async with admin_session_factory() as s:
            if fx.get("batch_no_b"):
                await s.execute(
                    delete(InventoryBarcode).where(InventoryBarcode.batch_no == fx["batch_no_b"])
                )
                await s.execute(
                    delete(StockFlow).where(StockFlow.batch_no == fx["batch_no_b"])
                )
                await s.execute(
                    delete(Inventory).where(Inventory.batch_no == fx["batch_no_b"])
                )
            await s.commit()

        await _cleanup(fx)
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
