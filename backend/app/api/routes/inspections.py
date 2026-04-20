"""
Inspection & Market Cleanup API routes — CRUD for inspection_cases
and market_cleanup_cases.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.inspection import InspectionCase, MarketCleanupCase
from app.models.inventory import Inventory, StockFlow
from app.schemas.inspection import (
    InspectionCaseCreate,
    InspectionCaseResponse,
    InspectionCaseUpdate,
    MarketCleanupCaseCreate,
    MarketCleanupCaseResponse,
    MarketCleanupCaseUpdate,
)
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}"


def _compute_profit_loss(case: InspectionCase, bottles: int) -> Decimal:
    """根据 case_type 计算预估盈亏（瓶数基准）。正=盈利、负=亏损。
    A1 恶意外流: -(回收价 - 到手价) × 瓶数 - 罚款
       含义：我们卖给客户的到手价 650，被窜货后花 800 回收，每瓶多花 150
    A2 非恶意: +(指导价 - 回收价) × 瓶数 - 罚款
       含义：回收后以指导价入主仓，差价是盈利
    A3 被转码: -罚款
    B1 回售: +(回售价 - 买入价) × 瓶数 + 奖励
    B2 转码入库: +(指导价 - 买入价) × 瓶数 + 奖励
    """
    sale_price = case.original_sale_price or Decimal("0")  # 指导价
    deal_price = case.deal_unit_price if case.deal_unit_price and case.deal_unit_price > 0 else sale_price  # 到手价
    purchase_price = case.purchase_price or Decimal("0")
    resell_price = case.resell_price or Decimal("0")
    penalty = case.penalty_amount or Decimal("0")
    reward = case.reward_amount or Decimal("0")
    b = Decimal(bottles)
    t = case.case_type
    if t == 'outflow_malicious':
        return -(purchase_price - deal_price) * b - penalty
    if t == 'outflow_nonmalicious':
        return (sale_price - purchase_price) * b - penalty
    if t == 'outflow_transfer':
        return -penalty
    if t == 'inflow_resell':
        return (resell_price - purchase_price) * b + reward
    if t == 'inflow_transfer':
        return (sale_price - purchase_price) * b + reward
    return Decimal("0")


async def _bottles_of(case: InspectionCase, db: AsyncSession) -> int:
    """案件实际瓶数（考虑 quantity_unit）"""
    if case.quantity_unit == '箱' and case.product_id:
        from app.models.product import Product
        prod = await db.get(Product, case.product_id)
        bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        return case.quantity * bpc
    return case.quantity


# ═══════════════════════════════════════════════════════════════════
# InspectionCase CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/inspection-cases", response_model=InspectionCaseResponse, status_code=201)
async def create_inspection_case(
    body: InspectionCaseCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = InspectionCase(
        id=str(uuid.uuid4()), case_no=_gen_no("IC"), **body.model_dump()
    )
    db.add(obj)
    await db.flush()

    # 后端权威计算 profit_loss（覆盖前端传值，保证利润台账准确）
    bottles = await _bottles_of(obj, db)
    obj.profit_loss = _compute_profit_loss(obj, bottles)

    # 回款账户联动
    if obj.brand_id and obj.case_type in ('outflow_transfer', 'inflow_transfer'):
        from app.models.product import Account, Product
        from app.api.routes.accounts import record_fund_flow
        ptm_acc = (await db.execute(
            select(Account).where(Account.brand_id == obj.brand_id, Account.account_type == 'payment_to_mfr')
        )).scalar_one_or_none()
        # 单位换算：输入单位=箱时需要乘以 bottles_per_case
        bpc = 1
        if obj.quantity_unit == '箱' and obj.product_id:
            prod = await db.get(Product, obj.product_id)
            bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        bottles = obj.quantity * bpc
        if ptm_acc:
            if obj.case_type == 'outflow_transfer' and obj.transfer_amount > 0:
                # A3被转码：扣减回款
                ptm_acc.balance -= obj.transfer_amount
                await record_fund_flow(db, account_id=ptm_acc.id, flow_type='debit',
                    amount=obj.transfer_amount, balance_after=ptm_acc.balance,
                    related_type='transfer_deduction', related_id=obj.id,
                    notes=f"被转码扣减回款 {obj.case_no}")
            elif obj.case_type == 'inflow_transfer' and obj.purchase_price > 0 and bottles > 0:
                # B2转码入库：增加回款（买入价×瓶数）
                amt = obj.purchase_price * bottles
                ptm_acc.balance += amt
                await record_fund_flow(db, account_id=ptm_acc.id, flow_type='credit',
                    amount=amt, balance_after=ptm_acc.balance,
                    related_type='transfer_credit', related_id=obj.id,
                    notes=f"转码入库增加回款 {obj.case_no} ({bottles}瓶)")
        await db.flush()

    await log_audit(db, action="create_inspection_case", entity_type="InspectionCase", entity_id=obj.id, user=user)
    await db.refresh(obj, ["product"])
    return obj


@router.get("/inspection-cases", response_model=list[InspectionCaseResponse])
async def list_inspection_cases(
    user: CurrentUser,
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(InspectionCase)
    if status:
        stmt = stmt.where(InspectionCase.status == status)
    stmt = stmt.order_by(InspectionCase.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/inspection-cases/{case_id}", response_model=InspectionCaseResponse)
async def get_inspection_case(
    case_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(InspectionCase, case_id)
    if obj is None:
        raise HTTPException(404, "InspectionCase not found")
    return obj


@router.put("/inspection-cases/{case_id}", response_model=InspectionCaseResponse)
async def update_inspection_case(
    case_id: str, body: InspectionCaseUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(InspectionCase, case_id)
    if obj is None:
        raise HTTPException(404, "InspectionCase not found")
    payload = body.model_dump(exclude_unset=True)
    # profit_loss 由后端重算，不接受前端值
    payload.pop('profit_loss', None)
    for k, v in payload.items():
        setattr(obj, k, v)
    # 如果改了数量/价格/罚款等字段，重算 profit_loss
    bottles = await _bottles_of(obj, db)
    obj.profit_loss = _compute_profit_loss(obj, bottles)
    await db.flush()
    await db.refresh(obj, ["product"])
    return obj


class ExecuteInspectionRequest(BaseModel):
    """执行稽查案件：原子化完成付款+入库/出库"""
    barcode: Optional[str] = None  # B1 回售时从备用库出库用
    barcodes: Optional[list[str]] = None  # A1/A2/B2 入库时绑定的条码
    voucher_urls: Optional[list[str]] = None


@router.post("/inspection-cases/{case_id}/execute", status_code=200)
async def execute_inspection_case(
    case_id: str, body: ExecuteInspectionRequest, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """
    根据 case_type 原子化执行：
      A1 outflow_malicious: 扣master(回收款+罚款) + 入备用库
      A2 outflow_nonmalicious: 扣master(回收款+罚款) + 入主仓(成本=售价)
      A3 outflow_transfer: 扣master(罚款)   ※转码金额已在create时扣回款
      B1 inflow_resell: 从备用库出库 + 加master(回售收入)
      B2 inflow_transfer: 入主仓(成本=售价)  ※回款已在create时加
    """
    from app.models.product import Account, Product, Warehouse
    from app.api.routes.accounts import record_fund_flow

    case = await db.get(InspectionCase, case_id)
    if case is None:
        raise HTTPException(404, "案件不存在")
    if case.status != 'approved':
        raise HTTPException(400, f"案件状态为 {case.status}，只有已审批案件才能执行")
    if not case.brand_id or not case.product_id:
        raise HTTPException(400, "案件缺少品牌或商品信息")

    # 瓶数换算
    prod = await db.get(Product, case.product_id)
    bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
    bottles = case.quantity * bpc if case.quantity_unit == '箱' else case.quantity
    if bottles <= 0:
        raise HTTPException(400, "案件数量为0")

    # 扫码校验
    needs_scan = case.case_type in ('outflow_malicious', 'outflow_nonmalicious', 'inflow_transfer', 'inflow_resell')
    if needs_scan and not (body.barcode or (body.barcodes and len(body.barcodes) > 0)):
        raise HTTPException(400, "该案件类型必须扫码")

    # 稽查付款/收款走品牌现金账户（不走总资金池）
    brand_cash_acc = (await db.execute(
        select(Account).where(
            Account.brand_id == case.brand_id,
            Account.account_type == 'cash',
            Account.level == 'project',
        )
    )).scalar_one_or_none()
    if not brand_cash_acc:
        raise HTTPException(400, "该品牌未配置现金账户，无法执行稽查扣款")

    main_wh = (await db.execute(
        select(Warehouse).where(Warehouse.brand_id == case.brand_id, Warehouse.warehouse_type == 'main', Warehouse.is_active == True)
    )).scalar_one_or_none()
    backup_wh = (await db.execute(
        select(Warehouse).where(Warehouse.brand_id == case.brand_id, Warehouse.warehouse_type == 'backup', Warehouse.is_active == True)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    batch_no = f"IC-{case.case_no}"

    # 预算总支出，校验余额
    total_debit = Decimal("0")
    if case.case_type in ('outflow_malicious', 'outflow_nonmalicious'):
        total_debit += case.purchase_price * bottles
    if case.case_type in ('outflow_malicious', 'outflow_nonmalicious', 'outflow_transfer'):
        total_debit += case.penalty_amount or Decimal("0")
    if case.case_type == 'inflow_transfer':
        total_debit += case.purchase_price * bottles
    if total_debit > 0 and brand_cash_acc.balance < total_debit:
        raise HTTPException(400,
            f"品牌现金账户余额不足：{brand_cash_acc.balance} < 需付 ¥{total_debit}。请先从总资金池调拨到品牌现金账户。")

    # 1. 付款/收款
    if case.case_type == 'outflow_malicious' or case.case_type == 'outflow_nonmalicious':
        pay_amt = case.purchase_price * bottles
        if pay_amt > 0:
            brand_cash_acc.balance -= pay_amt
            await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=pay_amt,
                balance_after=brand_cash_acc.balance, related_type='inspection_payment', related_id=case.id,
                notes=f"稽查回收付款 {case.case_no} ({bottles}瓶)")
    if case.case_type in ('outflow_malicious', 'outflow_nonmalicious', 'outflow_transfer') and case.penalty_amount > 0:
        brand_cash_acc.balance -= case.penalty_amount
        await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=case.penalty_amount,
            balance_after=brand_cash_acc.balance, related_type='inspection_penalty', related_id=case.id,
            notes=f"稽查罚款 {case.case_no}")
    if case.case_type == 'inflow_transfer':
        pay_amt = case.purchase_price * bottles
        if pay_amt > 0:
            brand_cash_acc.balance -= pay_amt
            await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=pay_amt,
                balance_after=brand_cash_acc.balance, related_type='inspection_payment', related_id=case.id,
                notes=f"转码入库付款 {case.case_no} ({bottles}瓶)")
    if case.case_type == 'inflow_resell':
        income = case.resell_price * bottles
        if income > 0:
            brand_cash_acc.balance += income
            await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='credit', amount=income,
                balance_after=brand_cash_acc.balance, related_type='inspection_income', related_id=case.id,
                notes=f"清理回售收款 {case.case_no} ({bottles}瓶)")

    # 2. 入库/出库
    target_wh = None
    cost_price = None
    if case.case_type == 'outflow_malicious':
        target_wh = backup_wh
        cost_price = case.purchase_price  # 备用库以回收价入账
    elif case.case_type == 'outflow_nonmalicious':
        target_wh = main_wh
        cost_price = case.original_sale_price or case.purchase_price  # 主仓按售价入账
    elif case.case_type == 'inflow_transfer':
        target_wh = main_wh
        cost_price = case.original_sale_price or case.purchase_price  # 主仓按售价入账

    if target_wh and cost_price is not None:
        # 入库
        existing_inv = (await db.execute(
            select(Inventory).where(
                Inventory.product_id == case.product_id,
                Inventory.warehouse_id == target_wh.id,
                Inventory.batch_no == batch_no,
            )
        )).scalar_one_or_none()
        if existing_inv:
            existing_inv.quantity += bottles
        else:
            db.add(Inventory(
                product_id=case.product_id, warehouse_id=target_wh.id,
                batch_no=batch_no, quantity=bottles, cost_price=cost_price,
                stock_in_date=now,
            ))
        flow = StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_no("SF"),
            flow_type="inbound", product_id=case.product_id, warehouse_id=target_wh.id,
            batch_no=batch_no, cost_price=cost_price, quantity=bottles,
            reference_no=case.case_no, notes=f"稽查入库 {case.case_no} ({bottles}瓶)",
        )
        db.add(flow)
        # 绑定条码
        if body.barcodes:
            from app.models.inventory import InventoryBarcode
            from app.models.base import InventoryBarcodeStatus, InventoryBarcodeType
            for code in body.barcodes:
                code = code.strip()
                if not code:
                    continue
                exists = (await db.execute(select(InventoryBarcode).where(InventoryBarcode.barcode == code))).scalar_one_or_none()
                if not exists:
                    db.add(InventoryBarcode(
                        id=str(uuid.uuid4()), barcode=code, barcode_type=InventoryBarcodeType.CASE,
                        product_id=case.product_id, warehouse_id=target_wh.id,
                        batch_no=batch_no, status=InventoryBarcodeStatus.IN_STOCK,
                    ))
    elif case.case_type == 'inflow_resell' and backup_wh:
        # B1 从备用库出库
        inv_rows = (await db.execute(
            select(Inventory).where(
                Inventory.product_id == case.product_id,
                Inventory.warehouse_id == backup_wh.id,
                Inventory.quantity > 0,
            ).order_by(Inventory.stock_in_date.asc())
        )).scalars().all()
        available = sum(r.quantity for r in inv_rows)
        if available < bottles:
            raise HTTPException(400, f"备用库库存不足：需要{bottles}瓶，可用{available}瓶")
        remaining = bottles
        for inv in inv_rows:
            if remaining <= 0:
                break
            deduct = min(inv.quantity, remaining)
            inv.quantity -= deduct
            remaining -= deduct
        flow = StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_no("SF"),
            flow_type="outbound", product_id=case.product_id, warehouse_id=backup_wh.id,
            batch_no=inv_rows[0].batch_no if inv_rows else "fallback", quantity=bottles,
            reference_no=case.case_no, notes=f"稽查回售出库 {case.case_no} ({bottles}瓶)",
        )
        db.add(flow)

    # 3. 更新状态 + 记录执行时间（利润台账按此时间过滤）
    case.status = 'executed'
    case.closed_at = now
    if body.voucher_urls:
        case.voucher_urls = body.voucher_urls

    await db.flush()
    await log_audit(db, action="execute_inspection_case", entity_type="InspectionCase", entity_id=case.id,
                    changes={"case_type": case.case_type, "bottles": bottles}, user=user)
    return {"detail": f"执行完成，案件 {case.case_no}", "bottles": bottles}


@router.delete("/inspection-cases/{case_id}", status_code=204)
async def delete_inspection_case(
    case_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(InspectionCase, case_id)
    if obj is None:
        raise HTTPException(404, "InspectionCase not found")
    # 已执行的案件不允许删除（库存+账户已变动）
    if obj.status in ('processing', 'settled', 'closed'):
        raise HTTPException(400, f"已执行的案件（状态={obj.status}）不能删除，如需修正请联系财务管理员手工调账")

    # 反转 create 时产生的账户变动（pending/approved 状态）
    from app.models.product import Account
    from app.api.routes.accounts import record_fund_flow
    if obj.brand_id and obj.case_type in ('outflow_transfer', 'inflow_transfer'):
        ptm_acc = (await db.execute(
            select(Account).where(Account.brand_id == obj.brand_id, Account.account_type == 'payment_to_mfr')
        )).scalar_one_or_none()
        if ptm_acc:
            if obj.case_type == 'outflow_transfer' and obj.transfer_amount and obj.transfer_amount > 0:
                ptm_acc.balance += obj.transfer_amount  # 加回来
                await record_fund_flow(db, account_id=ptm_acc.id, flow_type='credit',
                    amount=obj.transfer_amount, balance_after=ptm_acc.balance,
                    related_type='transfer_deduction_reverse', related_id=obj.id,
                    notes=f"撤销被转码扣减 {obj.case_no}")
            elif obj.case_type == 'inflow_transfer' and obj.purchase_price and obj.quantity:
                from app.models.product import Product
                prod = await db.get(Product, obj.product_id) if obj.product_id else None
                bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
                bottles = obj.quantity * bpc if obj.quantity_unit == '箱' else obj.quantity
                amt = obj.purchase_price * bottles
                if amt > 0:
                    ptm_acc.balance -= amt
                    await record_fund_flow(db, account_id=ptm_acc.id, flow_type='debit',
                        amount=amt, balance_after=ptm_acc.balance,
                        related_type='transfer_credit_reverse', related_id=obj.id,
                        notes=f"撤销转码入库 {obj.case_no}")

    await log_audit(db, action="delete_inspection_case", entity_type="InspectionCase", entity_id=obj.id,
                    changes={"case_no": obj.case_no, "case_type": obj.case_type, "status": obj.status}, user=user)
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# MarketCleanupCase CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/cleanup-cases", response_model=MarketCleanupCaseResponse, status_code=201)
async def create_cleanup_case(
    body: MarketCleanupCaseCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = MarketCleanupCase(
        id=str(uuid.uuid4()), case_no=_gen_no("CL"), **body.model_dump()
    )
    db.add(obj)
    await db.flush()
    await log_audit(db, action="create_cleanup_case", entity_type="MarketCleanupCase", entity_id=obj.id, user=user)
    return obj


@router.get("/cleanup-cases", response_model=list[MarketCleanupCaseResponse])
async def list_cleanup_cases(
    user: CurrentUser,
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MarketCleanupCase)
    if status:
        stmt = stmt.where(MarketCleanupCase.status == status)
    stmt = stmt.order_by(MarketCleanupCase.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/cleanup-cases/{case_id}", response_model=MarketCleanupCaseResponse)
async def get_cleanup_case(
    case_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(MarketCleanupCase, case_id)
    if obj is None:
        raise HTTPException(404, "MarketCleanupCase not found")
    return obj


@router.put("/cleanup-cases/{case_id}", response_model=MarketCleanupCaseResponse)
async def update_cleanup_case(
    case_id: str, body: MarketCleanupCaseUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(MarketCleanupCase, case_id)
    if obj is None:
        raise HTTPException(404, "MarketCleanupCase not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/cleanup-cases/{case_id}", status_code=204)
async def delete_cleanup_case(
    case_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(MarketCleanupCase, case_id)
    if obj is None:
        raise HTTPException(404, "MarketCleanupCase not found")
    await db.delete(obj)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Inventory linkage endpoints
# ═══════════════════════════════════════════════════════════════════


class RecoverToStockRequest(BaseModel):
    warehouse_id: str
    batch_no: str
    quantity: int


class CleanupStockInRequest(BaseModel):
    batch_no: str
    quantity: int


async def _upsert_inventory(
    db: AsyncSession,
    product_id: str,
    warehouse_id: str,
    batch_no: str,
    quantity: int,
    cost_price: Decimal,
) -> None:
    """Add *quantity* to existing Inventory row or create a new one."""
    stmt = select(Inventory).where(
        Inventory.product_id == product_id,
        Inventory.warehouse_id == warehouse_id,
        Inventory.batch_no == batch_no,
    )
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if inv is not None:
        inv.quantity += quantity
    else:
        inv = Inventory(
            product_id=product_id,
            warehouse_id=warehouse_id,
            batch_no=batch_no,
            quantity=quantity,
            cost_price=cost_price,
            stock_in_date=datetime.now(timezone.utc),
        )
        db.add(inv)


@router.post("/inspection-cases/{case_id}/recover-to-stock", status_code=200)
async def recover_to_stock(
    case_id: str,
    body: RecoverToStockRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Recover goods from an inspection violation into backup warehouse stock."""
    case = await db.get(InspectionCase, case_id)
    if case is None:
        raise HTTPException(404, "InspectionCase not found")
    if not case.into_backup_stock:
        raise HTTPException(
            400, "Case is not marked for backup-stock recovery (into_backup_stock=False)"
        )

    flow_id = str(uuid.uuid4())
    flow = StockFlow(
        id=flow_id,
        flow_no=_gen_no("SF"),
        flow_type="inbound",
        product_id=case.product_id,
        warehouse_id=body.warehouse_id,
        batch_no=body.batch_no,
        cost_price=case.recovery_price,
        quantity=body.quantity,
        reference_no=case.case_no,
        notes=f"Recovered from inspection case {case.case_no}",
    )
    db.add(flow)

    await _upsert_inventory(
        db,
        product_id=case.product_id,
        warehouse_id=body.warehouse_id,
        batch_no=body.batch_no,
        quantity=body.quantity,
        cost_price=case.recovery_price,
    )

    case.related_inventory_flow_id = flow_id
    case.status = "recovered"

    await db.flush()
    await log_audit(
        db,
        action="recover_to_stock",
        entity_type="InspectionCase",
        entity_id=case.id, user=user)
    return {"detail": "Stock recovered", "stock_flow_id": flow_id}


