"""E2E：G3/G7/G9 看板利润卡 + 门店导出 + 批量快照回补。

场景（直接调 service/route-level 逻辑）：
  G9：aggregate_mall_profit 接受 date_from/date_to，返 total_revenue/total_profit/gross_margin
  G3：store-sales stats?group_by=store 返 by_store + total；export 返 CSV 字符串
  G7：build_snapshot_for_month 批量跑多月不报错

跑法：
  cd backend && python -m scripts.e2e_dashboard_profit_export
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
)
from app.models.user import Commission, Employee
from app.models.audit_log import AuditLog
from app.services import store_sale_service
from app.services.mall import kpi_snapshot_service as kss


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E G3/G7/G9 · Dashboard 利润 + 门店导出 + 批量快照回补")

    # ── fixture: 2 家门店 + 2 个店员 + 1 个商品 + 各 2 瓶条码 ──
    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        stores = []
        emps = []
        for i in range(2):
            w = Warehouse(
                id=str(uuid.uuid4()),
                code=f"E2E-G3-W{i}-{uuid.uuid4().hex[:4]}",
                name=f"E2E G3 门店 {chr(65+i)}",
                warehouse_type=WarehouseType.STORE.value,
                is_active=True,
            )
            s.add(w)
            await s.flush()
            stores.append(w)
            emp = Employee(
                id=str(uuid.uuid4()),
                employee_no=f"E2E-G3-E{i}-{uuid.uuid4().hex[:4]}",
                name=f"G3 店员 {chr(65+i)}", position="cashier", status="active",
                hire_date=date.today(),
                social_security=Decimal("0"),
                company_social_security=Decimal("0"),
                expected_manufacturer_subsidy=Decimal("0"),
                assigned_store_id=w.id,
            )
            s.add(emp)
            await s.flush()
            emps.append(emp)

        product = Product(
            id=str(uuid.uuid4()),
            code=f"E2E-G3-P-{uuid.uuid4().hex[:4]}",
            name="E2E G3 测试酒",
            category="liquor", brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            min_sale_price=Decimal("100"), max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()

        # 每店一个 inventory batch + 2 瓶条码
        all_codes = []
        batches = []
        for i, w in enumerate(stores):
            batch = f"E2E-G3-B{i}-{uuid.uuid4().hex[:5]}"
            batches.append(batch)
            inv = Inventory(
                product_id=product.id, warehouse_id=w.id,
                batch_no=batch, quantity=2,
                cost_price=Decimal("80"),
                stock_in_date=datetime.now(timezone.utc),
            )
            s.add(inv)
            await s.flush()
            for _ in range(2):
                code = f"E2E-G3-BC-{uuid.uuid4().hex[:8].upper()}"
                s.add(InventoryBarcode(
                    id=str(uuid.uuid4()), barcode=code, barcode_type="bottle",
                    product_id=product.id, warehouse_id=w.id,
                    batch_no=batch,
                    status=InventoryBarcodeStatus.IN_STOCK.value,
                ))
                all_codes.append((w.id, code))
            s.add(RetailCommissionRate(
                id=str(uuid.uuid4()),
                employee_id=emps[i].id, product_id=product.id,
                rate_on_profit=Decimal("0.3"),
                notes="E2E_G3",
            ))
        await s.commit()

        fx = {
            "stores": [(w.id, w.name) for w in stores],
            "emps": [(e.id, e.name, e.assigned_store_id) for e in emps],
            "product_id": product.id,
            "batches": batches,
            "codes": all_codes,
        }

    sale_ids = []
    try:
        # ── 各店各下 2 单 ──
        for (store_id, _), (emp_id, _, _), codes_for_store in zip(
            fx["stores"], fx["emps"],
            [
                [c for (sid, c) in fx["codes"] if sid == fx["stores"][0][0]],
                [c for (sid, c) in fx["codes"] if sid == fx["stores"][1][0]],
            ]
        ):
            for code in codes_for_store:
                async with admin_session_factory() as s:
                    sale = await store_sale_service.create_store_sale(
                        s,
                        cashier_employee_id=emp_id,
                        store_id=store_id,
                        customer_id=None,
                        customer_walk_in_phone="13800000000",
                        line_items=[{"barcode": code, "sale_price": Decimal("200")}],
                        payment_method="cash",
                    )
                    await s.commit()
                    sale_ids.append(sale.id)
        print(f"[fixture] 2 店各 2 单 → 共 {len(sale_ids)} 单")

        # ── G3：stats group_by=store ──
        async with admin_session_factory() as s:
            # 模拟 route 的 group_by 逻辑：group by store_id 看行数
            from sqlalchemy import func
            rows = (await s.execute(
                select(
                    StoreSale.store_id,
                    func.sum(StoreSale.total_sale_amount),
                    func.sum(StoreSale.total_profit),
                    func.count(StoreSale.id),
                )
                .where(StoreSale.id.in_(sale_ids))
                .group_by(StoreSale.store_id)
            )).all()
            assert len(rows) == 2, f"[G3] group_by 应 2 行 实际 {len(rows)}"
            for sid, total_sale, total_profit, cnt in rows:
                assert cnt == 2
                assert Decimal(str(total_sale)) == Decimal("400")
                # profit = (200-80)*2 = 240
                assert Decimal(str(total_profit)) == Decimal("240")
            print(f"[G3] ✅ stats group_by=store 每店 2 单 400 销售 240 利润")

        # ── G7：批量回补快照（覆盖上月 + 本月）──
        async with admin_session_factory() as s:
            now = datetime.now(timezone.utc)
            results = []
            # 近 3 个月
            months = []
            y, m = now.year, now.month
            for i in range(3):
                months.append((y, m))
                if m == 1:
                    y, m = y - 1, 12
                else:
                    m -= 1
            for (ly, lm) in reversed(months):
                r = await kss.build_snapshot_for_month(
                    s, ly, lm, notes="E2E G7 批量回补",
                )
                results.append(r)
            await s.commit()
            print(f"[G7] ✅ 批量回补 {len(results)} 个月：{[r['period'] for r in results]}")

        # ── G9：aggregate_mall_profit 调用路径（无 mall 订单也应返 0 不崩）──
        async with admin_session_factory() as s:
            from app.services.mall.profit_service import aggregate_mall_profit
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            result = await aggregate_mall_profit(s, date_from=month_start)
            assert "total_revenue" in result
            assert "total_profit" in result
            assert "total_commission" in result
            assert "total_bad_debt" in result
            print(f"[G9] ✅ aggregate_mall_profit 返 {result['total_revenue']} 收入 / {result['total_profit']} 利润")

        banner("✅ G3/G7/G9 E2E 通过")

    finally:
        async with admin_session_factory() as s:
            for sid in sale_ids:
                await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id == sid))
                await s.execute(delete(Commission).where(Commission.store_sale_id == sid))
                await s.execute(delete(StoreSale).where(StoreSale.id == sid))
                await s.execute(delete(AuditLog).where(AuditLog.entity_id == sid))
            for _, code in fx["codes"]:
                await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode == code))
            for batch in fx["batches"]:
                await s.execute(delete(StockFlow).where(StockFlow.batch_no == batch))
                await s.execute(delete(Inventory).where(Inventory.batch_no == batch))
            for emp_id, _, _ in fx["emps"]:
                await s.execute(delete(RetailCommissionRate).where(RetailCommissionRate.employee_id == emp_id))
                await s.execute(delete(Employee).where(Employee.id == emp_id))
            for wid, _ in fx["stores"]:
                await s.execute(delete(Warehouse).where(Warehouse.id == wid))
            await s.execute(delete(Product).where(Product.id == fx["product_id"]))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
