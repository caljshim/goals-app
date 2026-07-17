from sqlmodel import Session, select

from app.budget import plaid_client
from app.budget.models import Account, PlaidItem, Transaction


def _account_map(session: Session, item_id: int) -> dict[str, int]:
    accounts = session.exec(select(Account).where(Account.item_id == item_id)).all()
    return {a.plaid_account_id: a.id for a in accounts}


def _upsert(session: Session, acct_map: dict[str, int], data: dict) -> bool:
    local_account_id = acct_map.get(data["plaid_account_id"])
    if local_account_id is None:
        return False
    existing = session.exec(
        select(Transaction).where(Transaction.plaid_transaction_id == data["plaid_transaction_id"])
    ).first()
    row = existing or Transaction(plaid_transaction_id=data["plaid_transaction_id"], account_id=local_account_id)
    row.account_id = local_account_id
    row.date = data["date"]
    row.name = data["name"]
    row.merchant_name = data["merchant_name"]
    row.amount = data["amount"]
    row.category = data["category"]
    row.pending = data["pending"]
    session.add(row)
    return True


def sync_item(session: Session, item: PlaidItem, client) -> dict:
    counts = {"added": 0, "modified": 0, "removed": 0}
    acct_map = _account_map(session, item.id)
    cursor = item.sync_cursor
    while True:
        page = plaid_client.sync_transactions(client, item.access_token, cursor)
        for data in page["added"]:
            if _upsert(session, acct_map, data):
                counts["added"] += 1
        for data in page["modified"]:
            if _upsert(session, acct_map, data):
                counts["modified"] += 1
        for tid in page["removed"]:
            existing = session.exec(
                select(Transaction).where(Transaction.plaid_transaction_id == tid)
            ).first()
            if existing:
                session.delete(existing)
                counts["removed"] += 1
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    item.sync_cursor = cursor
    session.add(item)
    session.commit()
    return counts
