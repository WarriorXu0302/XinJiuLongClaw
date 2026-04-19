"""
ExpenseClaim API — F类报账 + 日常开销 unified CRUD and workflow.
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
from app.models.expense_claim import ExpenseClaim
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{ts}-{uuid.uuid4().hex[:6]}"


class ClaimCreate(BaseModel):
    claim_type: str  # f_class / daily
    brand_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    amount: float
    notes: Optional[str] = None


class ClaimUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    scheme_no: Optional[str] = None
    voucher_urls: Optional[list[str]] = None
    receipt_urls: Optional[list[str]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


def _to_response(c: ExpenseClaim) -> dict:
    return {
        "id": c.id, "claim_no": c.claim_no, "claim_type": c.claim_type,
        "brand_id": c.brand_id,
        "brand_name": c.brand.name if c.brand else None,
        "title": c.title, "description": c.description,
        "amount": float(c.amount),
        "scheme_no": c.scheme_no,
        "arrival_amount": float(c.arrival_amount),
        "voucher_urls": c.voucher_urls, "receipt_urls": c.receipt_urls,
        "status": c.status,
        "applicant_name": c.applicant.name if c.applicant else None,
        "approved_by_name": c.approver.name if c.approver else None,
        "notes": c.notes,
        "created_at": str(c.created_at) if c.created_at else None,
    }


@router.post("", status_code=201)
async def create_claim(body: ClaimCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    prefix = "FC" if body.claim_type == "f_class" else "DC"
    c = ExpenseClaim(
        id=str(uuid.uuid4()),
        claim_no=_gen_no(prefix),
        claim_type=body.claim_type,
        brand_id=body.brand_id,
        title=body.title,
        description=body.description,
        amount=Decimal(str(body.amount)),
        applicant_id=user.get("employee_id"),
        notes=body.notes,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c, ["brand", "applicant", "approver"])
    return _to_response(c)


@router.get("")
async def list_claims(
    user: CurrentUser,
    claim_type: Optional[str] = Query(None),
    brand_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ExpenseClaim)
    if claim_type:
        stmt = stmt.where(ExpenseClaim.claim_type == claim_type)
    if brand_id:
        stmt = stmt.where(ExpenseClaim.brand_id == brand_id)
    if status:
        stmt = stmt.where(ExpenseClaim.status == status)
    stmt = stmt.order_by(ExpenseClaim.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_response(c) for c in rows]


@router.get("/{claim_id}")
async def get_claim(claim_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    return _to_response(c)


@router.put("/{claim_id}")
async def update_claim(claim_id: str, body: ClaimUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == 'amount' and v is not None:
            setattr(c, k, Decimal(str(v)))
        else:
            setattr(c, k, v)
    await db.flush()
    await db.refresh(c, ["brand", "applicant", "approver"])
    return _to_response(c)


@router.post("/{claim_id}/approve")
async def approve_claim(claim_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    if c.status != "pending":
        raise HTTPException(400, f"状态为 '{c.status}'，只有待审批的能审批")
    c.status = "approved"
    c.approved_by = user.get("employee_id")

    # share_out：审批通过时自动 1)总资金池入账 2)回款账户扣减
    if c.claim_type == "share_out" and c.brand_id and c.amount > 0:
        from app.models.product import Account
        from app.api.routes.accounts import record_fund_flow

        # 总资金池入账
        master_acc = (await db.execute(
            select(Account).where(Account.level == "master")
        )).scalar_one_or_none()
        if master_acc:
            master_acc.balance += c.amount
            await record_fund_flow(
                db, account_id=master_acc.id, flow_type='credit', amount=c.amount,
                balance_after=master_acc.balance, related_type='share_out_income',
                related_id=c.id, notes=f"分货收款: {c.title}",
            )

        # 回款账户扣减
        ptm_acc = (await db.execute(
            select(Account).where(Account.brand_id == c.brand_id, Account.account_type == 'payment_to_mfr')
        )).scalar_one_or_none()
        if ptm_acc:
            ptm_acc.balance -= c.amount
            await record_fund_flow(
                db, account_id=ptm_acc.id, flow_type='debit', amount=c.amount,
                balance_after=ptm_acc.balance, related_type='share_out',
                related_id=c.id, notes=f"分货扣减回款: {c.title}",
            )

    await db.flush()
    await log_audit(db, action="approve_expense_claim", entity_type="ExpenseClaim", entity_id=c.id, user=user)
    return {"detail": "审批通过"}


@router.post("/{claim_id}/reject")
async def reject_claim(claim_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    c.status = "rejected"
    await db.flush()
    return {"detail": "已驳回"}


@router.post("/{claim_id}/apply")
async def apply_scheme(claim_id: str, body: ClaimUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """F类：审批后录入方案号，进入对账流程"""
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    if body.scheme_no:
        c.scheme_no = body.scheme_no
    if body.notes:
        c.notes = body.notes
    c.status = "applied"
    await db.flush()
    return {"detail": "已录入方案号，等待对账"}


@router.post("/{claim_id}/confirm-arrival")
async def confirm_arrival(claim_id: str, user: CurrentUser, arrived_amount: float = Query(0), db: AsyncSession = Depends(get_db)):
    """F类：确认到账"""
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    c.arrival_amount = Decimal(str(arrived_amount)) if arrived_amount > 0 else c.amount
    c.status = "arrived"
    await db.flush()
    return {"detail": "已确认到账"}


@router.post("/{claim_id}/fulfill")
async def fulfill_claim(claim_id: str, body: ClaimUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """提交兑付/付款凭证"""
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    if body.voucher_urls:
        c.voucher_urls = body.voucher_urls
    if body.receipt_urls:
        c.receipt_urls = body.receipt_urls
    c.status = "fulfilled"
    await db.flush()
    return {"detail": "凭证已提交，等待确认"}


@router.post("/{claim_id}/pay")
async def pay_daily_claim(claim_id: str, user: CurrentUser, account_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """日常开销：从总资金池拨款"""
    from app.models.product import Account
    from app.api.routes.accounts import record_fund_flow

    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    if c.status != "approved":
        raise HTTPException(400, "需要先审批")

    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(400, "账户不存在")
    if acc.balance < c.amount:
        raise HTTPException(400, f"账户余额不足: ¥{acc.balance}，需 ¥{c.amount}")

    acc.balance -= c.amount
    await record_fund_flow(
        db, account_id=acc.id, flow_type='debit', amount=c.amount,
        balance_after=acc.balance, related_type='daily_expense', related_id=c.id,
        notes=f"日常开销: {c.title}",
    )
    c.paid_account_id = acc.id
    c.status = "paid"
    await db.flush()
    return {"detail": f"已从 {acc.name} 拨款 ¥{c.amount}"}


@router.post("/{claim_id}/settle")
async def settle_claim(claim_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """归档"""
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    c.status = "settled"
    await db.flush()
    await log_audit(db, action="settle_expense_claim", entity_type="ExpenseClaim", entity_id=c.id, user=user)
    return {"detail": "已归档"}


@router.delete("/{claim_id}", status_code=204)
async def delete_claim(claim_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    c = await db.get(ExpenseClaim, claim_id)
    if not c:
        raise HTTPException(404, "不存在")
    await db.delete(c)
    await db.flush()
