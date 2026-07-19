from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.budget.categories import effective_category, merchant_key
from app.budget.db import get_session
from app.budget.models import Transaction
from app.budget.services import rules as rules_svc
from app.budget.services.rules import load_rules
from app.budget.schemas import (
    MerchantCategoryUpdate,
    ReimburseUpdate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)

router = APIRouter(prefix="/api", tags=["transactions"])


def _to_read(txn: Transaction, rules: dict[str, str] | None = None) -> TransactionRead:
    return TransactionRead(
        id=txn.id, account_id=txn.account_id, date=txn.date, name=txn.name,
        merchant_name=txn.merchant_name, amount=txn.amount, category=txn.category,
        user_category=txn.user_category, effective_category=effective_category(txn, rules),
        pending=txn.pending, is_manual=(txn.plaid_transaction_id is None),
        reimburses_transaction_id=txn.reimburses_transaction_id,
    )


@router.get("/transactions", response_model=list[TransactionRead])
def list_transactions(
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    category: Optional[str] = None,
    account_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    query = select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())
    if start:
        query = query.where(Transaction.date >= start)
    if end:
        query = query.where(Transaction.date <= end)
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    rows = session.exec(query).all()
    rules = load_rules(session)
    if category:
        rows = [t for t in rows if effective_category(t, rules) == category]
    return [_to_read(t, rules) for t in rows]


@router.post("/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(body: TransactionCreate, session: Session = Depends(get_session)):
    txn = Transaction(**body.model_dump())
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn, load_rules(session))


@router.patch("/transactions/{txn_id}", response_model=TransactionRead)
def update_transaction(txn_id: int, body: TransactionUpdate, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.user_category = body.user_category
    # A category and a reimbursement link are mutually exclusive: assigning a category
    # drops any link (only reimbursements ever carry one, so this is a no-op otherwise).
    txn.reimburses_transaction_id = None
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn, load_rules(session))


@router.patch("/transactions/{txn_id}/merchant-category", response_model=TransactionRead)
def set_merchant_category(txn_id: int, body: MerchantCategoryUpdate, session: Session = Depends(get_session)):
    """Recategorize this transaction's whole merchant: create/update a rule so the
    category sticks for all its past & future transactions (see services.rules). Use
    the plain PATCH /transactions/{id} for a one-off that applies to only this row."""
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        rules_svc.set_merchant_rule(session, merchant_key(txn), body.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    session.refresh(txn)
    return _to_read(txn, load_rules(session))


@router.patch("/transactions/{txn_id}/reimburses", response_model=TransactionRead)
def set_reimbursement(txn_id: int, body: ReimburseUpdate, session: Session = Depends(get_session)):
    """Link an incoming reimbursement (e.g. a Zelle payment in) to the expense it pays
    back, or unlink it with target_id=null. The reduction nets against the linked
    expense's category and month (see services.summary)."""
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if body.target_id is None:
        txn.reimburses_transaction_id = None
        session.add(txn); session.commit(); session.refresh(txn)
        return _to_read(txn, load_rules(session))

    if body.target_id == txn_id:
        raise HTTPException(status_code=400, detail="A transaction cannot reimburse itself")
    if txn.amount >= 0:
        raise HTTPException(status_code=400, detail="Only an incoming amount can reimburse an expense")
    target = session.get(Transaction, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Expense to reimburse not found")
    if target.amount <= 0:
        raise HTTPException(status_code=400, detail="Can only reimburse a spending transaction")

    txn.reimburses_transaction_id = target.id
    # Linking supersedes a category-only reimbursement — keep the two mutually exclusive.
    txn.user_category = None
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn, load_rules(session))


@router.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.plaid_transaction_id is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a bank-synced transaction")
    session.delete(txn); session.commit()
    return Response(status_code=204)
