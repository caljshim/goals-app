from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.budget.categories import (
    TRANSFER_CATEGORIES,
    effective_category,
    is_incoming_p2p,
    merchant_key,
)
from app.budget.db import get_session
from app.budget.models import Budget, Transaction
from app.budget.services import rules as rules_svc
from app.budget.services.rules import load_rules
from app.budget.schemas import (
    BulkReimburseUpdate,
    BulkTransactionCategoryUpdate,
    MerchantCategoryUpdate,
    ReimburseUpdate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)

router = APIRouter(prefix="/api", tags=["transactions"])


def _budget_categories(session: Session) -> set[str]:
    return set(session.exec(select(Budget.category)).all())


def _to_read(
    txn: Transaction,
    rules: dict[str, str] | None = None,
    budget_categories: set[str] | None = None,
    session: Session | None = None,
) -> TransactionRead:
    category = effective_category(txn, rules)
    reimbursement_category = None
    if txn.reimburses_transaction_id is not None and session is not None:
        target = session.get(Transaction, txn.reimburses_transaction_id)
        if target is not None and target.amount > 0:
            reimbursement_category = effective_category(target, rules)
    elif is_incoming_p2p(txn) and category != "TRANSFER_IN":
        reimbursement_category = category
    is_budgeted = None
    if txn.amount > 0 and category not in TRANSFER_CATEGORIES:
        is_budgeted = category in (budget_categories or set())
    return TransactionRead(
        id=txn.id, account_id=txn.account_id, date=txn.date, name=txn.name,
        merchant_name=txn.merchant_name, amount=txn.amount, category=txn.category,
        user_category=txn.user_category, effective_category=category,
        pending=txn.pending, is_manual=(txn.plaid_transaction_id is None),
        reimburses_transaction_id=txn.reimburses_transaction_id,
        reimbursement_category=reimbursement_category,
        is_budgeted=is_budgeted,
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
    budget_categories = _budget_categories(session)
    return [_to_read(t, rules, budget_categories, session) for t in rows]


@router.post("/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(body: TransactionCreate, session: Session = Depends(get_session)):
    txn = Transaction(**body.model_dump())
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn, load_rules(session), _budget_categories(session), session)


def _load_bulk_transactions(session: Session, transaction_ids: list[int]) -> list[Transaction]:
    ordered_ids = list(dict.fromkeys(transaction_ids))
    rows = session.exec(select(Transaction).where(Transaction.id.in_(ordered_ids))).all()
    by_id = {row.id: row for row in rows}
    missing = [transaction_id for transaction_id in ordered_ids if transaction_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Transactions not found: {missing}")
    return [by_id[transaction_id] for transaction_id in ordered_ids]


@router.patch("/transactions/bulk-category", response_model=list[TransactionRead])
def bulk_update_transaction_category(
    body: BulkTransactionCategoryUpdate,
    session: Session = Depends(get_session),
):
    """Apply one category to a selected group in a single atomic database write."""
    rows = _load_bulk_transactions(session, body.transaction_ids)
    category = body.user_category.strip().replace(" ", "_").upper()
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")
    for txn in rows:
        txn.user_category = category
        txn.reimburses_transaction_id = None
        session.add(txn)
    session.commit()
    rules = load_rules(session)
    budget_categories = _budget_categories(session)
    return [_to_read(txn, rules, budget_categories, session) for txn in rows]


@router.patch("/transactions/bulk-reimburses", response_model=list[TransactionRead])
def bulk_set_reimbursement(
    body: BulkReimburseUpdate,
    session: Session = Depends(get_session),
):
    """Link several incoming reimbursements to the same exact expense atomically."""
    rows = _load_bulk_transactions(session, body.transaction_ids)
    target = session.get(Transaction, body.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Expense to reimburse not found")
    if target.amount <= 0:
        raise HTTPException(status_code=400, detail="Can only reimburse a spending transaction")
    if any(txn.amount >= 0 for txn in rows):
        raise HTTPException(status_code=400, detail="Only incoming amounts can reimburse an expense")
    for txn in rows:
        txn.reimburses_transaction_id = target.id
        txn.user_category = None
        session.add(txn)
    session.commit()
    rules = load_rules(session)
    budget_categories = _budget_categories(session)
    return [_to_read(txn, rules, budget_categories, session) for txn in rows]


@router.patch("/transactions/{txn_id}", response_model=TransactionRead)
def update_transaction(txn_id: int, body: TransactionUpdate, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    editable_fields = {"account_id", "date", "name", "amount"} & body.model_fields_set
    if editable_fields and txn.plaid_transaction_id is not None:
        raise HTTPException(status_code=400, detail="Cannot edit a bank-synced transaction")
    if "account_id" in editable_fields:
        if body.account_id is None:
            raise HTTPException(status_code=400, detail="Transaction account is required")
        txn.account_id = body.account_id
    if "date" in editable_fields:
        if body.date is None:
            raise HTTPException(status_code=400, detail="Transaction date is required")
        txn.date = body.date
    if "name" in editable_fields:
        clean_name = (body.name or "").strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="Transaction name is required")
        txn.name = clean_name
    if "amount" in editable_fields:
        if body.amount is None or body.amount == 0:
            raise HTTPException(status_code=400, detail="Transaction amount cannot be zero")
        txn.amount = body.amount
    if "user_category" in body.model_fields_set:
        txn.user_category = body.user_category
        # A category and a reimbursement link are mutually exclusive: assigning a category
        # drops any link (only reimbursements ever carry one, so this is a no-op otherwise).
        txn.reimburses_transaction_id = None
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn, load_rules(session), _budget_categories(session), session)


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
    return _to_read(txn, load_rules(session), _budget_categories(session), session)


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
        return _to_read(txn, load_rules(session), _budget_categories(session), session)

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
    return _to_read(txn, load_rules(session), _budget_categories(session), session)


@router.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.plaid_transaction_id is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a bank-synced transaction")
    session.delete(txn); session.commit()
    return Response(status_code=204)
