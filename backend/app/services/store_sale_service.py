"""门店零售收银 service。

业务流程（扫码即成交）：
  1. 校验店员（employee + mall_user.assigned_store_id 指向门店仓）
  2. 校验客户（mall_users.user_type=consumer + 存在）
  3. 逐瓶扫码：条码必须在店仓内 + status=in_stock + 属于订单商品清单
  4. 逐瓶输入售价：必须在 products.min_sale_price..max_sale_price 之间
  5. 付款方式：cash / wechat / alipay / card（禁 credit）
  6. 提交 → 事务内：
     - InventoryBarcode 状态 in_stock → outbound
     - Inventory 扣数量（按 barcode.batch_no）
     - StockFlow 记"retail_sale"出库流水
     - 建 StoreSale + StoreSaleItem × N 行
     - 查 retail_commission_rates 算提成，按单单生成 1 条 Commission（按店员×商品聚合瓶数的合计 commission_amount）
     - 顺手更新 products.total_sales（可选，ERP 没这字段时跳过）
     - 审计

利润口径（商城零售专属）：
  利润_瓶 = sale_price - Inventory.cost_price（按 batch 精确）
  提成_瓶 = 利润_瓶 × retail_commission_rates[employee, product].rate_on_profit
  commission 合计 = Σ(提成_瓶)  → 写入 Commission(employee_id, store_sale_id, commission_amount, status=pending)

整笔进月结工资单：commissions.store_sale_id 非空且 status='pending' → 纳入
"""
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import InventoryBarcodeStatus, WarehouseType
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.mall.base import MallUserStatus, MallUserType
from app.models.mall.user import MallUser
from app.models.product import Product, Warehouse
from app.models.store_sale import (
    RetailCommissionRate,
    StoreSale,
    StoreSaleItem,
)
from app.models.user import Commission, Employee
from app.services.audit_service import log_audit


ALLOWED_PAYMENT_METHODS = {"cash", "wechat", "alipay", "card"}


def _gen_sale_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"SS-{ts}-{uuid.uuid4().hex[:6]}"


def _gen_flow_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"SF-RS-{ts}-{uuid.uuid4().hex[:5]}"


async def _load_store_warehouse(db: AsyncSession, store_id: str) -> Warehouse:
    wh = await db.get(Warehouse, store_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="门店仓不存在")
    if wh.warehouse_type != WarehouseType.STORE.value:
        raise HTTPException(
            status_code=400,
            detail=f"仓 {wh.name} 不是门店仓（warehouse_type={wh.warehouse_type}）",
        )
    if not wh.is_active:
        raise HTTPException(status_code=400, detail=f"门店 {wh.name} 已停用")
    return wh


