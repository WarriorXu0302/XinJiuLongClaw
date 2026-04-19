"""
Account management API — master/project accounts, fund transfers, fund flow ledger.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.product import Account
from app.models.fund_flow import FundFlow
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}"


async def record_fund_flow(
    db, *, account_id: str, flow_type: str, amount: Decimal,
    balance_after: Decimal, related_type: str = None, related_id: str = None,
    voucher_url: str = None, notes: str = None, created_by: str = None,
    brand_id: str = None,
) -> FundFlow:
    """Helper: insert a FundFlow record. Auto-fills brand_id from account if not given."""
    if not brand_id:
        account = await db.get(Account, account_id)
        if account:
            brand_id = account.brand_id
    ff = FundFlow(
        id=str(uuid.uuid4()),
        flow_no=_gen_no("FF"),
        account_id=account_id,
        brand_id=brand_id,
        flow_type=flow_type,
        amount=amount,
        balance_after=balance_after,
        related_type=related_type,
        related_id=related_id,
        voucher_url=voucher_url,
        notes=notes,
        created_by=created_by,
    )
    db.add(ff)
    return ff


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    account_type: str
    level: str = "project"
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    balance: float
    bank: Optional[str] = None
    account_no: Optional[str] = None
    is_active: bool = True


class BrandAccountGroup(BaseModel):
    brand_id: Optional[str]
    brand_name: str
    cash_balance: float = 0
    f_class_balance: float = 0
    financing_balance: float = 0
    total: float = 0
    accounts: list[AccountResponse]


class AccountSummary(BaseModel):
    master_balance: float
    project_total: float
    grand_total: float
    master_accounts: list[AccountResponse]
    brand_groups: list[BrandAccountGroup]


class FundTransferRequest(BaseModel):
    from_account_id: str
    to_account_id: str
    amount: float
    notes: Optional[str] = None


class FundTransferRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    from_account_id: str
    to_account_id: str
    amount: float
    status: str
    notes: Optional[str] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: Optional[str] = None


# In-memory model for transfer requests (simple approach using fund_flows table)
# We use FundFlow with flow_type='transfer_pending' as the approval record

@router.post("/accounts/transfer")
async def submit_fund_transfer(
    body: FundTransferRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Submit a transfer request for approval. Does NOT move money yet."""
    if body.amount <= 0:
        raise HTTPException(400, "调拨金额必须大于0")

    from_acc = await db.get(Account, body.from_account_id)
    to_acc = await db.get(Account, body.to_account_id)
    if not from_acc:
        raise HTTPException(404, "转出账户不存在")
    if not to_acc:
        raise HTTPException(404, "转入账户不存在")
    if from_acc.level != 'master':
        raise HTTPException(400, "只能从总账户拨款到项目账户")
    if to_acc.level != 'project':
        raise HTTPException(400, "只能拨款到品牌项目账户")
    if to_acc.account_type == 'f_class':
        raise HTTPException(400, "F类账户只接收厂家政策打款，不能接受调拨")

    amount = Decimal(str(body.amount))
    if from_acc.balance < amount:
        raise HTTPException(400, f"总账户余额不足：当前 ¥{from_acc.balance}，需拨 ¥{amount}")

    # Create a pending transfer record
    ff = FundFlow(
        id=str(uuid.uuid4()),
        flow_no=_gen_no("TF"),
        account_id=from_acc.id,
        brand_id=to_acc.brand_id,
        flow_type='transfer_pending',
        amount=amount,
        balance_after=from_acc.balance,  # snapshot, not yet deducted
        related_type='transfer',
        related_id=to_acc.id,  # store target account id
        notes=f"待审批：拨款至 {to_acc.name} | {body.notes or ''}",
        created_by=user.get('employee_id'),
    )
    db.add(ff)
    await db.flush()

    return {"message": "拨款申请已提交，等待审批", "transfer_id": ff.id, "status": "pending"}


