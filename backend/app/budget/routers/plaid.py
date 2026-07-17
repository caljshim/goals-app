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
from app.budget.services.sync import sync_item

router = APIRouter(prefix="/api", tags=["plaid"])


@router.post("/plaid/link-token")
def link_token():
    client = get_client()
    return {"link_token": create_link_token(client)}


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
    for data in fetch_accounts(client, result["access_token"]):
        existing = session.exec(
            select(Account).where(Account.plaid_account_id == data["plaid_account_id"])
        ).first()
        if existing:
            continue
        session.add(Account(item_id=item.id, **data))
        added += 1
    session.commit()
    return {"item_id": item.plaid_item_id, "accounts": added}


@router.post("/plaid/refresh")
def refresh(session: Session = Depends(get_session)):
    """Ask Plaid to re-pull every linked bank now. Plaid fetches asynchronously —
    follow up with /plaid/sync a few seconds later to ingest whatever arrived."""
    items = session.exec(select(PlaidItem)).all()
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
        counts = sync_item(session, item, client)
        for k in totals:
            totals[k] += counts[k]
    return totals