async def create_store_sale(
    db: AsyncSession,
    *,
    cashier_employee_id: str,
    store_id: str,
    customer_id: Optional[str] = None,
    customer_walk_in_name: Optional[str] = None,
    customer_walk_in_phone: Optional[str] = None,
    line_items: list[dict],  # [{barcode, sale_price}]
    payment_method: str,
    notes: Optional[str] = None,
) -> StoreSale:
    """店员提交收银单。

    参数 line_items 每个元素 {barcode: str, sale_price: Decimal}。
    售价由店员输入，必须在 product.min_sale_price..max_sale_price 之间。

    客户标识（决策 #3 散客支持）：
      - customer_id 非空：走 mall_user 会员，校验 user_type=consumer + active
      - customer_id 为空：散客，可选填 customer_walk_in_name/phone（仅用于
        回头率分析，不建 mall_user 账号）
      二者至少填其一的提示由前端给，服务端允许两者都空（纯匿名）

    成功返回 StoreSale（含 total_* 字段）；失败抛 HTTPException。
    所有校验失败整笔回滚（事务外层由调用方的 get_db 管理）。
    """
    # 1. 付款方式
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"付款方式非法：{payment_method}（允许：{', '.join(sorted(ALLOWED_PAYMENT_METHODS))}）",
        )

    # 2. 门店校验
    store_wh = await _load_store_warehouse(db, store_id)

    # 3. 店员校验（必须属于这个店）
    cashier = await db.get(Employee, cashier_employee_id)
    if cashier is None or cashier.status != "active":
        raise HTTPException(status_code=400, detail="店员不存在或已离职")
    if cashier.assigned_store_id != store_id:
        raise HTTPException(
            status_code=403,
            detail=f"店员 {cashier.name} 不属于门店 {store_wh.name}",
        )

    # 4. 客户校验（会员 vs 散客）
    if customer_id:
        customer = await db.get(MallUser, customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户不存在")
        if customer.user_type != MallUserType.CONSUMER.value:
            raise HTTPException(status_code=400, detail="客户必须是 consumer 类型")
        if customer.status != MallUserStatus.ACTIVE.value:
            raise HTTPException(status_code=400, detail=f"客户已停用（{customer.status}）")
    # 散客（customer_id=None）不校验；customer_walk_in_* 纯文本记录即可

    # 5. line_items 校验
    if not line_items:
        raise HTTPException(status_code=400, detail="请至少扫描一瓶")
    barcodes = [it["barcode"] for it in line_items]
    if len(set(barcodes)) != len(barcodes):
        raise HTTPException(status_code=400, detail="扫码包含重复条码")

    # 6. 查条码（批量 FOR UPDATE 锁）
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
            detail=f"以下条码不存在：{missing[:5]}",
        )

    # 7. 校验每瓶（仓位 + 状态）+ 批量拉 product 做售价区间校验
    product_ids = list({b.product_id for b in bcs})
    products = (await db.execute(
        select(Product).where(Product.id.in_(product_ids))
    )).scalars().all()
    product_by_id = {p.id: p for p in products}

    # 预先算好 line sale_price 字典（按 barcode 映射）
    sale_price_by_barcode: dict[str, Decimal] = {}
    for it in line_items:
        sp = it.get("sale_price")
        if sp is None:
            raise HTTPException(
                status_code=400, detail=f"条码 {it['barcode']} 缺 sale_price",
            )
        sale_price_by_barcode[it["barcode"]] = Decimal(str(sp))

    for code in barcodes:
        b = bc_by_code[code]
        if b.warehouse_id != store_id:
            raise HTTPException(
                status_code=400,
                detail=f"条码 {code} 不在本门店仓内（实际仓 {b.warehouse_id[:8]}）",
            )
        if b.status != InventoryBarcodeStatus.IN_STOCK.value:
            raise HTTPException(
                status_code=400,
                detail=f"条码 {code} 状态 {b.status}，不可销售",
            )

        # 售价区间
        prod = product_by_id.get(b.product_id)
        if prod is None:
            raise HTTPException(
                status_code=500,
                detail=f"商品 {b.product_id} 不存在，条码异常",
            )
        sp = sale_price_by_barcode[code]
        if prod.min_sale_price is None or prod.max_sale_price is None:
            raise HTTPException(
                status_code=400,
                detail=f"商品 {prod.name} 未配置售价区间，请联系管理员",
            )
        if sp < prod.min_sale_price or sp > prod.max_sale_price:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"商品 {prod.name} 售价 ¥{sp} 超出区间 "
                    f"¥{prod.min_sale_price}–¥{prod.max_sale_price}"
                ),
            )

    # 8. 按 (product_id, batch_no) 聚合 + 扣 Inventory
    inv_dedup: dict[tuple[str, str], Inventory] = {}
    agg_qty: dict[tuple[str, str], int] = defaultdict(int)
    for code in barcodes:
        b = bc_by_code[code]
        agg_qty[(b.product_id, b.batch_no)] += 1
    for (pid, batch), qty in agg_qty.items():
        inv = (await db.execute(
            select(Inventory)
            .where(Inventory.warehouse_id == store_id)
            .where(Inventory.product_id == pid)
            .where(Inventory.batch_no == batch)
            .with_for_update()
        )).scalar_one_or_none()
        if inv is None or inv.quantity < qty:
            raise HTTPException(
                status_code=409,
                detail=f"门店库存不足（product={pid[:8]}, batch={batch}）",
            )
        inv.quantity -= qty
        inv_dedup[(pid, batch)] = inv

    # 9. 创建 StoreSale + 明细
    sale_id = str(uuid.uuid4())
    sale_no = _gen_sale_no()
    now = datetime.now(timezone.utc)

    # 查提成率（按员工×每个商品）
    rates = (await db.execute(
        select(RetailCommissionRate)
        .where(RetailCommissionRate.employee_id == cashier_employee_id)
        .where(RetailCommissionRate.product_id.in_(product_ids))
    )).scalars().all()
    rate_by_pid = {r.product_id: r.rate_on_profit for r in rates}

    total_sale = Decimal("0")
    total_cost = Decimal("0")
    total_profit = Decimal("0")
    total_commission = Decimal("0")

    items: list[StoreSaleItem] = []
    for code in barcodes:
        b = bc_by_code[code]
        prod = product_by_id[b.product_id]
        inv = inv_dedup[(b.product_id, b.batch_no)]
        cost = inv.cost_price or Decimal("0")
        sp = sale_price_by_barcode[code]
        profit = sp - cost
        rate = rate_by_pid.get(b.product_id)
        if rate is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"店员 {cashier.name} 未配置商品 {prod.name} 的利润提成率，"
                    "请联系管理员配 retail_commission_rates"
                ),
            )
        commission_per = (profit * rate).quantize(Decimal("0.01"))

        # 条码出库
        b.status = InventoryBarcodeStatus.OUTBOUND.value
        # 不改 outbound_stock_flow_id 因为 ERP StockFlow 走批次聚合，后面一条条码对不上特定 flow
        # ERP StockFlow 的 order_out 有 reference_no 能反查，不需要条码级 FK

        items.append(StoreSaleItem(
            id=str(uuid.uuid4()),
            sale_id=sale_id,
            barcode=code,
            product_id=b.product_id,
            batch_no_snapshot=b.batch_no,
            sale_price=sp,
            cost_price_snapshot=cost,
            profit=profit,
            rate_on_profit_snapshot=rate,
            commission_amount=commission_per,
        ))

        total_sale += sp
        total_cost += cost
        total_profit += profit
        total_commission += commission_per

    # 10. StockFlow：按 (product_id, batch) 聚合一条
    for (pid, batch), qty in agg_qty.items():
        inv = inv_dedup[(pid, batch)]
        db.add(StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_gen_flow_no(),
            flow_type="retail_sale",
            product_id=pid,
            warehouse_id=store_id,
            batch_no=batch,
            quantity=-qty,
            cost_price=inv.cost_price,
            reference_no=sale_no,
            notes=f"门店零售出库 {sale_no}（{store_wh.name}）",
        ))

    # 11. 写 StoreSale 主单
    sale = StoreSale(
        id=sale_id,
        sale_no=sale_no,
        store_id=store_id,
        cashier_employee_id=cashier_employee_id,
        customer_id=customer_id,
        customer_walk_in_name=customer_walk_in_name,
        customer_walk_in_phone=customer_walk_in_phone,
        total_sale_amount=total_sale,
        total_cost=total_cost,
        total_profit=total_profit,
        total_commission=total_commission,
        total_bottles=len(barcodes),
        payment_method=payment_method,
        notes=notes,
        status="completed",
    )
    db.add(sale)
    await db.flush()

    for it in items:
        db.add(it)

    # 12. Commission（一笔销售一条 commission，按店员聚合）
    com = Commission(
        id=str(uuid.uuid4()),
        employee_id=cashier_employee_id,
        brand_id=(products[0].brand_id if products else None),
        store_sale_id=sale.id,
        commission_amount=total_commission,
        status="pending",
        notes=f"门店零售 {sale_no}（{store_wh.name}）{len(barcodes)} 瓶",
    )
    db.add(com)
    await db.flush()

    # 把 commission_id 回填到每个 item（方便工资单追溯）
    for it in items:
        it.commission_id = com.id

    await db.flush()

    # 审计：门店零售收银金额/状态/权限三要素都涉及，必须留痕
    await log_audit(
        db,
        action="store_sale.create",
        entity_type="StoreSale",
        entity_id=sale.id,
        actor_id=cashier_employee_id,
        changes={
            "sale_no": sale.sale_no,
            "store_id": store_id,
            "store_name": store_wh.name,
            "customer_id": customer_id,
            "walk_in": not customer_id,
            "walk_in_name": customer_walk_in_name,
            "walk_in_phone": customer_walk_in_phone,
            "bottles": sale.total_bottles,
            "total_sale_amount": str(sale.total_sale_amount),
            "total_profit": str(sale.total_profit),
            "total_commission": str(sale.total_commission),
            "payment_method": payment_method,
        },
    )
    return sale
