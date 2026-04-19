"""
Policy service — settlement allocation, proportional distribution
to claim items, and automatic advance-repayment request generation.
"""
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import (
    AdvancePayerType,
    ClaimRecordStatus,
    PayeeType,
    PaymentRequestStatus,
)
from app.models.finance import FinancePaymentRequest, ManufacturerSettlement
from app.models.policy import (
    ClaimSettlementLink,
    PolicyClaim,
    PolicyClaimItem,
    PolicyUsageRecord,
)
from app.models.policy_request_item import PolicyRequestItem


def _generate_request_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"PR-{ts}-{short}"


async def confirm_settlement_allocation(
    db: AsyncSession,
    *,
    settlement_id: str,
    claim_id: str,
    allocated_amount: Decimal,
    confirmed_by: str,
) -> ClaimSettlementLink:
    """Allocate part (or all) of a manufacturer settlement to a policy claim.

    Business flow (PRD §3.2.5 + §3.2.6):
      1. Create ``claim_settlement_links`` record.
      2. Update financial totals on both claim and settlement.
      3. Proportionally distribute the allocated amount across
         ``policy_claim_items`` (by ``declared_amount`` ratio),
         updating each item's ``approved_amount``.
      4. For each item whose upstream ``policy_usage_record`` has
         ``advance_payer_type == 'employee'``, auto-generate a
         ``payment_request`` (status=pending) to close the
         advance-repayment loop.

    Returns the created ClaimSettlementLink.
    Raises ValueError on validation failure.
    """
    if allocated_amount <= 0:
        raise ValueError("allocated_amount must be > 0")

    # -----------------------------------------------------------------
    # 1. Load & validate settlement and claim (with row locks)
    # -----------------------------------------------------------------
    settlement = (
        await db.execute(
            select(ManufacturerSettlement)
            .where(ManufacturerSettlement.id == settlement_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if settlement is None:
        raise ValueError(f"Settlement {settlement_id} not found")

    claim = (
        await db.execute(
            select(PolicyClaim)
            .where(PolicyClaim.id == claim_id)
            .options(selectinload(PolicyClaim.items))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if claim is None:
        raise ValueError(f"PolicyClaim {claim_id} not found")

    if allocated_amount > settlement.unsettled_amount:
        raise ValueError(
            f"Allocated {allocated_amount} exceeds settlement "
            f"unsettled balance {settlement.unsettled_amount}"
        )
    if allocated_amount > claim.unsettled_amount:
        raise ValueError(
            f"Allocated {allocated_amount} exceeds claim "
            f"unsettled balance {claim.unsettled_amount}"
        )

    items: list[PolicyClaimItem] = claim.items
    if not items:
        raise ValueError(f"PolicyClaim {claim_id} has no claim items")

    now = datetime.now(timezone.utc)

    # -----------------------------------------------------------------
    # 2. Create the link record
    # -----------------------------------------------------------------
    link = ClaimSettlementLink(
        id=str(uuid.uuid4()),
        claim_id=claim_id,
        settlement_id=settlement_id,
        allocated_amount=allocated_amount,
        confirmed_by=confirmed_by,
        confirmed_at=now,
    )
    db.add(link)

    # -----------------------------------------------------------------
    # 3. Update settlement totals
    # -----------------------------------------------------------------
    settlement.settled_amount += allocated_amount
    settlement.unsettled_amount -= allocated_amount

    # -----------------------------------------------------------------
    # 4. Update claim totals & status
    # -----------------------------------------------------------------
    claim.settled_amount += allocated_amount
    claim.unsettled_amount -= allocated_amount

    if claim.settled_amount >= claim.claim_amount:
        claim.status = ClaimRecordStatus.SETTLED
    else:
        claim.status = ClaimRecordStatus.PARTIALLY_SETTLED

    # -----------------------------------------------------------------
    # 5. Proportional distribution to claim items
    #    Rule (PRD §3.2.5): pro-rata by declared_amount.
    #    Remainder correction on last item to guarantee sum == allocated.
    # -----------------------------------------------------------------
    total_declared = sum(it.declared_amount for it in items)
    if total_declared <= 0:
        raise ValueError("Total declared_amount across claim items is 0")

    # Pre-compute each item's share (single pass, reused in step 6)
    shares: list[Decimal] = []
    distributed_sum = Decimal("0.00")
    for idx, item in enumerate(items):
        if idx == len(items) - 1:
            share = allocated_amount - distributed_sum
        else:
            share = (
                allocated_amount * item.declared_amount / total_declared
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            distributed_sum += share
        shares.append(share)

    # Apply shares to approved_amount
    for item, share in zip(items, shares):
        item.approved_amount += share

    # -----------------------------------------------------------------
    # 6. Update source item settled_amount + advance-repayment logic
    # -----------------------------------------------------------------
    for item, share in zip(items, shares):
        if share <= 0:
            continue

        advance_payer_type = None
        advance_employee_id = None
        advance_customer_id = None

        # --- New path: source_request_item_id ---
        if item.source_request_item_id:
            ri = await db.get(PolicyRequestItem, item.source_request_item_id)
            if ri:
                ri.settled_amount += share
                if ri.settled_amount >= ri.total_value:
                    ri.fulfill_status = "settled"
                advance_payer_type = ri.advance_payer_type
                advance_employee_id = ri.advance_payer_id if ri.advance_payer_type == "employee" else None
                # For customer payer, advance_payer_id holds the customer_id
                advance_customer_id = ri.advance_payer_id if ri.advance_payer_type == "customer" else None

        # --- Legacy path: source_usage_record_id ---
        elif item.source_usage_record_id:
            usage = await db.get(PolicyUsageRecord, item.source_usage_record_id)
            if usage:
                advance_payer_type = usage.advance_payer_type
                advance_employee_id = usage.advance_employee_id
                advance_customer_id = usage.advance_customer_id

        # --- Generate payment requests for advance repayment ---
        if advance_payer_type == AdvancePayerType.EMPLOYEE and advance_employee_id:
            pr = FinancePaymentRequest(
                id=str(uuid.uuid4()),
                request_no=_generate_request_no(),
                source_usage_record_id=item.source_usage_record_id,
                related_claim_id=claim_id,
                payee_type=PayeeType.EMPLOYEE,
                payee_employee_id=advance_employee_id,
                amount=share,
                status=PaymentRequestStatus.PENDING,
            )
            db.add(pr)

        elif advance_payer_type == AdvancePayerType.CUSTOMER and advance_customer_id:
            pr = FinancePaymentRequest(
                id=str(uuid.uuid4()),
                request_no=_generate_request_no(),
                source_usage_record_id=item.source_usage_record_id,
                related_claim_id=claim_id,
                payee_type=PayeeType.CUSTOMER,
                payee_customer_id=advance_customer_id,
                amount=share,
                status=PaymentRequestStatus.PENDING,
            )
            db.add(pr)

        elif advance_payer_type == AdvancePayerType.COMPANY:
            from app.models.product import Account
            from app.api.routes.accounts import record_fund_flow

            brand_id = claim.brand_id
            if brand_id:
                f_class_acc = (
                    await db.execute(
                        select(Account).where(
                            Account.brand_id == brand_id,
                            Account.account_type == "f_class",
                            Account.level == "project",
                        )
                    )
                ).scalar_one_or_none()
                cash_acc = (
                    await db.execute(
                        select(Account).where(
                            Account.brand_id == brand_id,
                            Account.account_type == "cash",
                            Account.level == "project",
                        )
                    )
                ).scalar_one_or_none()
                if f_class_acc and cash_acc and share > 0:
                    f_class_acc.balance -= share
                    cash_acc.balance += share
                    await record_fund_flow(
                        db, account_id=f_class_acc.id, flow_type='debit',
                        amount=share, balance_after=f_class_acc.balance,
                        related_type='company_advance', related_id=claim_id,
                        notes=f"公司垫付回收：F类→现金 ¥{share}",
                    )
                    await record_fund_flow(
                        db, account_id=cash_acc.id, flow_type='credit',
                        amount=share, balance_after=cash_acc.balance,
                        related_type='company_advance', related_id=claim_id,
                        notes=f"公司垫付回收：F类→现金 ¥{share}",
                    )

    await db.flush()
    return link
