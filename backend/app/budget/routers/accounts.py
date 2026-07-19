from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.budget.db import get_session
from app.budget.models import Account, PlaidItem
from app.budget.schemas import AccountRead

router = APIRouter(prefix="/api", tags=["accounts"])


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()


@router.post("/accounts/manual", response_model=AccountRead)
def ensure_manual_account(session: Session = Depends(get_session)):
    """Return the singleton local account used when a user declines Plaid."""
    account = session.exec(
        select(Account).where(Account.plaid_account_id == "manual-local")
    ).first()
    if account:
        return account

    item = session.exec(
        select(PlaidItem).where(PlaidItem.plaid_item_id == "manual-local")
    ).first()
    if not item:
        # Empty access_token marks a local-only item. Plaid refresh/sync excludes it.
        item = PlaidItem(plaid_item_id="manual-local", access_token="")
        session.add(item)
        session.flush()
        session.refresh(item)

    account = Account(
        plaid_account_id="manual-local",
        item_id=item.id,
        name="Manual finances",
        type="cash",
        subtype="manual",
        currency="USD",
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account
