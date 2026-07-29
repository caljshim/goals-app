import json

from fastapi import APIRouter, Depends, HTTPException
from plaid.exceptions import ApiException
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
from app.budget.services.sync import reconcile_item_duplicates, sync_item
from app.perf import timed

router = APIRouter(prefix="/api", tags=["plaid"])

_ACCOUNT_FIELDS = (
    "persistent_account_id", "name", "official_name", "type", "subtype", "mask",
    "current_balance", "available_balance", "currency",
)
_TEMPORARY_REFRESH_CODES = {
    "INSTITUTION_DOWN",
    "INSTITUTION_NOT_AVAILABLE",
    "INSTITUTION_NOT_RESPONDING",
    "RATE_LIMIT_EXCEEDED",
}


def _plaid_error_code(exc: ApiException) -> str | None:
    """Extract Plaid's safe error code without returning credentials or tokens."""
    try:
        body = exc.body.decode() if isinstance(exc.body, bytes) else exc.body
        payload = json.loads(body or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    code = payload.get("error_code")
    return code if isinstance(code, str) else None


def _relink_match(session: Session, data: dict) -> Account | None:
    """Find one existing local account that represents a newly re-linked account.

    Plaid account IDs are stable within an Item, but linking the same institution as a
    new Item creates new IDs. A masked account signature lets us preserve local history
    without merging ambiguous or unmasked accounts.
    """
    persistent_id = data.get("persistent_account_id")
    if persistent_id:
        persistent_match = session.exec(
            select(Account).where(Account.persistent_account_id == persistent_id)
        ).first()
        if persistent_match:
            return persistent_match

    if not data.get("mask"):
        return None
    candidates = [
        account for account in session.exec(select(Account)).all()
        if account.plaid_account_id != "manual-local"
        and account.mask == data["mask"]
        and account.type == data["type"]
        and account.subtype == data.get("subtype")
        and account.currency == data.get("currency", "USD")
    ]
    return candidates[0] if len(candidates) == 1 else None


def _apply_account_data(account: Account, item_id: int, data: dict) -> None:
    account.item_id = item_id
    account.plaid_account_id = data["plaid_account_id"]
    for field in _ACCOUNT_FIELDS:
        setattr(account, field, data.get(field))


@router.post("/plaid/link-token")
def link_token(item_id: int | None = None, session: Session = Depends(get_session)):
    client = get_client()
    try:
        access_token = None
        if item_id is not None:
            item = session.get(PlaidItem, item_id)
            if item is None or not item.access_token:
                raise HTTPException(status_code=404, detail="Linked bank was not found")
            access_token = item.access_token
        token = (
            create_link_token(client, access_token=access_token)
            if access_token
            else create_link_token(client)
        )
        return {"link_token": token}
    except HTTPException:
        raise
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
    accepted = 0
    temporarily_unavailable = 0
    for item in items:
        try:
            refresh_transactions(client, item.access_token)
            accepted += 1
        except ApiException as exc:
            if _plaid_error_code(exc) in _TEMPORARY_REFRESH_CODES:
                temporarily_unavailable += 1
                continue
            raise HTTPException(
                status_code=502, detail=f"Plaid refresh failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — surface unexpected configuration errors
            raise HTTPException(
                status_code=502, detail=f"Plaid refresh failed: {exc}"
            ) from exc
    return {
        "requested": len(items),
        "accepted": accepted,
        "temporarily_unavailable": temporarily_unavailable,
    }


@router.post("/plaid/sync")
def sync(session: Session = Depends(get_session)):
    with timed("plaid.sync.endpoint"):
        return _sync(session)


def _sync(session: Session):
    client = get_client()
    totals = {"added": 0, "modified": 0, "removed": 0, "deduplicated": 0}
    for item in session.exec(select(PlaidItem)).all():
        if not item.access_token:  # local/manual account; never send it to Plaid
            continue
        for data in fetch_accounts(client, item.access_token):
            account = session.exec(
                select(Account).where(Account.plaid_account_id == data["plaid_account_id"])
            ).first()
            if not account:
                account = _relink_match(session, data)
            if not account:
                account = Account(item_id=item.id, **data)
            else:
                _apply_account_data(account, item.id, data)
            session.add(account)
        session.commit()
        counts = sync_item(session, item, client)
        for k in totals:
            if k in counts:
                totals[k] += counts[k]
        session.refresh(item)
        if item.reconciliation_version < 1:
            totals["deduplicated"] += reconcile_item_duplicates(session, item, client)
    record_financial_goal_snapshots(session)
    return totals