@router.post("/cleanup-cases/{case_id}/stock-in", status_code=200)
async def cleanup_stock_in(
    case_id: str,
    body: CleanupStockInRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Move cleanup-case goods into the main warehouse at manufacturer price."""
    case = await db.get(MarketCleanupCase, case_id)
    if case is None:
        raise HTTPException(404, "MarketCleanupCase not found")
    if not case.into_main_warehouse:
        raise HTTPException(
            400, "Case is not marked for main-warehouse intake (into_main_warehouse=False)"
        )

    flow_id = str(uuid.uuid4())
    flow = StockFlow(
        id=flow_id,
        flow_no=_gen_no("SF"),
        flow_type="inbound",
        product_id=case.product_id,
        warehouse_id=case.main_warehouse_id,
        batch_no=body.batch_no,
        cost_price=case.manufacturer_price,
        quantity=body.quantity,
        reference_no=case.case_no,
        notes=f"Stock-in from cleanup case {case.case_no}",
    )
    db.add(flow)

    await _upsert_inventory(
        db,
        product_id=case.product_id,
        warehouse_id=case.main_warehouse_id,
        batch_no=body.batch_no,
        quantity=body.quantity,
        cost_price=case.manufacturer_price,
    )

    case.related_inventory_flow_id = flow_id
    case.status = "stocked_in"

    await db.flush()
    await log_audit(
        db,
        action="cleanup_stock_in",
        entity_type="MarketCleanupCase",
        entity_id=case.id, user=user)
    return {"detail": "Stock in completed", "stock_flow_id": flow_id}
