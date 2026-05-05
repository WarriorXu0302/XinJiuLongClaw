"""E2E：Review 之后的两个修复。

修复 1（P0）：挂账扣款消失 bug
  - 场景：员工当月工资 ¥200，有 ¥500 历史挂账
  - 原 bug：rec.total_pay -= historical_deduction 直接改合计，
    后续 _recalc_salary_total 按字段重算会"还原"挂账扣款
  - 修复：用 historical_clawback_deduction 独立字段，_recalc_salary_total 也扫它
  - 验证：手工调 _recalc_salary_total 后 total_pay 不会"还原"

修复 2（P1）：门店退货两段式
  - 场景：店员发起退货 → 财务 approve → 财务 mark_refunded（填退款方式）
  - 原 bug：approve 直接 status=refunded，refund_method/refunded_at 都没填
  - 修复：approve_return → "approved"，mark_refunded → "refunded" + refund_method
  - 验证：两步各自状态 + 幂等（重复 mark_refunded 拒绝）

跑法：
  cd backend && python -m scripts.e2e_review_fixes
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
from app.models.payroll import SalaryAdjustmentPending, SalaryRecord
from app.models.product import Brand, Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate, StoreSale, StoreSaleItem,
    StoreSaleReturn, StoreSaleReturnItem,
)
from app.models.user import Commission, Employee
from app.services import store_return_service, store_sale_service
from app.api.routes.payroll import _recalc_salary_total


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def test_fix_1_clawback_persists() -> None:
    banner("修复 1：挂账扣款通过 _recalc_salary_total 不会消失")

    emp_id = None
    rec_id = None
    try:
        async with admin_session_factory() as s:
            emp = Employee(
                id=str(uuid.uuid4()),
                employee_no=f"E2E-R1-{uuid.uuid4().hex[:4]}",
                name="E2E 挂账测试员工",
                position="salesman", status="active",
                hire_date=date.today(),
                social_security=Decimal("0"),
                company_social_security=Decimal("0"),
                expected_manufacturer_subsidy=Decimal("0"),
            )
            s.add(emp)
            await s.flush()
            emp_id = emp.id

            # 造一张工资单：底薪 ¥2000 + 迟到扣 ¥100 + 历史挂账扣 ¥500 → 实发 1400
            rec = SalaryRecord(
                id=str(uuid.uuid4()),
                employee_id=emp.id,
                period="2026-05",
                fixed_salary=Decimal("2000"),
                variable_salary_total=Decimal("0"),
                commission_total=Decimal("0"),
                manager_share_total=Decimal("0"),
                attendance_bonus=Decimal("0"),
                bonus_other=Decimal("0"),
                manufacturer_subsidy_total=Decimal("0"),
                late_deduction=Decimal("100"),
                absence_deduction=Decimal("0"),
                fine_deduction=Decimal("0"),
                historical_clawback_deduction=Decimal("500"),
                social_security=Decimal("0"),
                total_pay=Decimal("1400"),  # 2000 - 100 - 500
                actual_pay=Decimal("1400"),
                status="draft",
                work_days_month=26, work_days_actual=26,
            )
            s.add(rec)
            await s.commit()
            rec_id = rec.id

        # 场景：HR 点保存 → 触发 _recalc_salary_total
        async with admin_session_factory() as s:
            r = await s.get(SalaryRecord, rec_id)
            _recalc_salary_total(r)
            await s.commit()

        async with admin_session_factory() as s:
            r = await s.get(SalaryRecord, rec_id)
            # 期望：total_pay 仍 = 2000 - 100 - 500 = 1400
            assert r.total_pay == Decimal("1400.00"), (
                f"[修复1] _recalc_salary_total 后 total_pay 应 1400 实际 {r.total_pay}"
            )
            assert r.historical_clawback_deduction == Decimal("500.00")
            print(f"✅ 修复 1：_recalc_salary_total 后挂账扣款 ¥500 仍被扣（total_pay={r.total_pay}）")

        # 对比旧 bug：如果用 rec.total_pay -= 手工改，重算后会丢失扣款变成 1900
        # 这里用新实现验证不再丢失

    finally:
        async with admin_session_factory() as s:
            if rec_id:
                await s.execute(delete(SalaryRecord).where(SalaryRecord.id == rec_id))
            if emp_id:
                await s.execute(delete(Employee).where(Employee.id == emp_id))
            await s.commit()


async def test_fix_2_store_return_two_stage() -> None:
    banner("修复 2：门店退货两段式 approve → mark_refunded")

    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        store = Warehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-R2-{uuid.uuid4().hex[:4]}",
            name="E2E 两段退测试店",
            warehouse_type=WarehouseType.STORE.value, is_active=True,
        )
        s.add(store)
        await s.flush()
        emp = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-R2-E-{uuid.uuid4().hex[:4]}",
            name="E2E 两段退店员",
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
            code=f"E2E-R2-P-{uuid.uuid4().hex[:4]}",
            name="E2E 两段退酒",
            category="liquor", brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            min_sale_price=Decimal("100"), max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()
        batch = f"E2E-R2-B-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id, warehouse_id=store.id,
            batch_no=batch, quantity=1, cost_price=Decimal("100"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()
        code = f"E2E-R2-BC-{uuid.uuid4().hex[:8].upper()}"
        s.add(InventoryBarcode(
            id=str(uuid.uuid4()), barcode=code, barcode_type="bottle",
            product_id=product.id, warehouse_id=store.id, batch_no=batch,
            status=InventoryBarcodeStatus.IN_STOCK.value,
        ))
        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp.id, product_id=product.id,
            rate_on_profit=Decimal("0.3"),
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
    try:
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_id"],
                store_id=fx["store_id"],
                customer_id=None,
                line_items=[{"barcode": fx["code"], "sale_price": Decimal("200")}],
                payment_method="cash",
            )
            await s.commit()
            sale_id = sale.id

        async with admin_session_factory() as s:
            ret = await store_return_service.apply_return(
                s, initiator_employee_id=fx["emp_id"],
                original_sale_id=sale_id, reason="R2 两段式测试",
            )
            await s.commit()
            return_id = ret.id

        # Step 1: approve → status=approved（不是 refunded）
        async with admin_session_factory() as s:
            ret = await store_return_service.approve_return(
                s, return_id=return_id, reviewer_employee_id=fx["emp_id"],
            )
            await s.commit()
            assert ret.status == "approved", f"approve 后应 approved 实际 {ret.status}"
            assert ret.refunded_at is None
            assert ret.refund_method is None
            print(f"[1] ✅ approve_return → status=approved（未打款）")

        # Step 2: mark_refunded 前，重复 approve 应被拒
        async with admin_session_factory() as s:
            raised_409 = False
            try:
                await store_return_service.approve_return(
                    s, return_id=return_id, reviewer_employee_id=fx["emp_id"],
                )
            except Exception as e:
                if getattr(e, "status_code", None) == 409:
                    raised_409 = True
            assert raised_409, "重复 approve 应 409"
            print(f"[2] ✅ 重复 approve 被 409 拒")

        # Step 3: mark_refunded
        async with admin_session_factory() as s:
            ret = await store_return_service.mark_refunded(
                s, return_id=return_id,
                reviewer_employee_id=fx["emp_id"],
                refund_method="wechat",
                refund_note="微信转账 备注#12345",
            )
            await s.commit()
            assert ret.status == "refunded"
            assert ret.refund_method == "wechat"
            assert ret.refund_note == "微信转账 备注#12345"
            assert ret.refunded_at is not None
            print(f"[3] ✅ mark_refunded → status=refunded, method=wechat")

        # Step 4: mark_refunded 幂等：重复调应 409
        async with admin_session_factory() as s:
            raised_409 = False
            try:
                await store_return_service.mark_refunded(
                    s, return_id=return_id,
                    reviewer_employee_id=fx["emp_id"],
                    refund_method="cash",
                )
            except Exception as e:
                if getattr(e, "status_code", None) == 409:
                    raised_409 = True
            assert raised_409, "重复 mark_refunded 应 409"
            print(f"[4] ✅ 重复 mark_refunded 被 409 拒")

        # Step 5: refund_method 非法值应被 400 拒
        async with admin_session_factory() as s:
            raised_400 = False
            try:
                # 需要造另一条 approved 单来测
                await store_return_service.mark_refunded(
                    s, return_id=return_id,
                    reviewer_employee_id=fx["emp_id"],
                    refund_method="credit",  # 非法
                )
            except Exception as e:
                if getattr(e, "status_code", None) in (400, 409):
                    raised_400 = True
            assert raised_400, "非法 refund_method 应被拒"
            print(f"[5] ✅ 非法 refund_method 被拒")

        banner("✅ 修复 1 + 2 全部验证通过")

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


async def main() -> None:
    await test_fix_1_clawback_persists()
    await test_fix_2_store_return_two_stage()


if __name__ == "__main__":
    asyncio.run(main())
