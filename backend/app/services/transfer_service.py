"""仓库调拨 service

业务规则严格校验：
  1. 品牌主仓（warehouse_type='main' AND brand_id IS NOT NULL）**出入都禁**
     —— 品牌主仓只能走采购单（入）+ 销售订单+政策审批（出）
  2. 所有调拨必须扫码（每瓶条码过户），不允许按数量散装
  3. 审批策略：
       * 同品牌内部（两仓 brand_id 相同且都在 ERP 端）→ 免审，直接 executed
       * 跨品牌 / 涉任何 mall 仓 / ERP↔mall 跨端 → 必审
  4. 跨端 ERP↔mall：执行时条码在源端表 DELETE + 目标端表 INSERT
     成本从源端 cost_price 带过去；mall 侧用于加权平均更新

状态机：
  pending_scan ─submit→ pending_approval ─approve→ approved ─execute→ executed
       │                       │
       │                       └─reject→ rejected（终态）
       └─execute（免审时直接）→ executed
       └─cancel→ cancelled（条码回池子）
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import InventoryBarcodeStatus
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import (
    MallInventoryBarcodeStatus,
    MallInventoryBarcodeType,
    MallInventoryFlowType,
)
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryBarcode,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import MallProduct, MallProductSku
from app.models.product import Brand, Product, Warehouse
from app.models.transfer import (
    TRANSFER_STATUS_APPROVED,
    TRANSFER_STATUS_CANCELLED,
    TRANSFER_STATUS_EXECUTED,
    TRANSFER_STATUS_PENDING_APPROVAL,
    TRANSFER_STATUS_PENDING_SCAN,
    TRANSFER_STATUS_REJECTED,
    WAREHOUSE_SIDE_ERP,
    WAREHOUSE_SIDE_MALL,
    WarehouseTransfer,
    WarehouseTransferItem,
)


# =============================================================================
# 工具：仓库解析 + 业务规则判定
# =============================================================================


async def _load_erp_warehouse(db: AsyncSession, wh_id: str) -> Warehouse:
    wh = await db.get(Warehouse, wh_id)
    if wh is None:
        raise HTTPException(status_code=404, detail=f"ERP 仓不存在: {wh_id}")
    if not wh.is_active:
        raise HTTPException(status_code=400, detail=f"ERP 仓已停用: {wh.name}")
    return wh


async def _load_mall_warehouse(db: AsyncSession, wh_id: str) -> MallWarehouse:
    wh = await db.get(MallWarehouse, wh_id)
    if wh is None:
        raise HTTPException(status_code=404, detail=f"商城仓不存在: {wh_id}")
    if not wh.is_active:
        raise HTTPException(status_code=400, detail=f"商城仓已停用: {wh.name}")
    return wh


def _is_brand_main_warehouse(wh: Warehouse) -> bool:
    """ERP 仓是否是"品牌主仓"（只进销售出，不参与调拨）。

    定义：warehouse_type='main' AND brand_id IS NOT NULL
    """
    return wh.warehouse_type == "main" and wh.brand_id is not None


async def _check_brand_main_forbidden(
    db: AsyncSession,
    side: str,
    wh_id: str,
    direction: str,  # 'source' or 'dest'
) -> None:
    """品牌主仓不参与调拨——出入都禁。mall 仓无此约束。"""
    if side != WAREHOUSE_SIDE_ERP:
        return
    wh = await _load_erp_warehouse(db, wh_id)
    if _is_brand_main_warehouse(wh):
        raise HTTPException(
            status_code=400,
            detail=(
                f"仓库 [{wh.name}] 是品牌主仓，不允许作为调拨的{direction}"
                "（品牌主仓只能通过采购单入库 + 销售订单出库）"
            ),
        )


async def _determine_requires_approval(
    db: AsyncSession,
    source_side: str,
    source_id: str,
    dest_side: str,
    dest_id: str,
) -> bool:
    """判定是否需要审批。

    免审条件（同时满足）：
      - 两端都在 ERP
      - 两仓 brand_id 非空且相同（同品牌内部流转）
    否则必审：
      - 跨品牌（brand_id 不同或有一端为 None）
      - 涉任何 mall 仓 / 跨端
    """
    if source_side == WAREHOUSE_SIDE_ERP and dest_side == WAREHOUSE_SIDE_ERP:
        src = await _load_erp_warehouse(db, source_id)
        dst = await _load_erp_warehouse(db, dest_id)
        if src.brand_id and dst.brand_id and src.brand_id == dst.brand_id:
            return False  # 免审
    return True


# =============================================================================
# 创建 + 扫码
# =============================================================================


def _generate_transfer_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"TR-{ts}-{uuid.uuid4().hex[:6]}"


async def _assert_barcode_not_in_active_transfer(
    db: AsyncSession, barcode: str
) -> None:
    """确认条码没被其他活跃 transfer 锁住。"""
    active_statuses = (
        TRANSFER_STATUS_PENDING_SCAN,
        TRANSFER_STATUS_PENDING_APPROVAL,
        TRANSFER_STATUS_APPROVED,
    )
    existing = (await db.execute(
        select(WarehouseTransferItem.id)
        .join(
            WarehouseTransfer,
            WarehouseTransferItem.transfer_id == WarehouseTransfer.id,
        )
        .where(WarehouseTransferItem.barcode == barcode)
        .where(WarehouseTransfer.status.in_(active_statuses))
        .limit(1)
    )).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"条码 {barcode} 已在另一份未完成调拨单中",
        )


async def create_transfer(
    db: AsyncSession,
    *,
    initiator_employee_id: str,
    source_side: str,
    source_warehouse_id: str,
    dest_side: str,
    dest_warehouse_id: str,
    barcodes: list[str],
    reason: Optional[str] = None,
) -> WarehouseTransfer:
    """创建调拨单（扫码模式）。

    流程：
      1. 校验源/目标仓存在 + 不是品牌主仓
      2. 校验 barcodes 非空 + 全部在源仓 + 状态可调拨 + 未锁进其他 transfer
      3. 判定是否需要审批
      4. 写主单 + 每瓶一行 item（条码 + 成本快照）
      5. 返回主单；业务动作（条码过户、库存扣加、流水）延迟到 execute

    注意：本函数不改 barcode.status，在 execute 阶段才动。
    中途仅通过 "活跃 transfer items 对 barcode 的引用" 防止重复锁。
    """
    # 1. 校验 side
    if source_side not in (WAREHOUSE_SIDE_ERP, WAREHOUSE_SIDE_MALL):
        raise HTTPException(status_code=400, detail=f"非法 source_side: {source_side}")
    if dest_side not in (WAREHOUSE_SIDE_ERP, WAREHOUSE_SIDE_MALL):
        raise HTTPException(status_code=400, detail=f"非法 dest_side: {dest_side}")
    if source_side == dest_side and source_warehouse_id == dest_warehouse_id:
        raise HTTPException(status_code=400, detail="源仓和目标仓不能相同")

    # 品牌主仓禁
    await _check_brand_main_forbidden(db, source_side, source_warehouse_id, "源仓")
    await _check_brand_main_forbidden(db, dest_side, dest_warehouse_id, "目标仓")

    # 仓存在校验
    if source_side == WAREHOUSE_SIDE_ERP:
        await _load_erp_warehouse(db, source_warehouse_id)
    else:
        await _load_mall_warehouse(db, source_warehouse_id)
    if dest_side == WAREHOUSE_SIDE_ERP:
        await _load_erp_warehouse(db, dest_warehouse_id)
    else:
        await _load_mall_warehouse(db, dest_warehouse_id)

    # 2. 条码校验
    if not barcodes:
        raise HTTPException(status_code=400, detail="请至少扫描一个条码")
    # 内部去重
    if len(set(barcodes)) != len(barcodes):
        raise HTTPException(status_code=400, detail="扫码包含重复条码")

    # 每个条码：存在性 + 源仓匹配 + 状态 + 未被其他 transfer 锁
    item_meta: list[dict] = []
    if source_side == WAREHOUSE_SIDE_ERP:
        bcs = (await db.execute(
            select(InventoryBarcode)
            .where(InventoryBarcode.barcode.in_(barcodes))
            .with_for_update()
        )).scalars().all()
        bc_by_code = {b.barcode: b for b in bcs}
        missing = [c for c in barcodes if c not in bc_by_code]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"以下条码不存在于 ERP 库存：{missing[:5]}",
            )
        for c in barcodes:
            b = bc_by_code[c]
            if b.warehouse_id != source_warehouse_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"条码 {c} 不在源仓内（实际仓 {b.warehouse_id[:8]}）",
                )
            if b.status != InventoryBarcodeStatus.IN_STOCK.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"条码 {c} 状态 {b.status}，不可调拨",
                )
            await _assert_barcode_not_in_active_transfer(db, c)
            # 成本：从对应 inventory 行 cost_price 拿（按 batch）
            inv = (await db.execute(
                select(Inventory)
                .where(Inventory.warehouse_id == source_warehouse_id)
                .where(Inventory.product_id == b.product_id)
                .where(Inventory.batch_no == b.batch_no)
                .limit(1)
            )).scalar_one_or_none()
            cost = inv.cost_price if inv else None
            item_meta.append({
                "barcode": c,
                "product_ref": b.product_id,
                "sku_ref": None,
                "cost_price_snapshot": cost,
                "batch_no_snapshot": b.batch_no,
            })
    else:  # mall
        mbcs = (await db.execute(
            select(MallInventoryBarcode)
            .where(MallInventoryBarcode.barcode.in_(barcodes))
            .with_for_update()
        )).scalars().all()
        bc_by_code = {b.barcode: b for b in mbcs}
        missing = [c for c in barcodes if c not in bc_by_code]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"以下条码不存在于 mall 库存：{missing[:5]}",
            )
        for c in barcodes:
            b = bc_by_code[c]
            if b.warehouse_id != source_warehouse_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"条码 {c} 不在源仓内",
                )
            if b.status != MallInventoryBarcodeStatus.IN_STOCK.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"条码 {c} 状态 {b.status}，不可调拨",
                )
            await _assert_barcode_not_in_active_transfer(db, c)
            item_meta.append({
                "barcode": c,
                "product_ref": str(b.product_id),
                "sku_ref": str(b.sku_id),
                "cost_price_snapshot": b.cost_price,
                "batch_no_snapshot": b.batch_no,
            })

    # 3. 审批策略
    requires_approval = await _determine_requires_approval(
        db, source_side, source_warehouse_id, dest_side, dest_warehouse_id,
    )

    # 4. 写主单 + 明细
    total_bottles = len(barcodes)
    total_cost = sum(
        (m["cost_price_snapshot"] or Decimal("0")) for m in item_meta
    )
    transfer = WarehouseTransfer(
        id=str(uuid.uuid4()),
        transfer_no=_generate_transfer_no(),
        source_side=source_side,
        source_warehouse_id=source_warehouse_id,
        dest_side=dest_side,
        dest_warehouse_id=dest_warehouse_id,
        status=TRANSFER_STATUS_PENDING_SCAN,
        requires_approval=requires_approval,
        initiator_employee_id=initiator_employee_id,
        reason=reason,
        total_bottles=total_bottles,
        total_cost=total_cost,
    )
    db.add(transfer)
    await db.flush()

    for m in item_meta:
        db.add(WarehouseTransferItem(
            id=str(uuid.uuid4()),
            transfer_id=transfer.id,
            **m,
        ))
    await db.flush()
    return transfer


# =============================================================================
# Submit / Approve / Reject
# =============================================================================


async def submit_transfer(
    db: AsyncSession, *, transfer_id: str, actor_employee_id: str,
) -> WarehouseTransfer:
    """提交审批（pending_scan → pending_approval）。仅需审批的单子走这步。"""
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if t.status != TRANSFER_STATUS_PENDING_SCAN:
        raise HTTPException(status_code=409, detail=f"状态 {t.status} 不可提交")
    if not t.requires_approval:
        raise HTTPException(
            status_code=400,
            detail="该调拨单免审，请直接 execute",
        )
    t.status = TRANSFER_STATUS_PENDING_APPROVAL
    t.submitted_at = datetime.now(timezone.utc)
    await db.flush()
    return t


async def approve_transfer(
    db: AsyncSession, *, transfer_id: str, approver_employee_id: str,
) -> WarehouseTransfer:
    """审批通过（pending_approval → approved）。"""
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if t.status != TRANSFER_STATUS_PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"状态 {t.status} 不可审批")
    t.status = TRANSFER_STATUS_APPROVED
    t.approved_at = datetime.now(timezone.utc)
    t.approver_employee_id = approver_employee_id
    await db.flush()
    return t


async def reject_transfer(
    db: AsyncSession, *, transfer_id: str,
    approver_employee_id: str, reason: str,
) -> WarehouseTransfer:
    """审批驳回（pending_approval → rejected，终态）。"""
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if t.status != TRANSFER_STATUS_PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"状态 {t.status} 不可驳回")
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="驳回理由必填")
    t.status = TRANSFER_STATUS_REJECTED
    t.approver_employee_id = approver_employee_id
    t.rejection_reason = reason
    await db.flush()
    return t


async def cancel_transfer(
    db: AsyncSession, *, transfer_id: str, actor_employee_id: str,
) -> WarehouseTransfer:
    """发起人取消。仅 pending_scan / pending_approval 状态可取消。

    条码通过 _assert_barcode_not_in_active_transfer 的"软锁"自动释放
    （取消后 status=cancelled 不再被查到）。
    """
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if t.status not in (TRANSFER_STATUS_PENDING_SCAN, TRANSFER_STATUS_PENDING_APPROVAL):
        raise HTTPException(
            status_code=409,
            detail=f"状态 {t.status} 不可取消",
        )
    t.status = TRANSFER_STATUS_CANCELLED
    t.cancelled_at = datetime.now(timezone.utc)
    await db.flush()
    return t


# =============================================================================
# Execute（真正的条码过户 + 库存流水）
# =============================================================================


def _gen_flow_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"SF-{ts}-{uuid.uuid4().hex[:6]}"


async def execute_transfer(
    db: AsyncSession, *, transfer_id: str, actor_employee_id: str,
) -> WarehouseTransfer:
    """执行调拨：条码过户 + 库存扣加 + 流水。

    分支（四种组合）：
      (1) ERP → ERP    : InventoryBarcode.warehouse_id 改；Inventory 扣加 + StockFlow 两条
      (2) ERP → mall   : InventoryBarcode 删除 + MallInventoryBarcode 新建；
                         ERP Inventory 扣 + mall_inventory 加 + 加权平均 + MallInventoryFlow
      (3) mall → ERP   : MallInventoryBarcode 删除 + InventoryBarcode 新建（需要 MallProduct.source_product_id 映射）；
                         mall_inventory 扣 + ERP Inventory 加（按 batch，用快照 batch_no）
      (4) mall → mall  : MallInventoryBarcode.warehouse_id 改；MallInventory 扣加 + 加权平均

    执行成功 → status=executed + executed_at。
    """
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    # 状态允许：pending_scan（免审直接执行）或 approved（审批完毕后执行）
    if t.requires_approval and t.status != TRANSFER_STATUS_APPROVED:
        raise HTTPException(
            status_code=409,
            detail=f"调拨单需要审批，当前状态 {t.status} 不可执行",
        )
    if not t.requires_approval and t.status != TRANSFER_STATUS_PENDING_SCAN:
        raise HTTPException(
            status_code=409,
            detail=f"状态 {t.status} 不可执行",
        )

    items = (await db.execute(
        select(WarehouseTransferItem).where(
            WarehouseTransferItem.transfer_id == t.id
        )
    )).scalars().all()
    if not items:
        raise HTTPException(status_code=400, detail="调拨单无明细，无法执行")

    now = datetime.now(timezone.utc)

    if t.source_side == WAREHOUSE_SIDE_ERP and t.dest_side == WAREHOUSE_SIDE_ERP:
        await _execute_erp_to_erp(db, t, items, now)
    elif t.source_side == WAREHOUSE_SIDE_ERP and t.dest_side == WAREHOUSE_SIDE_MALL:
        await _execute_erp_to_mall(db, t, items, now)
    elif t.source_side == WAREHOUSE_SIDE_MALL and t.dest_side == WAREHOUSE_SIDE_ERP:
        await _execute_mall_to_erp(db, t, items, now)
    else:
        await _execute_mall_to_mall(db, t, items, now)

    t.status = TRANSFER_STATUS_EXECUTED
    t.executed_at = now
    await db.flush()
    return t


# =============================================================================
# 四种执行路径
# =============================================================================


async def _execute_erp_to_erp(
    db: AsyncSession,
    t: WarehouseTransfer,
    items: list[WarehouseTransferItem],
    now: datetime,
) -> None:
    """ERP → ERP：条码改 warehouse_id + Inventory 扣加 + StockFlow 双向"""
    # 按 (product_id, batch_no) 聚合数量和成本
    from collections import defaultdict
    agg: dict[tuple[str, str], list[int, Decimal]] = defaultdict(lambda: [0, Decimal("0")])

    for it in items:
        bc = (await db.execute(
            select(InventoryBarcode)
            .where(InventoryBarcode.barcode == it.barcode)
            .with_for_update()
        )).scalar_one_or_none()
        if bc is None or bc.warehouse_id != t.source_warehouse_id:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 已不在源仓，调拨失败",
            )
        if bc.status != InventoryBarcodeStatus.IN_STOCK.value:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 状态 {bc.status} 已变更",
            )
        # 过户
        bc.warehouse_id = t.dest_warehouse_id
        key = (bc.product_id, bc.batch_no)
        agg[key][0] += 1
        agg[key][1] = it.cost_price_snapshot or Decimal("0")

    # Inventory 扣（源仓）+ 加（目标仓），StockFlow 双向
    for (product_id, batch_no), (qty, cost) in agg.items():
        # 源仓 -
        src_inv = (await db.execute(
            select(Inventory)
            .where(Inventory.warehouse_id == t.source_warehouse_id)
            .where(Inventory.product_id == product_id)
            .where(Inventory.batch_no == batch_no)
            .with_for_update()
        )).scalar_one_or_none()
        if src_inv is None or src_inv.quantity < qty:
            raise HTTPException(
                status_code=409,
                detail=f"源仓库存不足（product={product_id[:8]}, batch={batch_no}）",
            )
        src_inv.quantity -= qty

        # 目标仓 +
        dst_inv = (await db.execute(
            select(Inventory)
            .where(Inventory.warehouse_id == t.dest_warehouse_id)
            .where(Inventory.product_id == product_id)
            .where(Inventory.batch_no == batch_no)
            .with_for_update()
        )).scalar_one_or_none()
        if dst_inv is None:
            dst_inv = Inventory(
                product_id=product_id,
                warehouse_id=t.dest_warehouse_id,
                batch_no=batch_no,
                quantity=qty,
                cost_price=cost,
                stock_in_date=now,
            )
            db.add(dst_inv)
        else:
            dst_inv.quantity += qty

        # StockFlow 双向（出+入）
        db.add(StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_flow_no(),
            flow_type="transfer_out",
            product_id=product_id,
            warehouse_id=t.source_warehouse_id,
            batch_no=batch_no,
            quantity=-qty, cost_price=cost,
            reference_no=t.transfer_no,
            notes=f"调拨出库 {t.transfer_no}",
        ))
        db.add(StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_flow_no(),
            flow_type="transfer_in",
            product_id=product_id,
            warehouse_id=t.dest_warehouse_id,
            batch_no=batch_no,
            quantity=qty, cost_price=cost,
            reference_no=t.transfer_no,
            notes=f"调拨入库 {t.transfer_no}",
        ))
    await db.flush()


async def _get_mall_sku_for_erp_product(
    db: AsyncSession, erp_product_id: str,
) -> MallProductSku:
    """ERP→mall 用：查 MallProduct.source_product_id=X 的第一个 SKU。
    如果没有映射，抛 400 指引管理员先建商城商品。"""
    mp = (await db.execute(
        select(MallProduct).where(MallProduct.source_product_id == erp_product_id)
    )).scalar_one_or_none()
    if mp is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ERP 商品 {erp_product_id} 未映射到 mall_products，"
                "请先在商城商品管理创建对应商品（source_product_id 指向本商品）"
            ),
        )
    sku = (await db.execute(
        select(MallProductSku)
        .where(MallProductSku.product_id == mp.id)
        .order_by(MallProductSku.id)
        .limit(1)
    )).scalar_one_or_none()
    if sku is None:
        raise HTTPException(
            status_code=400,
            detail=f"商城商品 {mp.name} 无 SKU，无法接收跨端调拨",
        )
    return sku


async def _execute_erp_to_mall(
    db: AsyncSession,
    t: WarehouseTransfer,
    items: list[WarehouseTransferItem],
    now: datetime,
) -> None:
    """ERP → mall：源端 InventoryBarcode 删 + 目标端 MallInventoryBarcode 建
    + ERP Inventory 扣 + mall_inventory 加（加权平均）+ 双向流水"""
    from collections import defaultdict
    # 先拿源条码，决定对应的 mall SKU
    src_bcs: dict[str, InventoryBarcode] = {}
    for it in items:
        bc = (await db.execute(
            select(InventoryBarcode)
            .where(InventoryBarcode.barcode == it.barcode)
            .with_for_update()
        )).scalar_one_or_none()
        if bc is None or bc.warehouse_id != t.source_warehouse_id:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 已不在 ERP 源仓",
            )
        if bc.status != InventoryBarcodeStatus.IN_STOCK.value:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 状态 {bc.status} 已变更",
            )
        src_bcs[it.barcode] = bc

    # 按 ERP product_id 聚合（每个都要查 mall SKU 映射）
    per_product_qty: dict[str, int] = defaultdict(int)
    per_product_cost: dict[str, Decimal] = {}
    per_product_batch: dict[str, str] = {}
    for it in items:
        bc = src_bcs[it.barcode]
        per_product_qty[bc.product_id] += 1
        per_product_cost[bc.product_id] = it.cost_price_snapshot or Decimal("0")
        per_product_batch[bc.product_id] = bc.batch_no

    for erp_pid, qty in per_product_qty.items():
        cost = per_product_cost[erp_pid]
        batch = per_product_batch[erp_pid]
        sku = await _get_mall_sku_for_erp_product(db, erp_pid)

        # 源：ERP Inventory 扣 + StockFlow(transfer_out)
        src_inv = (await db.execute(
            select(Inventory)
            .where(Inventory.warehouse_id == t.source_warehouse_id)
            .where(Inventory.product_id == erp_pid)
            .where(Inventory.batch_no == batch)
            .with_for_update()
        )).scalar_one_or_none()
        if src_inv is None or src_inv.quantity < qty:
            raise HTTPException(
                status_code=409,
                detail=f"ERP 源仓库存不足（product={erp_pid[:8]}）",
            )
        src_inv.quantity -= qty
        db.add(StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_flow_no(),
            flow_type="transfer_out",
            product_id=erp_pid,
            warehouse_id=t.source_warehouse_id,
            batch_no=batch,
            quantity=-qty, cost_price=cost,
            reference_no=t.transfer_no,
            notes=f"调拨出到 mall 仓 {t.transfer_no}",
        ))

        # 目标：mall_inventory + 加权平均
        m_inv = (await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == t.dest_warehouse_id)
            .where(MallInventory.sku_id == sku.id)
            .with_for_update()
        )).scalar_one_or_none()
        if m_inv is None:
            m_inv = MallInventory(
                id=str(uuid.uuid4()),
                warehouse_id=t.dest_warehouse_id,
                sku_id=sku.id,
                quantity=qty,
                avg_cost_price=cost,
            )
            db.add(m_inv)
            await db.flush()
        else:
            old_q = m_inv.quantity or 0
            old_avg = m_inv.avg_cost_price or Decimal("0")
            new_q = old_q + qty
            m_inv.avg_cost_price = (
                (Decimal(old_q) * old_avg + Decimal(qty) * cost) / Decimal(new_q)
            ).quantize(Decimal("0.0001"))
            m_inv.quantity = new_q

        db.add(MallInventoryFlow(
            id=str(uuid.uuid4()),
            inventory_id=m_inv.id,
            flow_type=MallInventoryFlowType.IN.value,
            quantity=qty,
            cost_price=cost,
            ref_type="transfer",
            ref_id=t.id,
            notes=f"ERP→mall 调拨入库 {t.transfer_no}",
        ))

    # 最后：源端条码 DELETE + 目标端条码 INSERT
    for it in items:
        bc = src_bcs[it.barcode]
        # 记录源端 product/batch（供目标端用）
        erp_pid = bc.product_id
        erp_batch = bc.batch_no
        erp_cost = it.cost_price_snapshot
        sku = await _get_mall_sku_for_erp_product(db, erp_pid)

        # 源端删（真删，目标端用同条码）
        await db.delete(bc)

        # 目标端建
        db.add(MallInventoryBarcode(
            id=str(uuid.uuid4()),
            barcode=it.barcode,
            barcode_type=MallInventoryBarcodeType.BOTTLE.value,
            sku_id=sku.id,
            product_id=sku.product_id,
            warehouse_id=t.dest_warehouse_id,
            batch_no=erp_batch or f"TRANSFER-{t.transfer_no}",
            status=MallInventoryBarcodeStatus.IN_STOCK.value,
            cost_price=erp_cost,
        ))
    await db.flush()


async def _execute_mall_to_erp(
    db: AsyncSession,
    t: WarehouseTransfer,
    items: list[WarehouseTransferItem],
    now: datetime,
) -> None:
    """mall → ERP：反向。需要 MallProduct.source_product_id 非空（必须挂靠到 ERP product）。"""
    from collections import defaultdict

    src_bcs: dict[str, MallInventoryBarcode] = {}
    for it in items:
        bc = (await db.execute(
            select(MallInventoryBarcode)
            .where(MallInventoryBarcode.barcode == it.barcode)
            .with_for_update()
        )).scalar_one_or_none()
        if bc is None or bc.warehouse_id != t.source_warehouse_id:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 已不在 mall 源仓",
            )
        if bc.status != MallInventoryBarcodeStatus.IN_STOCK.value:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 状态 {bc.status} 已变更",
            )
        src_bcs[it.barcode] = bc

    # mall product → 查 source_product_id 到 ERP 产品
    per_erp_pid_qty: dict[str, int] = defaultdict(int)
    per_erp_pid_cost: dict[str, Decimal] = {}
    erp_pid_by_mall_pid: dict[int, str] = {}

    for it in items:
        bc = src_bcs[it.barcode]
        mp = await db.get(MallProduct, bc.product_id)
        if mp is None:
            raise HTTPException(
                status_code=500,
                detail=f"mall_product {bc.product_id} 不存在",
            )
        if mp.source_product_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"商城商品 {mp.name} 未挂靠 ERP 商品（source_product_id 为空），"
                    "不能回调拨到 ERP 仓"
                ),
            )
        erp_pid_by_mall_pid[bc.product_id] = mp.source_product_id
        per_erp_pid_qty[mp.source_product_id] += 1
        per_erp_pid_cost[mp.source_product_id] = it.cost_price_snapshot or Decimal("0")

    # mall 仓 source 减 + ERP 仓 dest 加（按虚拟 batch: TRANSFER-{transfer_no}）
    virtual_batch = f"TRANSFER-{t.transfer_no}"
    for erp_pid, qty in per_erp_pid_qty.items():
        cost = per_erp_pid_cost[erp_pid]

        # mall_inventory 扣（按 SKU）
        # 找到该 ERP product 对应的 mall SKU
        mp = (await db.execute(
            select(MallProduct).where(MallProduct.source_product_id == erp_pid)
        )).scalar_one()
        sku = (await db.execute(
            select(MallProductSku)
            .where(MallProductSku.product_id == mp.id)
            .order_by(MallProductSku.id)
            .limit(1)
        )).scalar_one()
        m_inv = (await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == t.source_warehouse_id)
            .where(MallInventory.sku_id == sku.id)
            .with_for_update()
        )).scalar_one_or_none()
        if m_inv is None or (m_inv.quantity or 0) < qty:
            raise HTTPException(
                status_code=409,
                detail=f"mall 源仓库存不足（sku={sku.id}）",
            )
        m_inv.quantity -= qty

        db.add(MallInventoryFlow(
            id=str(uuid.uuid4()),
            inventory_id=m_inv.id,
            flow_type=MallInventoryFlowType.OUT.value,
            quantity=qty,
            cost_price=cost,
            ref_type="transfer",
            ref_id=t.id,
            notes=f"mall→ERP 调拨出库 {t.transfer_no}",
        ))

        # ERP Inventory 加（虚拟 batch）
        dst_inv = Inventory(
            product_id=erp_pid,
            warehouse_id=t.dest_warehouse_id,
            batch_no=virtual_batch,
            quantity=qty,
            cost_price=cost,
            stock_in_date=now,
        )
        db.add(dst_inv)

        db.add(StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_flow_no(),
            flow_type="transfer_in",
            product_id=erp_pid,
            warehouse_id=t.dest_warehouse_id,
            batch_no=virtual_batch,
            quantity=qty, cost_price=cost,
            reference_no=t.transfer_no,
            notes=f"mall→ERP 调拨入库 {t.transfer_no}",
        ))

    # 条码：mall 端 DELETE + ERP 端 INSERT
    for it in items:
        bc = src_bcs[it.barcode]
        erp_pid = erp_pid_by_mall_pid[bc.product_id]
        erp_cost = it.cost_price_snapshot
        await db.delete(bc)

        db.add(InventoryBarcode(
            id=str(uuid.uuid4()),
            barcode=it.barcode,
            barcode_type="bottle",
            product_id=erp_pid,
            warehouse_id=t.dest_warehouse_id,
            batch_no=virtual_batch,
            status=InventoryBarcodeStatus.IN_STOCK.value,
        ))
    await db.flush()


async def _execute_mall_to_mall(
    db: AsyncSession,
    t: WarehouseTransfer,
    items: list[WarehouseTransferItem],
    now: datetime,
) -> None:
    """mall → mall：条码改 warehouse_id + mall_inventory 扣加 + 加权平均"""
    from collections import defaultdict

    per_sku_qty: dict[int, int] = defaultdict(int)
    per_sku_cost: dict[int, Decimal] = {}

    for it in items:
        bc = (await db.execute(
            select(MallInventoryBarcode)
            .where(MallInventoryBarcode.barcode == it.barcode)
            .with_for_update()
        )).scalar_one_or_none()
        if bc is None or bc.warehouse_id != t.source_warehouse_id:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 已不在 mall 源仓",
            )
        if bc.status != MallInventoryBarcodeStatus.IN_STOCK.value:
            raise HTTPException(
                status_code=409,
                detail=f"条码 {it.barcode} 状态 {bc.status} 已变更",
            )
        bc.warehouse_id = t.dest_warehouse_id
        per_sku_qty[bc.sku_id] += 1
        per_sku_cost[bc.sku_id] = it.cost_price_snapshot or Decimal("0")

    for sku_id, qty in per_sku_qty.items():
        cost = per_sku_cost[sku_id]
        # 源仓 -
        src_inv = (await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == t.source_warehouse_id)
            .where(MallInventory.sku_id == sku_id)
            .with_for_update()
        )).scalar_one_or_none()
        if src_inv is None or (src_inv.quantity or 0) < qty:
            raise HTTPException(
                status_code=409,
                detail=f"mall 源仓库存不足（sku={sku_id}）",
            )
        src_inv.quantity -= qty

        db.add(MallInventoryFlow(
            id=str(uuid.uuid4()),
            inventory_id=src_inv.id,
            flow_type=MallInventoryFlowType.OUT.value,
            quantity=qty, cost_price=cost,
            ref_type="transfer", ref_id=t.id,
            notes=f"mall→mall 调拨出库 {t.transfer_no}",
        ))

        # 目标仓 + 加权平均
        dst_inv = (await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == t.dest_warehouse_id)
            .where(MallInventory.sku_id == sku_id)
            .with_for_update()
        )).scalar_one_or_none()
        if dst_inv is None:
            dst_inv = MallInventory(
                id=str(uuid.uuid4()),
                warehouse_id=t.dest_warehouse_id,
                sku_id=sku_id,
                quantity=qty,
                avg_cost_price=cost,
            )
            db.add(dst_inv)
            await db.flush()
        else:
            old_q = dst_inv.quantity or 0
            old_avg = dst_inv.avg_cost_price or Decimal("0")
            new_q = old_q + qty
            dst_inv.avg_cost_price = (
                (Decimal(old_q) * old_avg + Decimal(qty) * cost) / Decimal(new_q)
            ).quantize(Decimal("0.0001"))
            dst_inv.quantity = new_q

        db.add(MallInventoryFlow(
            id=str(uuid.uuid4()),
            inventory_id=dst_inv.id,
            flow_type=MallInventoryFlowType.IN.value,
            quantity=qty, cost_price=cost,
            ref_type="transfer", ref_id=t.id,
            notes=f"mall→mall 调拨入库 {t.transfer_no}",
        ))
    await db.flush()
