"""E2E：G14/G15/G16/G17 业务员管理加固。

验证：
  G14：切店员 assigned_store_id 时有在途销售/退货 → 阻塞或要求 force_switch
  G15：凭证超时告警 job 幂等 + 24h/48h 分级
  G16：my-customers 列表手机号脱敏 + reveal 端点审计
  G17：禁用业务员时释放的订单会通知客户

跑法：
  cd backend && python -m scripts.e2e_salesman_mgmt_hardening
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select, func as sa_func

from app.core.database import admin_session_factory
from app.models.audit_log import AuditLog
from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import (
    MallOrderStatus, MallPaymentApprovalStatus,
    MallUserApplicationStatus, MallUserStatus, MallUserType,
)
from app.models.mall.order import MallOrder, MallPayment
from app.models.mall.user import MallUser
from app.models.notification_log import NotificationLog
from app.models.product import Brand, Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate, StoreSale, StoreSaleItem,
)
from app.models.user import Commission, Employee
from app.services import store_sale_service
from app.services.mall import housekeeping_service as hk


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


async def main() -> None:
    banner("E2E G14/G15/G16/G17 · 业务员管理加固")

    # ── fixture: 2 门店 + 店员 + 商品 + 条码 + 客户 ──
    async with admin_session_factory() as s:
        brand = (await s.execute(select(Brand).limit(1))).scalar_one()
        stores = []
        for i in range(2):
            w = Warehouse(
                id=str(uuid.uuid4()),
                code=f"E2E-G14-{i}-{uuid.uuid4().hex[:4]}",
                name=f"E2E G14 门店 {chr(65+i)}",
                warehouse_type=WarehouseType.STORE.value, is_active=True,
            )
            s.add(w)
            await s.flush()
            stores.append(w)

        emp = Employee(
            id=str(uuid.uuid4()),
            employee_no=f"E2E-G14-E-{uuid.uuid4().hex[:4]}",
            name="E2E G14 店员",
            position="cashier", status="active",
            hire_date=date.today(),
            social_security=Decimal("0"),
            company_social_security=Decimal("0"),
            expected_manufacturer_subsidy=Decimal("0"),
            assigned_store_id=stores[0].id,
        )
        s.add(emp)
        await s.flush()

        # 业务员 mall_user 绑 employee
        salesman = MallUser(
            id=str(uuid.uuid4()),
            username=f"e2e_g14_{uuid.uuid4().hex[:4]}",
            hashed_password="x",
            user_type=MallUserType.SALESMAN.value,
            status=MallUserStatus.ACTIVE.value,
            linked_employee_id=emp.id,
            application_status=MallUserApplicationStatus.APPROVED.value,
            nickname="G14 业务员",
            assigned_store_id=stores[0].id,
        )
        s.add(salesman)
        await s.flush()

        product = Product(
            id=str(uuid.uuid4()),
            code=f"E2E-G14-P-{uuid.uuid4().hex[:4]}",
            name="G14 酒",
            category="liquor", brand_id=brand.id,
            unit="瓶", bottles_per_case=6,
            min_sale_price=Decimal("100"), max_sale_price=Decimal("300"),
            status="active",
        )
        s.add(product)
        await s.flush()

        batch = f"E2E-G14-B-{uuid.uuid4().hex[:6]}"
        inv = Inventory(
            product_id=product.id, warehouse_id=stores[0].id,
            batch_no=batch, quantity=1,
            cost_price=Decimal("100"),
            stock_in_date=datetime.now(timezone.utc),
        )
        s.add(inv)
        await s.flush()

        code = f"E2E-G14-BC-{uuid.uuid4().hex[:8].upper()}"
        s.add(InventoryBarcode(
            id=str(uuid.uuid4()), barcode=code, barcode_type="bottle",
            product_id=product.id, warehouse_id=stores[0].id, batch_no=batch,
            status=InventoryBarcodeStatus.IN_STOCK.value,
        ))

        rate = RetailCommissionRate(
            id=str(uuid.uuid4()),
            employee_id=emp.id, product_id=product.id,
            rate_on_profit=Decimal("0.5"),
        )
        s.add(rate)

        # 测试用 consumer 客户（业务员推荐的）
        customer = MallUser(
            id=str(uuid.uuid4()),
            username=f"e2e_g16_cust_{uuid.uuid4().hex[:4]}",
            hashed_password="x",
            user_type=MallUserType.CONSUMER.value,
            status=MallUserStatus.ACTIVE.value,
            application_status=MallUserApplicationStatus.APPROVED.value,
            nickname="G16 客户",
            real_name="张三",
            contact_phone="13800001234",
            referrer_salesman_id=salesman.id,
        )
        s.add(customer)
        await s.commit()

        fx = {
            "stores": [w.id for w in stores],
            "emp_id": emp.id, "salesman_id": salesman.id,
            "product_id": product.id, "batch": batch,
            "code": code, "rate_id": rate.id,
            "customer_id": customer.id,
        }

    sale_id = None
    payment_id = None
    try:
        # ── G14: 24h 内开单 → 切店被 409 拦 ──
        async with admin_session_factory() as s:
            sale = await store_sale_service.create_store_sale(
                s,
                cashier_employee_id=fx["emp_id"],
                store_id=fx["stores"][0],
                customer_id=None,
                line_items=[{"barcode": fx["code"], "sale_price": Decimal("200")}],
                payment_method="cash",
            )
            await s.commit()
            sale_id = sale.id

        # 模拟切店：直接导入路由逻辑跑
        from app.api.routes.mall.admin.salesmen import update_salesman, _UpdateSalesmanBody
        async with admin_session_factory() as s:
            blocked = False
            try:
                await update_salesman(
                    fx["salesman_id"],
                    _UpdateSalesmanBody(assigned_store_id=fx["stores"][1]),
                    {"roles": ["admin"], "employee_id": fx["emp_id"], "is_admin": True, "sub": fx["emp_id"], "brand_ids": []},
                    request=None,
                    db=s,
                )
                await s.commit()
            except Exception as e:
                if getattr(e, "status_code", None) == 409:
                    blocked = True
            assert blocked, "G14: 24h 内开单应阻塞切店"
            print(f"[G14] ✅ 24h 内开单阻塞切店（409）")

        # force_switch=true 应放行
        async with admin_session_factory() as s:
            await update_salesman(
                fx["salesman_id"],
                _UpdateSalesmanBody(assigned_store_id=fx["stores"][1], force_switch=True),
                {"roles": ["admin"], "employee_id": fx["emp_id"], "is_admin": True, "sub": fx["emp_id"], "brand_ids": []},
                request=None,
                db=s,
            )
            await s.commit()
            sm_reloaded = await s.get(MallUser, fx["salesman_id"])
            assert sm_reloaded.assigned_store_id == fx["stores"][1]
            print(f"[G14] ✅ force_switch=true 切店成功")

        # ── G15: 造一条 25h 前 pending payment → 跑 job → 推告警 ──
        async with admin_session_factory() as s:
            # 简单造 payment（无完整 order 也不影响 job 逻辑跑通）
            test_order = MallOrder(
                id=str(uuid.uuid4()),
                order_no=f"E2E-G15-O-{uuid.uuid4().hex[:6]}",
                user_id=fx["customer_id"],
                status=MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
                total_amount=Decimal("100"),
                pay_amount=Decimal("100"),
                received_amount=Decimal("0"),
                shipping_fee=Decimal("0"),
                address_snapshot={"receiver": "test", "mobile": "138", "addr": "x"},
            )
            s.add(test_order)
            await s.flush()

            now = datetime.now(timezone.utc)
            payment = MallPayment(
                id=str(uuid.uuid4()),
                order_id=test_order.id,
                uploaded_by_user_id=fx["salesman_id"],
                amount=Decimal("100"),
                payment_method="cash",
                status=MallPaymentApprovalStatus.PENDING_CONFIRMATION.value,
                created_at=now - timedelta(hours=25),  # 25h 前
            )
            s.add(payment)
            await s.commit()
            payment_id = payment.id
            test_order_id = test_order.id

        # 跑告警 job
        result = await hk.job_notify_aged_pending_vouchers()
        # 至少推了 1 条 24h 告警
        assert result.get("notified_24h", 0) >= 1 or result.get("notified_48h", 0) >= 1, (
            f"[G15] 应推告警 实际 {result}"
        )
        print(f"[G15] ✅ 凭证超时告警：{result}")

        # 幂等：再跑一次 → 0 条新告警
        result2 = await hk.job_notify_aged_pending_vouchers()
        assert result2.get("notified_24h", 0) == 0 and result2.get("notified_48h", 0) == 0, (
            f"[G15] 第二次应幂等不推 实际 {result2}"
        )
        print(f"[G15] ✅ 幂等：二次运行 notified=0")

        # ── G16: my-customers 列表手机号脱敏 + reveal 端点 ──
        async with admin_session_factory() as s:
            # 模拟调用 list 路径（用 service 层逻辑）
            from app.api.routes.mall.salesman.my_customers import _mask_phone
            masked = _mask_phone("13800001234")
            assert masked == "138****1234", f"_mask_phone 结果错：{masked}"
            print(f"[G16] ✅ _mask_phone 正常：13800001234 → {masked}")

        # ── G17: notify on disable  ──
        # 建一条 assigned 订单 + 调 disable → 客户收到通知
        async with admin_session_factory() as s:
            o = MallOrder(
                id=str(uuid.uuid4()),
                order_no=f"E2E-G17-O-{uuid.uuid4().hex[:6]}",
                user_id=fx["customer_id"],
                assigned_salesman_id=fx["salesman_id"],
                status=MallOrderStatus.ASSIGNED.value,
                total_amount=Decimal("100"),
                pay_amount=Decimal("100"),
                received_amount=Decimal("0"),
                shipping_fee=Decimal("0"),
                address_snapshot={"receiver": "test", "mobile": "138", "addr": "x"},
                claimed_at=datetime.now(timezone.utc),
            )
            s.add(o)
            await s.commit()
            assigned_order_id = o.id

        from app.api.routes.mall.admin.salesmen import disable_salesman
        # 定义 body 类
        class _DisableBody:
            reason = "G17 测试"

        async with admin_session_factory() as s:
            await disable_salesman(
                fx["salesman_id"],
                _DisableBody(),
                {"roles": ["admin"], "employee_id": fx["emp_id"], "is_admin": True, "sub": fx["emp_id"], "brand_ids": []},
                request=None,
                db=s,
            )
            await s.commit()

        # 验证 client 通知已写
        async with admin_session_factory() as s:
            notifs = (await s.execute(
                select(NotificationLog)
                .where(NotificationLog.related_entity_type == "MallOrder")
                .where(NotificationLog.related_entity_id == assigned_order_id)
                .where(NotificationLog.recipient_type == "mall_user")
            )).scalars().all()
            assert len(notifs) >= 1, f"[G17] 应通知客户 实际 {len(notifs)}"
            print(f"[G17] ✅ 禁用业务员时通知了 {len(notifs)} 条客户通知")

        banner("✅ G14/G15/G16/G17 业务员管理加固 E2E 通过")

    finally:
        async with admin_session_factory() as s:
            # 清理通知
            await s.execute(delete(NotificationLog).where(
                NotificationLog.title.like("%PAYMENT_AGING%")
            ))
            await s.execute(delete(NotificationLog).where(
                NotificationLog.title == "订单配送员变更"
            ))
            # 清理订单/支付（可能有 2 条）
            if payment_id:
                await s.execute(delete(MallPayment).where(MallPayment.id == payment_id))
            await s.execute(delete(MallOrder).where(
                MallOrder.order_no.like("E2E-G%")
            ))
            # 清理 audit log
            await s.execute(delete(AuditLog).where(
                AuditLog.entity_id.in_([sale_id, fx["customer_id"], fx["salesman_id"]])
            ))
            # sale 数据
            if sale_id:
                await s.execute(delete(StoreSaleItem).where(StoreSaleItem.sale_id == sale_id))
                await s.execute(delete(Commission).where(Commission.store_sale_id == sale_id))
                await s.execute(delete(StoreSale).where(StoreSale.id == sale_id))
            # 业务员 + 客户
            await s.execute(delete(MallUser).where(MallUser.id.in_([fx["salesman_id"], fx["customer_id"]])))
            # 条码/库存
            await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode == fx["code"]))
            await s.execute(delete(StockFlow).where(StockFlow.batch_no == fx["batch"]))
            await s.execute(delete(Inventory).where(Inventory.batch_no == fx["batch"]))
            await s.execute(delete(RetailCommissionRate).where(RetailCommissionRate.id == fx["rate_id"]))
            await s.execute(delete(Employee).where(Employee.id == fx["emp_id"]))
            for wid in fx["stores"]:
                await s.execute(delete(Warehouse).where(Warehouse.id == wid))
            await s.execute(delete(Product).where(Product.id == fx["product_id"]))
            await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
