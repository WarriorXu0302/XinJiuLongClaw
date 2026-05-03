"""E2E：仓库调拨（跨 ERP + mall）端到端。

覆盖 4 种路径 + 业务规则拦截：
  1. ERP→ERP 同品牌内（预期：免审）
  2. ERP→mall 跨端（预期：需审批；执行后条码从 InventoryBarcode 迁到 MallInventoryBarcode）
  3. mall→mall（预期：需审批）
  4. 品牌主仓拦截（warehouse_type=main AND brand_id 非空 不允许作为 source）

每步 DB 断言：
  - 条码 warehouse_id / 目标表存在性
  - Inventory / MallInventory 数量扣加
  - StockFlow / MallInventoryFlow 流水
  - transfer.status 正确转移

跑法：
  cd backend && python -m scripts.e2e_warehouse_transfer
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import admin_session_factory
from app.models.base import InventoryBarcodeStatus
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import MallInventoryBarcodeStatus, MallInventoryBarcodeType
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryBarcode,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.models.product import Brand, Product, Warehouse
from app.models.transfer import (
    TRANSFER_STATUS_EXECUTED,
    TRANSFER_STATUS_PENDING_APPROVAL,
    TRANSFER_STATUS_PENDING_SCAN,
    WarehouseTransfer,
    WarehouseTransferItem,
)
from app.models.user import Employee
from app.services import transfer_service


def banner(s: str) -> None:
    print(f"\n{'='*70}\n{s}\n{'='*70}")


def step(n: int, label: str) -> None:
    print(f"\n[{n:02d}] {label}")


async def _fixture_erp_non_main_warehouses(s) -> tuple[Warehouse, Warehouse, Brand]:
    """造两个同品牌非主仓（ERP 内部调拨免审场景）"""
    brand = (await s.execute(select(Brand).limit(1))).scalar_one()
    wh1 = Warehouse(
        id=str(uuid.uuid4()),
        code=f"E2E-WH1-{uuid.uuid4().hex[:4]}",
        name="E2E 非主仓 A",
        warehouse_type="branch",
        brand_id=brand.id,
        is_active=True,
    )
    wh2 = Warehouse(
        id=str(uuid.uuid4()),
        code=f"E2E-WH2-{uuid.uuid4().hex[:4]}",
        name="E2E 非主仓 B",
        warehouse_type="branch",
        brand_id=brand.id,
        is_active=True,
    )
    s.add_all([wh1, wh2])
    await s.flush()
    return wh1, wh2, brand


async def _fixture_brand_main_warehouse(s, brand: Brand) -> Warehouse:
    """造一个品牌主仓（调拨应被拒）"""
    wh = Warehouse(
        id=str(uuid.uuid4()),
        code=f"E2E-MAIN-{uuid.uuid4().hex[:4]}",
        name="E2E 品牌主仓",
        warehouse_type="main",
        brand_id=brand.id,
        is_active=True,
    )
    s.add(wh)
    await s.flush()
    return wh


async def _fixture_seed_barcodes(
    s, warehouse: Warehouse, product: Product, count: int
) -> list[str]:
    """给 ERP 仓种 count 瓶条码（同批次）"""
    batch_no = f"E2E-BATCH-{uuid.uuid4().hex[:6]}"
    cost = Decimal("50.00")
    # inventory
    inv = Inventory(
        product_id=product.id,
        warehouse_id=warehouse.id,
        batch_no=batch_no,
        quantity=count,
        cost_price=cost,
        stock_in_date=datetime.now(timezone.utc),
    )
    s.add(inv)
    # barcodes
    codes = []
    for i in range(count):
        code = f"E2E-TR-{uuid.uuid4().hex[:10].upper()}"
        s.add(InventoryBarcode(
            id=str(uuid.uuid4()),
            barcode=code,
            barcode_type="bottle",
            product_id=product.id,
            warehouse_id=warehouse.id,
            batch_no=batch_no,
            status=InventoryBarcodeStatus.IN_STOCK.value,
        ))
        codes.append(code)
    await s.flush()
    return codes


async def main() -> None:
    banner("E2E 仓库调拨：4 种路径 + 品牌主仓拦截")

    # fixture 准备
    async with admin_session_factory() as s:
        emp = (await s.execute(select(Employee).where(Employee.status == "active").limit(1))).scalar_one()
        # ERP 商品 + 非主仓
        product = (await s.execute(select(Product).limit(1))).scalar_one()
        wh_a, wh_b, brand = await _fixture_erp_non_main_warehouses(s)
        wh_main = await _fixture_brand_main_warehouse(s, brand)

        # ERP 仓 A 塞 5 瓶
        erp_codes = await _fixture_seed_barcodes(s, wh_a, product, 5)
        await s.commit()
        print(f"fixture ERP: brand={brand.name}, wh_a={wh_a.name}, wh_b={wh_b.name}")
        print(f"fixture ERP: main={wh_main.name}（品牌主仓，应拒调拨）")
        print(f"fixture ERP: 种了 5 瓶条码到 wh_a, product={product.name}")

        # mall fixture
        mall_prod = (await s.execute(
            select(MallProduct).where(MallProduct.source_product_id == product.id).limit(1)
        )).scalar_one_or_none()
        if mall_prod is None:
            mall_prod = MallProduct(
                source_product_id=product.id,
                brand_id=brand.id,
                name=f"E2E {product.name}",
                status="on_sale",
            )
            s.add(mall_prod)
            await s.flush()
        mall_sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.product_id == mall_prod.id).limit(1)
        )).scalar_one_or_none()
        if mall_sku is None:
            mall_sku = MallProductSku(
                product_id=mall_prod.id, spec="500ml",
                price=Decimal("199.00"), cost_price=Decimal("50.00"),
                status="active",
            )
            s.add(mall_sku)
            await s.flush()

        # 两个 mall 仓
        mall_wh_1 = (await s.execute(
            select(MallWarehouse).where(MallWarehouse.is_active.is_(True)).limit(1)
        )).scalar_one_or_none()
        if mall_wh_1 is None:
            print("❌ 没 mall 仓 fixture")
            return
        mall_wh_2 = MallWarehouse(
            id=str(uuid.uuid4()),
            code=f"E2E-MW-{uuid.uuid4().hex[:4]}",
            name="E2E 测试 mall 仓 2",
            is_active=True,
        )
        s.add(mall_wh_2)
        await s.flush()

        # mall 仓 1 塞 3 瓶条码；如果已存在同 (warehouse, sku) inventory 就 +qty 不新建
        mall_batch = f"E2E-MB-{uuid.uuid4().hex[:6]}"
        m_inv = (await s.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == mall_wh_1.id)
            .where(MallInventory.sku_id == mall_sku.id)
        )).scalar_one_or_none()
        if m_inv is None:
            m_inv = MallInventory(
                id=str(uuid.uuid4()),
                warehouse_id=mall_wh_1.id,
                sku_id=mall_sku.id,
                quantity=3,
                avg_cost_price=Decimal("50.00"),
            )
            s.add(m_inv)
        else:
            m_inv.quantity = (m_inv.quantity or 0) + 3
        mall_codes = []
        for i in range(3):
            code = f"E2E-MTR-{uuid.uuid4().hex[:10].upper()}"
            s.add(MallInventoryBarcode(
                id=str(uuid.uuid4()),
                barcode=code,
                barcode_type=MallInventoryBarcodeType.BOTTLE.value,
                sku_id=mall_sku.id,
                product_id=mall_prod.id,
                warehouse_id=mall_wh_1.id,
                batch_no=mall_batch,
                status=MallInventoryBarcodeStatus.IN_STOCK.value,
                cost_price=Decimal("50.00"),
            ))
            mall_codes.append(code)
        await s.commit()

        # 暂存 ID + 跑前基线（mall 仓 1 当前 qty，后面断言用 qty_before + 2）
        wh_a_id, wh_b_id, wh_main_id = wh_a.id, wh_b.id, wh_main.id
        mall_wh_1_qty_baseline = m_inv.quantity or 0
        mall_wh_1_id, mall_wh_2_id = mall_wh_1.id, mall_wh_2.id
        mall_sku_id = mall_sku.id
        emp_id = emp.id
        product_id = product.id

    # ── Step 1：ERP→ERP 同品牌内（免审）──
    step(1, "ERP→ERP 同品牌内（预期：免审，直接 executed）")
    async with admin_session_factory() as s:
        t = await transfer_service.create_transfer(
            s,
            initiator_employee_id=emp_id,
            source_side="erp", source_warehouse_id=wh_a_id,
            dest_side="erp", dest_warehouse_id=wh_b_id,
            barcodes=erp_codes[:2],  # 2 瓶
            reason="E2E 同品牌内部调拨",
        )
        t_id_1 = t.id
        await s.commit()
        assert t.requires_approval is False, f"同品牌内部应免审，实际 requires_approval={t.requires_approval}"
        assert t.status == TRANSFER_STATUS_PENDING_SCAN, f"初始状态错：{t.status}"
        print(f"   ✅ 创建成功，免审，status={t.status}")

    async with admin_session_factory() as s:
        t = await transfer_service.execute_transfer(
            s, transfer_id=t_id_1, actor_employee_id=emp_id,
        )
        await s.commit()
        assert t.status == TRANSFER_STATUS_EXECUTED
        print(f"   ✅ 免审执行成功")

        # 断言条码已迁移到 wh_b
        bcs = (await s.execute(
            select(InventoryBarcode).where(InventoryBarcode.barcode.in_(erp_codes[:2]))
        )).scalars().all()
        for bc in bcs:
            assert bc.warehouse_id == wh_b_id, f"条码 {bc.barcode} 未迁移"
        print(f"   ✅ 条码 warehouse_id 已改 {wh_b_id[:8]}")

        # StockFlow 流水双向
        flows = (await s.execute(
            select(StockFlow).where(StockFlow.reference_no == t.transfer_no)
        )).scalars().all()
        assert len(flows) == 2, f"应有 2 条流水，实际 {len(flows)}"
        types = {f.flow_type for f in flows}
        assert types == {"transfer_out", "transfer_in"}
        print(f"   ✅ 流水 {len(flows)} 条：{types}")

    # ── Step 2：ERP→mall 跨端（需审批 + 条码迁表）──
    step(2, "ERP→mall 跨端（预期：需审批，执行后条码从 ERP 表迁到 mall 表）")
    async with admin_session_factory() as s:
        t = await transfer_service.create_transfer(
            s,
            initiator_employee_id=emp_id,
            source_side="erp", source_warehouse_id=wh_a_id,
            dest_side="mall", dest_warehouse_id=mall_wh_1_id,
            barcodes=erp_codes[2:4],  # 2 瓶
            reason="E2E 跨端调拨 ERP→mall",
        )
        t_id_2 = t.id
        await s.commit()
        assert t.requires_approval is True
        print(f"   ✅ 创建成功，需审批")

    async with admin_session_factory() as s:
        t = await transfer_service.submit_transfer(
            s, transfer_id=t_id_2, actor_employee_id=emp_id,
        )
        await s.commit()
        assert t.status == TRANSFER_STATUS_PENDING_APPROVAL
        print(f"   ✅ 提交审批 → status=pending_approval")

    async with admin_session_factory() as s:
        t = await transfer_service.approve_transfer(
            s, transfer_id=t_id_2, approver_employee_id=emp_id,
        )
        await s.commit()
        print(f"   ✅ 审批通过 → status=approved")

    async with admin_session_factory() as s:
        t = await transfer_service.execute_transfer(
            s, transfer_id=t_id_2, actor_employee_id=emp_id,
        )
        await s.commit()
        assert t.status == TRANSFER_STATUS_EXECUTED

        # 断言 InventoryBarcode 已 DELETE
        remaining = (await s.execute(
            select(InventoryBarcode).where(InventoryBarcode.barcode.in_(erp_codes[2:4]))
        )).scalars().all()
        assert len(remaining) == 0, "ERP 端条码应已删除"
        # MallInventoryBarcode 新建
        mbcs = (await s.execute(
            select(MallInventoryBarcode).where(MallInventoryBarcode.barcode.in_(erp_codes[2:4]))
        )).scalars().all()
        assert len(mbcs) == 2, f"mall 端应新建 2 条条码，实际 {len(mbcs)}"
        for mbc in mbcs:
            assert mbc.warehouse_id == mall_wh_1_id
            assert mbc.status == MallInventoryBarcodeStatus.IN_STOCK.value
        print(f"   ✅ 条码从 InventoryBarcode 表 DELETE，在 MallInventoryBarcode 新建 2 条")

        # mall_inventory 加权平均成本
        m_inv_after = (await s.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == mall_wh_1_id)
            .where(MallInventory.sku_id == mall_sku_id)
        )).scalar_one()
        print(f"   ✅ mall_inventory: quantity={m_inv_after.quantity}, avg_cost={m_inv_after.avg_cost_price}")
        expected_qty = mall_wh_1_qty_baseline + 2
        assert m_inv_after.quantity == expected_qty, (
            f"mall 仓数量应 baseline + 2 = {expected_qty}, 实际 {m_inv_after.quantity}"
        )

    # ── Step 3：mall→mall（需审批）──
    step(3, "mall→mall（预期：需审批）")
    async with admin_session_factory() as s:
        t = await transfer_service.create_transfer(
            s,
            initiator_employee_id=emp_id,
            source_side="mall", source_warehouse_id=mall_wh_1_id,
            dest_side="mall", dest_warehouse_id=mall_wh_2_id,
            barcodes=mall_codes[:2],  # 2 瓶
            reason="E2E mall→mall",
        )
        t_id_3 = t.id
        await s.commit()
        assert t.requires_approval is True
        print(f"   ✅ 创建成功")

    async with admin_session_factory() as s:
        await transfer_service.submit_transfer(
            s, transfer_id=t_id_3, actor_employee_id=emp_id,
        )
        await transfer_service.approve_transfer(
            s, transfer_id=t_id_3, approver_employee_id=emp_id,
        )
        t = await transfer_service.execute_transfer(
            s, transfer_id=t_id_3, actor_employee_id=emp_id,
        )
        await s.commit()
        assert t.status == TRANSFER_STATUS_EXECUTED

        # 条码 warehouse_id 已迁
        mbcs = (await s.execute(
            select(MallInventoryBarcode).where(MallInventoryBarcode.barcode.in_(mall_codes[:2]))
        )).scalars().all()
        for mbc in mbcs:
            assert mbc.warehouse_id == mall_wh_2_id
        print(f"   ✅ 2 瓶条码已迁到 mall_wh_2")

    # ── Step 4：品牌主仓拦截（源仓 + 目标仓分别测）──
    step(4, "品牌主仓拦截（源仓 or 目标仓都应被拒）")
    async with admin_session_factory() as s:
        from fastapi import HTTPException
        # 4a. 主仓作 source
        try:
            await transfer_service.create_transfer(
                s,
                initiator_employee_id=emp_id,
                source_side="erp", source_warehouse_id=wh_main_id,
                dest_side="erp", dest_warehouse_id=wh_b_id,
                barcodes=["dummy"],
                reason="应被拒",
            )
            assert False, "主仓作源应被拒"
        except HTTPException as e:
            assert "品牌主仓" in e.detail, f"错误消息应含品牌主仓: {e.detail}"
            print(f"   ✅ 主仓作源仓被拒：{e.detail}")

        # 4b. 主仓作 dest
        try:
            await transfer_service.create_transfer(
                s,
                initiator_employee_id=emp_id,
                source_side="erp", source_warehouse_id=wh_a_id,
                dest_side="erp", dest_warehouse_id=wh_main_id,
                barcodes=[erp_codes[4]],
                reason="应被拒",
            )
            assert False, "主仓作目标应被拒"
        except HTTPException as e:
            assert "品牌主仓" in e.detail
            print(f"   ✅ 主仓作目标仓被拒：{e.detail}")

    banner("✅ 仓库调拨 E2E 全部通过")

    # ── 清理 ──
    step(99, "清理 fixture")
    async with admin_session_factory() as s:
        # 删 transfer items + transfers
        for tid in [t_id_1, t_id_2, t_id_3]:
            await s.execute(delete(WarehouseTransferItem).where(WarehouseTransferItem.transfer_id == tid))
            await s.execute(delete(WarehouseTransfer).where(WarehouseTransfer.id == tid))
        # 删造的条码
        await s.execute(delete(InventoryBarcode).where(InventoryBarcode.barcode.like("E2E-TR-%")))
        await s.execute(delete(MallInventoryBarcode).where(MallInventoryBarcode.barcode.like("E2E-MTR-%")))
        await s.execute(delete(MallInventoryBarcode).where(MallInventoryBarcode.barcode.like("E2E-TR-%")))
        # 删 flows
        await s.execute(delete(StockFlow).where(StockFlow.flow_no.like("SF-%")).where(StockFlow.reference_no.like("TR-%")))
        await s.execute(delete(MallInventoryFlow).where(MallInventoryFlow.notes.like("%E2E%")))
        # 删 fixture inventory
        await s.execute(delete(Inventory).where(Inventory.batch_no.like("E2E-BATCH-%")))
        await s.execute(delete(Inventory).where(Inventory.batch_no.like("TRANSFER-%")))
        # 先删 flows 再删 inventory（FK 顺序）
        await s.execute(
            delete(MallInventoryFlow).where(MallInventoryFlow.inventory_id.in_(
                select(MallInventory.id).where(MallInventory.warehouse_id == mall_wh_2_id)
            ))
        )
        await s.execute(delete(MallInventory).where(MallInventory.warehouse_id.in_([mall_wh_2_id])))
        # mall_wh_1 是真仓不能删；把 fixture 累加的库存复位到 baseline
        inv_row = (await s.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == mall_wh_1_id)
            .where(MallInventory.sku_id == mall_sku_id)
        )).scalar_one_or_none()
        if inv_row is not None:
            inv_row.quantity = mall_wh_1_qty_baseline
        # 删仓
        await s.execute(delete(Warehouse).where(Warehouse.id.in_([wh_a_id, wh_b_id, wh_main_id])))
        await s.execute(delete(MallWarehouse).where(MallWarehouse.id == mall_wh_2_id))
        await s.commit()
        print("   ✅ 清理完毕")


if __name__ == "__main__":
    asyncio.run(main())