@router.get("/accounts/pending-transfers")
async def list_pending_transfers(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """List all pending transfer requests for approval."""
    rows = (await db.execute(
        select(FundFlow).where(FundFlow.flow_type == 'transfer_pending').order_by(FundFlow.created_at.desc())
    )).scalars().all()
    result = []
    for ff in rows:
        from_acc = await db.get(Account, ff.account_id)
        to_acc = await db.get(Account, ff.related_id) if ff.related_id else None
        result.append({
            "id": ff.id,
            "flow_no": ff.flow_no,
            "from_account": from_acc.name if from_acc else ff.account_id,
            "to_account": to_acc.name if to_acc else ff.related_id,
            "to_brand": to_acc.brand.name if to_acc and to_acc.brand else None,
            "amount": float(ff.amount),
            "notes": ff.notes,
            "created_at": str(ff.created_at) if ff.created_at else None,
        })
    return result


@router.post("/accounts/transfers/{transfer_id}/approve")
async def approve_fund_transfer(
    transfer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Approve a pending transfer → actually move the money."""
    ff = await db.get(FundFlow, transfer_id)
    if ff is None:
        raise HTTPException(404, "拨款申请不存在")
    if ff.flow_type != 'transfer_pending':
        raise HTTPException(400, "该记录不是待审批的拨款申请")

    from_acc = await db.get(Account, ff.account_id)
    to_acc = await db.get(Account, ff.related_id) if ff.related_id else None
    if not from_acc or not to_acc:
        raise HTTPException(400, "账户不存在")

    amount = ff.amount
    if from_acc.balance < amount:
        raise HTTPException(400, f"总账户余额不足：当前 ¥{from_acc.balance}，需拨 ¥{amount}")

    # Execute transfer
    from_acc.balance -= amount
    to_acc.balance += amount

    # Mark original as approved and executed
    ff.flow_type = 'transfer_out'
    ff.balance_after = from_acc.balance
    ff.approved_by = user.get('employee_id')
    ff.approved_at = datetime.now(timezone.utc)
    ff.notes = (ff.notes or '').replace('待审批：', '已审批：')

    # Create transfer_in record
    await record_fund_flow(
        db, account_id=to_acc.id, flow_type='transfer_in', amount=amount,
        balance_after=to_acc.balance, related_type='transfer',
        notes=f"从总账户拨入（已审批）: {ff.notes or ''}",
        created_by=user.get('employee_id'),
    )

    await db.flush()
    await log_audit(db, action="approve_fund_transfer", entity_type="Account", entity_id=from_acc.id,
                    changes={"from": from_acc.name, "to": to_acc.name, "amount": float(amount)}, user=user)

    return {"message": f"已审批，¥{amount} 从 {from_acc.name} 拨至 {to_acc.name}", "from_balance": float(from_acc.balance), "to_balance": float(to_acc.balance)}


@router.post("/accounts/transfers/{transfer_id}/reject")
async def reject_fund_transfer(
    transfer_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Reject a pending transfer."""
    ff = await db.get(FundFlow, transfer_id)
    if ff is None:
        raise HTTPException(404, "拨款申请不存在")
    if ff.flow_type != 'transfer_pending':
        raise HTTPException(400, "该记录不是待审批的拨款申请")
    ff.flow_type = 'transfer_rejected'
    ff.notes = (ff.notes or '').replace('待审批：', '已驳回：')
    await db.flush()
    return {"message": "拨款申请已驳回"}


class FundFlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    flow_no: str
    account_id: str
    brand_id: Optional[str] = None
    flow_type: str
    amount: float
    balance_after: float
    related_type: Optional[str] = None
    related_id: Optional[str] = None
    voucher_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(user: CurrentUser, brand_id: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    stmt = select(Account).where(Account.is_active == True)
    if brand_id:
        from sqlalchemy import or_
        stmt = stmt.where(or_(Account.brand_id == brand_id, Account.level == 'master'))
    stmt = stmt.order_by(Account.level, Account.code)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for a in rows:
        d = AccountResponse.model_validate(a).model_dump()
        d['brand_name'] = a.brand.name if a.brand else None
        result.append(d)
    return result


@router.get("/accounts/summary", response_model=AccountSummary)
async def account_summary(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Account).where(Account.is_active == True).order_by(Account.level, Account.code)
    )).scalars().all()

    master_accounts = []
    brand_map: dict[str, BrandAccountGroup] = {}

    for a in rows:
        resp = AccountResponse.model_validate(a)
        resp_d = resp.model_dump()
        resp_d['brand_name'] = a.brand.name if a.brand else None

        if a.level == 'master':
            master_accounts.append(resp_d)
        else:
            bid = a.brand_id or '_none'
            bname = a.brand.name if a.brand else '未分配'
            if bid not in brand_map:
                brand_map[bid] = BrandAccountGroup(
                    brand_id=a.brand_id, brand_name=bname, accounts=[]
                )
            grp = brand_map[bid]
            grp.accounts.append(resp_d)
            bal = float(a.balance)
            if a.account_type == 'cash':
                grp.cash_balance += bal
                grp.total += bal
            elif a.account_type == 'f_class':
                grp.f_class_balance += bal
                grp.total += bal
            elif a.account_type == 'financing':
                grp.financing_balance += bal
                # NOT added to total — financing is a liability

    master_bal = sum(float(a.balance) for a in rows if a.level == 'master')
    project_total = sum(g.total for g in brand_map.values())

    return AccountSummary(
        master_balance=master_bal,
        project_total=project_total,
        grand_total=master_bal + project_total,
        master_accounts=master_accounts,
        brand_groups=list(brand_map.values()),
    )


@router.get("/accounts/fund-flows", response_model=list[FundFlowResponse])
async def list_fund_flows(
    user: CurrentUser,
    account_id: str | None = Query(None),
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FundFlow)
    if account_id:
        stmt = stmt.where(FundFlow.account_id == account_id)
    if brand_id:
        stmt = stmt.where(FundFlow.brand_id == brand_id)
    stmt = stmt.order_by(FundFlow.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


class ManualFundFlowCreate(BaseModel):
    account_id: str
    flow_type: str  # credit / debit
    amount: float
    related_type: Optional[str] = None
    notes: Optional[str] = None


@router.post("/accounts/fund-flows", status_code=201)
async def create_manual_fund_flow(
    body: ManualFundFlowCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Manual fund flow entry — for F-class arrivals, deductions, rewards, etc."""
    account = await db.get(Account, body.account_id)
    if not account:
        raise HTTPException(404, "账户不存在")
    amt = Decimal(str(body.amount))
    if body.flow_type == 'credit':
        account.balance += amt
    elif body.flow_type == 'debit':
        account.balance -= amt
    else:
        raise HTTPException(400, f"无效的 flow_type: {body.flow_type}")
    ff = await record_fund_flow(
        db, account_id=account.id, flow_type=body.flow_type, amount=amt,
        balance_after=account.balance, related_type=body.related_type,
        notes=body.notes, created_by=user.get('employee_id'),
    )
    await db.flush()
    return {"detail": f"已{'入账' if body.flow_type == 'credit' else '扣款'} ¥{amt}", "flow_id": ff.id, "balance": float(account.balance)}