from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.budget.categories import effective_category
from app.budget.db import get_session
from app.budget.models import Transaction
from app.budget.schemas import TransactionCreate, TransactionRead, TransactionUpdate

router = APIRouter(prefix="/api", tags=["transactions"])


def _to_read(txn: Transaction) -> TransactionRead:
    return TransactionRead(
        id=txn.id, account_id=txn.account_id, date=txn.date, name=txn.name,
        merchant_name=txn.merchant_name, amount=txn.amount, category=txn.category,
        user_category=txn.user_category, effective_category=effective_category(txn),
        pending=txn.pending, is_manual=(txn.plaid_transaction_id is None),
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
    if category:
        rows = [t for t in rows if effective_category(t) == category]
    return [_to_read(t) for t in rows]


@router.post("/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(body: TransactionCreate, session: Session = Depends(get_session)):
    txn = Transaction(**body.model_dump())
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn)


@router.patch("/transactions/{txn_id}", response_model=TransactionRead)
def update_transaction(txn_id: int, body: TransactionUpdate, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.user_category = body.user_category
    session.add(txn); session.commit(); session.refresh(txn)
    return _to_read(txn)


@router.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.plaid_transaction_id is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a bank-synced transaction")
    session.delete(txn); session.commit()
    return Response(status_code=204)
