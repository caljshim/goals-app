from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.budget.db import get_session
from app.budget.models import Account, PlaidItem
from app.budget.plaid_client import (
    create_link_token,
    exchange_public_token,
    fetch_accounts,
    get_client,
    refresh_transactions,
)
from app.budget.schemas import ExchangeRequest
from app.budget.services.goals import record_financial_goal_snapshots
from app.budget.services.sync import sync_item

router = APIRouter(prefix="/api", tags=["plaid"])

_ACCOUNT_FIELDS = (
    "name", "official_name", "type", "subtype", "mask",
    "current_balance", "available_balance", "currency",
)


def _relink_match(session: Session, data: dict) -> Account | None:
    """Find one existing local account that represents a newly re-linked account.

    Plaid account IDs are stable within an Item, but linking the same institution as a
    new Item creates new IDs. A masked account signature lets us preserve local history
    without merging ambiguous or unmasked accounts.
    """
    if not data.get("mask"):
        return None
    label = (data.get("official_name") or data["name"]).strip().casefold()
    candidates = [
        account for account in session.exec(select(Account)).all()
        if account.plaid_account_id != "manual-local"
        and account.mask == data["mask"]
        and account.type == data["type"]
        and account.subtype == data.get("subtype")
        and (account.official_name or account.name).strip().casefold() == label
    ]
    return candidates[0] if len(candidates) == 1 else None


def _apply_account_data(account: Account, item_id: int, data: dict) -> None:
    account.item_id = item_id
    account.plaid_account_id = data["plaid_account_id"]
    for field in _ACCOUNT_FIELDS:
        setattr(account, field, data.get(field))


@router.post("/plaid/link-token")
def link_token():
    client = get_client()
    try:
        return {"link_token": create_link_token(client)}
    except Exception as exc:  # noqa: BLE001 — surface Plaid configuration errors
        raise HTTPException(status_code=502, detail=f"Plaid Link setup failed: {exc}") from exc


@router.post("/plaid/exchange")
def exchange(body: ExchangeRequest, session: Session = Depends(get_session)):
    client = get_client()
    result = exchange_public_token(client, body.public_token)
    item = session.exec(
        select(PlaidItem).where(PlaidItem.plaid_item_id == result["item_id"])
    ).first()
    if item:
        item.access_token = result["access_token"]
    else:
        item = PlaidItem(plaid_item_id=result["item_id"], access_token=result["access_token"])
        session.add(item)
    session.flush()
    session.refresh(item)

    added = 0
    replaced_item_ids: set[int] = set()
    for data in fetch_accounts(client, result["access_token"]):
        existing = session.exec(
            select(Account).where(Account.plaid_account_id == data["plaid_account_id"])
        ).first()
        if not existing:
            existing = _relink_match(session, data)
        if existing:
            if existing.item_id != item.id:
                replaced_item_ids.add(existing.item_id)
            _apply_account_data(existing, item.id, data)
            session.add(existing)
        else:
            session.add(Account(item_id=item.id, **data))
            added += 1

    session.flush()
    for old_item_id in replaced_item_ids:
        has_accounts = session.exec(
            select(Account).where(Account.item_id == old_item_id)
        ).first()
        if not has_accounts:
            old_item = session.get(PlaidItem, old_item_id)
            if old_item:
                session.delete(old_item)
    session.commit()
    record_financial_goal_snapshots(session)
    return {"item_id": item.plaid_item_id, "accounts": added}


@router.post("/plaid/refresh")
def refresh(session: Session = Depends(get_session)):
    """Ask Plaid to re-pull every linked bank now. Plaid fetches asynchronously —
    follow up with /plaid/sync a few seconds later to ingest whatever arrived."""
    items = [item for item in session.exec(select(PlaidItem)).all() if item.access_token]
    if not items:
        raise HTTPException(status_code=400, detail="No bank is linked yet")
    client = get_client()
    try:
        for item in items:
            refresh_transactions(client, item.access_token)
    except Exception as exc:  # noqa: BLE001 — surface Plaid's reason (e.g. product not enabled)
        raise HTTPException(status_code=502, detail=f"Plaid refresh failed: {exc}")
    return {"requested": len(items)}


@router.post("/plaid/sync")
def sync(session: Session = Depends(get_session)):
    client = get_client()
    totals = {"added": 0, "modified": 0, "removed": 0}
    for item in session.exec(select(PlaidItem)).all():
        if not item.access_token:  # local/manual account; never send it to Plaid
            continue
        for data in fetch_accounts(client, item.access_token):
            account = session.exec(
                select(Account).where(Account.plaid_account_id == data["plaid_account_id"])
            ).first()
            if not account:
                account = Account(item_id=item.id, **data)
            else:
                _apply_account_data(account, item.id, data)
            session.add(account)
        session.commit()
        counts = sync_item(session, item, client)
        for k in totals:
            totals[k] += counts[k]
    record_financial_goal_snapshots(session)
    return totals
