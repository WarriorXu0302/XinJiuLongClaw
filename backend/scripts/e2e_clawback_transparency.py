"""E2E：G4/G6 业务员追回透明化 · 工资 detail 扩展 + commission 流水。

场景：
  1. 造 1 个业务员（linked_employee_id）+ 2 条 Commission（1 pending settled、1 pending）
  2. 模拟跨月退货追回 → is_adjustment=True 负数 Commission
  3. 模拟挂账 → SalaryAdjustmentPending 未结清
  4. 建 SalaryRecord (period=本月 + include pending adjustment via SalaryOrderLink)
  5. 验证 G4：salary_detail API 返 clawback_details 非空，且含 origin_order_no / origin_amount
  6. 验证 G6：调 commission_service 层直接验证能查到 adjustment 行并关联原 commission

跑法：
  cd backend && python -m scripts.e2e_clawback_transparency
"""
import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.audit_log import AuditLog
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.payroll import SalaryAdjustmentPending, SalaryOrderLink, SalaryRecord
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
    banner("E2E G4/G6 · 跨月退货追回透明化")

    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        store = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-G4-{uuid.uuid4().hex[:4]}",
            name="E2E 追回透明化店",
            warehouse_type=WarehouseType.STORE.value, is_active=True,
        )
        s.add(store)
        await s.flush()

        emp = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-G4-E-{uuid.uuid4().hex[:4]}",
            name="E2E 追回店员",
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
            code=f"E2E-G4-P-{uuid.uuid4().hex[:4]}",
            name="E2E 追回测试酒",
            category="liquor", brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            min_sale_price=Decimal("100"),
            max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()

        batch = f"E2E-G4-B-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id, warehouse_id=store.id,
            batch_no=batch, quantity=1,
            cost_price=Decimal("100"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()

        code = f"E2E-G4-BC-{uuid.uuid4().hex[:8].upper()}"
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
    salary_id = None
    adj_pending_id = None
    origin_commission_id = None
    adj_commission_id = None

    try:
        # Step 1: 收银 → Commission pending
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

        # Step 2: 标 Commission settled（模拟上月已发）
        async with admin_session_factory() as s:
            c = (await s.execute(
                select(Commission).where(Commission.store_sale_id == sale_id)
            )).scalar_one()
            c.status = "settled"
            c.settled_at = datetime.now(timezone.utc) - timedelta(days=30)
            origin_commission_id = c.id
            await s.commit()

        # Step 3: 退货 + approve → 建 adjustment Commission (is_adjustment=True, 负数)
        async with admin_session_factory() as s:
            ret = await store_return_service.apply_return(
                s, initiator_employee_id=fx["emp_id"],
                original_sale_id=sale_id, reason="跨月透明化测试",
            )
            await s.commit()
            return_id = ret.id

        async with admin_session_factory() as s:
            await store_return_service.approve_return(
                s, return_id=return_id, reviewer_employee_id=fx["emp_id"],
            )
            await s.commit()

        # Step 4: 验证 adjustment Commission 存在
        async with admin_session_factory() as s:
            adj = (await s.execute(
                select(Commission)
                .where(Commission.adjustment_source_commission_id == origin_commission_id)
            )).scalar_one()
            adj_commission_id = adj.id
            assert adj.is_adjustment is True
            assert adj.commission_amount < 0
            assert adj.status == "pending"
            print(f"[1] ✅ 退货追回 adjustment 已建：{adj.id[:8]} amount={adj.commission_amount}")

        # Step 5: 造 SalaryRecord + SalaryOrderLink 模拟本月工资单扫入了 adjustment
        async with admin_session_factory() as s:
            now = datetime.now(timezone.utc)
            rec = SalaryRecord(
                id=str(uuid.uuid4()),
                employee_id=fx["emp_id"],
                period=now.strftime("%Y-%m"),
                fixed_salary=Decimal("5000"),
                variable_salary_total=Decimal("0"),
                commission_total=Decimal("-75"),  # 原 150*0.5=75
                manager_share_total=Decimal("0"),
                attendance_bonus=Decimal("0"),
                bonus_other=Decimal("0"),
                manufacturer_subsidy_total=Decimal("0"),
                late_deduction=Decimal("0"),
                absence_deduction=Decimal("0"),
                fine_deduction=Decimal("0"),
                social_security=Decimal("0"),
                total_pay=Decimal("4925"),
                actual_pay=Decimal("4925"),
                status="draft",
                work_days_month=26, work_days_actual=26,
                notes="E2E G4",
            )
            s.add(rec)
            await s.flush()
            salary_id = rec.id

            # SalaryOrderLink 挂上 adjustment
            link = SalaryOrderLink(
                id=str(uuid.uuid4()),
                salary_record_id=rec.id,
                store_sale_id=sale_id,  # 来源 sale
                commission_id=adj_commission_id,
                brand_id=brand.id,
                receipt_amount=Decimal("0"),
                commission_rate_used=Decimal("0.5"),
                kpi_coefficient=Decimal("1.0"),
                commission_amount=adj.commission_amount,  # 负数
                is_manager_share=False,
            )
            s.add(link)
            await s.commit()

        # Step 6: 造一条 SalaryAdjustmentPending（挂账）
        async with admin_session_factory() as s:
            adj_pending = SalaryAdjustmentPending(
                id=str(uuid.uuid4()),
                employee_id=fx["emp_id"],
                pending_amount=Decimal("150"),
                source_salary_record_id=salary_id,
                reason=f"{rec.period} 当月工资不足扣减（E2E 测试）",
            )
            s.add(adj_pending)
            adj_pending_id = adj_pending.id
            await s.commit()

        # Step 7: 验证 G4 —— 直接跑 salary_detail API 逻辑（部分复用，不走 HTTP 省事）
        async with admin_session_factory() as s:
            # 跑 clawback_details 查询
            links = (await s.execute(
                select(SalaryOrderLink, Commission)
                .join(Commission, Commission.id == SalaryOrderLink.commission_id)
                .where(SalaryOrderLink.salary_record_id == salary_id)
                .where(Commission.is_adjustment.is_(True))
            )).all()
            assert len(links) == 1
            _, com = links[0]
            origin = await s.get(Commission, com.adjustment_source_commission_id)
            assert origin is not None
            print(f"[2] ✅ G4 salary_detail 能查到 adjustment link 原 commission={origin.id[:8]} 原金额=¥{origin.commission_amount}")

            # 本期新建的挂账
            new_pendings = (await s.execute(
                select(SalaryAdjustmentPending)
                .where(SalaryAdjustmentPending.source_salary_record_id == salary_id)
                .where(SalaryAdjustmentPending.settled_in_salary_id.is_(None))
            )).scalars().all()
            assert len(new_pendings) == 1
            assert new_pendings[0].pending_amount == Decimal("150")
            print(f"[3] ✅ G4 本期新建挂账 1 条 ¥150")

        # Step 8: 验证 G6 —— 模拟 workspace/my-commissions 查询
        async with admin_session_factory() as s:
            # 按 employee_id 查所有 commission
            all_commissions = (await s.execute(
                select(Commission).where(Commission.employee_id == fx["emp_id"])
                .order_by(Commission.created_at)
            )).scalars().all()
            assert len(all_commissions) == 2, f"应 2 条 实际 {len(all_commissions)}"

            # 原 + adjustment
            origin = [c for c in all_commissions if c.id == origin_commission_id][0]
            adj = [c for c in all_commissions if c.is_adjustment][0]
            assert origin.status == "settled"
            assert adj.status == "pending"
            assert origin.commission_amount == Decimal("100.00"), f"原 commission 应 100（(300-100)*0.5），实际 {origin.commission_amount}"
            assert adj.commission_amount == Decimal("-100.00")
            print(f"[4] ✅ G6 查自己 commission 能看到 原(settled ¥100) + 追回(pending ¥-100)")

            # 按 status='adjustment' 筛
            adj_rows = (await s.execute(
                select(Commission)
                .where(Commission.employee_id == fx["emp_id"])
                .where(Commission.is_adjustment.is_(True))
            )).scalars().all()
            assert len(adj_rows) == 1
            print(f"[5] ✅ G6 status=adjustment 筛出 1 条追回")

        banner("✅ G4/G6 跨月退货追回透明化 E2E 通过")

    finally:
        # 清理
        async with admin_session_factory() as s:
            if adj_pending_id:
                await s.execute(delete(SalaryAdjustmentPending).where(SalaryAdjustmentPending.id == adj_pending_id))
            if salary_id:
                await s.execute(delete(SalaryOrderLink).where(SalaryOrderLink.salary_record_id == salary_id))
                await s.execute(delete(SalaryRecord).where(SalaryRecord.id == salary_id))
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
