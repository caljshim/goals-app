import logging
import threading

from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, select

from app.budget import plaid_client
from app.budget.models import Account, PlaidItem, Transaction
from app.perf import timed

logger = logging.getLogger("app.budget.sync")

# Syncs must not overlap. The frontend fires /plaid/sync from several unguarded
# places (the 15-min auto-sync, the "Refresh from bank" button, the Accounts
# "Sync transactions" button), and FastAPI runs the endpoint in a threadpool, so
# two syncs can run at once on separate PostgreSQL connections. _upsert's
# check-then-insert is not atomic across connections: both SELECT a new
# transaction, find nothing, and INSERT it, so the loser hits
# the unique plaid_transaction_id constraint (surfaced via autoflush). This app
# is a single process, so serialising sync runs closes the
# race — the waiting sync sees the committed rows and updates instead of
# re-inserting.
_sync_lock = threading.Lock()


def _account_map(session: Session, item_id: int) -> dict[str, int]:
    accounts = session.exec(select(Account).where(Account.item_id == item_id)).all()
    return {a.plaid_account_id: a.id for a in accounts}


def _natural_match(
    session: Session,
    account_id: int,
    data: dict,
    eligible_rows: set[int],
    claimed_rows: set[int],
) -> Transaction | None:
    """Match a transaction from an old Plaid Item during a relink's first sync."""
    candidates = session.exec(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.date == data["date"],
            Transaction.amount == data["amount"],
            Transaction.pending == data["pending"],
        )
    ).all()
    available = [
        row for row in candidates
        if row.id in eligible_rows and row.id not in claimed_rows
    ]

    # Plaid may replay the same posted transaction under a new transaction ID
    # after a relink while dropping merchant enrichment (merchant_name becomes
    # null and the category becomes OTHER). The raw statement name remains
    # stable in that case, so prefer it over the optional cleaned merchant.
    raw_name = _normalize_identity(data["name"])
    raw_match = next(
        (row for row in available if _normalize_identity(row.name) == raw_name),
        None,
    )
    if raw_match is not None:
        return raw_match

    # Plaid can also rewrite the raw description while retaining its cleaned
    # merchant. Keep that existing fallback, but only when both sides actually
    # have merchant data so generic/missing merchants cannot merge transactions.
    merchant = _normalize_identity(data["merchant_name"])
    if merchant:
        return next(
            (
                row for row in available
                if _normalize_identity(row.merchant_name) == merchant
            ),
            None,
        )
    return None


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _merchant_identity(name: str | None, merchant_name: str | None) -> str:
    return _normalize_identity(merchant_name or name)


def _natural_key(account_id: int, data: dict) -> tuple:
    return (
        account_id,
        data["date"],
        round(float(data["amount"]), 2),
        _merchant_identity(data["name"], data["merchant_name"]),
        bool(data["pending"]),
    )


def _row_key(row: Transaction) -> tuple:
    return (
        row.account_id,
        row.date,
        round(float(row.amount), 2),
        _merchant_identity(row.name, row.merchant_name),
        bool(row.pending),
    )


def _deduplicate_account_transactions(
    session: Session,
    account_ids: set[int],
) -> int:
    """Collapse duplicate Plaid rows with the same bank-statement fingerprint.

    Plaid can assign new transaction IDs after an Item is linked again. Those
    IDs are not sufficient to distinguish the replayed copy from the original,
    so use account, posting date, amount, merchant, and pending state. Manual
    transactions are excluded because two identical manual entries may be
    intentional.
    """
    if not account_ids:
        return 0

    rows = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(account_ids),
            Transaction.plaid_transaction_id.is_not(None),
        )
    ).all()
    rows_by_key: dict[tuple, list[Transaction]] = {}
    for row in rows:
        rows_by_key.setdefault(_row_key(row), []).append(row)

    referenced_ids = {
        row.reimburses_transaction_id
        for row in rows
        if row.reimburses_transaction_id is not None
    }
    replacements: dict[int, int] = {}
    duplicate_rows: list[Transaction] = []

    for matches in rows_by_key.values():
        if len(matches) < 2:
            continue
        # Preserve user work first, then prefer the oldest local row. Relinks
        # generally created the newer copy.
        keeper = max(
            matches,
            key=lambda row: (
                row.user_category is not None,
                row.id in referenced_ids,
                row.reimburses_transaction_id is not None,
                -(row.id or 0),
            ),
        )
        for row in matches:
            if row.id == keeper.id:
                continue
            if keeper.user_category is None and row.user_category is not None:
                keeper.user_category = row.user_category
            if (
                keeper.reimburses_transaction_id is None
                and row.reimburses_transaction_id is not None
            ):
                keeper.reimburses_transaction_id = row.reimburses_transaction_id
            replacements[row.id] = keeper.id
            duplicate_rows.append(row)
        session.add(keeper)

    if not replacements:
        return 0

    for row in rows:
        replacement = replacements.get(row.reimburses_transaction_id)
        if replacement is not None:
            row.reimburses_transaction_id = replacement
            session.add(row)
    for row in duplicate_rows:
        session.delete(row)
    session.flush()
    return len(duplicate_rows)


def _upsert(
    session: Session,
    acct_map: dict[str, int],
    data: dict,
    existing_by_pid: dict[str, Transaction],
    *,
    reconcile_existing: bool = False,
    eligible_rows: set[int] | None = None,
    claimed_rows: set[int] | None = None,
) -> bool:
    local_account_id = acct_map.get(data["plaid_account_id"])
    if local_account_id is None:
        return False
    pid = data["plaid_transaction_id"]
    existing = existing_by_pid.get(pid)
    eligible_rows = eligible_rows if eligible_rows is not None else set()
    claimed_rows = claimed_rows if claimed_rows is not None else set()
    if not existing and reconcile_existing:
        existing = _natural_match(
            session, local_account_id, data, eligible_rows, claimed_rows
        )
    row = existing or Transaction(plaid_transaction_id=pid, account_id=local_account_id)
    row.plaid_transaction_id = pid
    row.account_id = local_account_id
    row.date = data["date"]
    row.name = data["name"]
    row.merchant_name = data["merchant_name"]
    row.amount = data["amount"]
    row.category = data["category"]
    row.pending = data["pending"]
    session.add(row)
    # Keep the index live so a later page that modifies this same transaction
    # finds the row we just staged instead of missing it and inserting a dupe.
    existing_by_pid[pid] = row
    if row.id is not None:
        claimed_rows.add(row.id)
    return True


def _existing_by_plaid_id(
    session: Session, account_ids: list[int]
) -> dict[str, Transaction]:
    """Load every Plaid-backed row for these accounts once, keyed by Plaid ID.

    Replaces a per-transaction SELECT in the sync loop (an N+1 that dominated the
    DB cost on large histories) with a single query.
    """
    if not account_ids:
        return {}
    rows = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(account_ids),
            Transaction.plaid_transaction_id.is_not(None),
        )
    ).all()
    return {row.plaid_transaction_id: row for row in rows}


def sync_item(session: Session, item: PlaidItem, client) -> dict:
    with _sync_lock, timed("sync.item", item=item.id):
        counts = {"added": 0, "modified": 0, "removed": 0, "deduplicated": 0}
        acct_map = _account_map(session, item.id)
        account_ids = list(acct_map.values())
        cursor = item.sync_cursor
        full_history_sync = cursor is None
        reconcile_existing = cursor is None
        eligible_rows = set()
        if reconcile_existing and account_ids:
            eligible_rows = set(session.exec(
                select(Transaction.id).where(Transaction.account_id.in_(account_ids))
            ).all())
        existing_by_pid = _existing_by_plaid_id(session, account_ids)
        claimed_rows: set[int] = set()
        pages = 0
        while True:
            page = plaid_client.sync_transactions(client, item.access_token, cursor)
            pages += 1
            for data in page["added"]:
                if _upsert(
                    session, acct_map, data, existing_by_pid,
                    reconcile_existing=reconcile_existing,
                    eligible_rows=eligible_rows,
                    claimed_rows=claimed_rows,
                ):
                    counts["added"] += 1
            for data in page["modified"]:
                if _upsert(session, acct_map, data, existing_by_pid):
                    counts["modified"] += 1
            for tid in page["removed"]:
                existing = existing_by_pid.pop(tid, None)
                if existing is not None:
                    if sa_inspect(existing).persistent:
                        session.delete(existing)
                    else:
                        # Added earlier in this same sync and never flushed; just
                        # drop the staged insert instead of deleting a phantom row.
                        session.expunge(existing)
                    counts["removed"] += 1
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        logger.info(
            "sync.item item=%s pages=%s added=%s modified=%s removed=%s",
            item.id, pages, counts["added"], counts["modified"], counts["removed"],
        )
        item.sync_cursor = cursor
        if full_history_sync:
            # The initial cursor replay plus _natural_match is the authoritative
            # reconciliation for a freshly linked/relinked Item.
            item.reconciliation_version = 1
        session.flush()
        counts["deduplicated"] = _deduplicate_account_transactions(
            session, set(acct_map.values())
        )
        session.add(item)
        session.commit()
    return counts


def reconcile_item_duplicates(session: Session, item: PlaidItem, client) -> int:
    """Remove stale transaction copies left by linking the same bank as a new Item.

    A cursor-less Transactions Sync replay is authoritative for the active Item.
    We first remove stale IDs when an otherwise-identical active transaction
    exists, then collapse any identical active rows Plaid retained after a relink.
    """
    with _sync_lock:
        account_map = _account_map(session, item.id)
        account_ids = set(account_map.values())
        if not account_ids:
            item.reconciliation_version = 1
            session.add(item)
            session.commit()
            return 0

        active: dict[str, dict] = {}
        cursor = None
        while True:
            page = plaid_client.sync_transactions(client, item.access_token, cursor)
            for data in [*page["added"], *page["modified"]]:
                if data["plaid_account_id"] in account_map:
                    active[data["plaid_transaction_id"]] = data
            for transaction_id in page["removed"]:
                active.pop(transaction_id, None)
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break

        active_ids_by_key: dict[tuple, set[str]] = {}
        for transaction_id, data in active.items():
            local_account_id = account_map.get(data["plaid_account_id"])
            if local_account_id is None:
                continue
            active_ids_by_key.setdefault(
                _natural_key(local_account_id, data), set()
            ).add(transaction_id)

        local_rows = session.exec(
            select(Transaction).where(
                Transaction.account_id.in_(account_ids),
                Transaction.plaid_transaction_id.is_not(None),
            )
        ).all()
        rows_by_key: dict[tuple, list[Transaction]] = {}
        for row in local_rows:
            rows_by_key.setdefault(_row_key(row), []).append(row)

        replacements: dict[int, int] = {}
        stale_rows: list[Transaction] = []
        for key, rows in rows_by_key.items():
            current_ids = active_ids_by_key.get(key, set())
            if not current_ids:
                continue
            keepers = sorted(
                (row for row in rows if row.plaid_transaction_id in current_ids),
                key=lambda row: row.id,
            )
            stale = sorted(
                (row for row in rows if row.plaid_transaction_id not in current_ids),
                key=lambda row: row.id,
            )
            if not keepers:
                continue
            for index, row in enumerate(stale):
                keeper = keepers[index % len(keepers)]
                replacements[row.id] = keeper.id
                if keeper.user_category is None and row.user_category is not None:
                    keeper.user_category = row.user_category
                if (
                    keeper.reimburses_transaction_id is None
                    and row.reimburses_transaction_id is not None
                ):
                    keeper.reimburses_transaction_id = row.reimburses_transaction_id
                session.add(keeper)
                stale_rows.append(row)

        if replacements:
            for row in local_rows:
                replacement = replacements.get(row.reimburses_transaction_id)
                if replacement is not None:
                    row.reimburses_transaction_id = replacement
                    session.add(row)
            for row in stale_rows:
                session.delete(row)

        session.flush()
        duplicate_count = _deduplicate_account_transactions(session, account_ids)
        item.reconciliation_version = 1
        session.add(item)
        session.commit()
        return len(stale_rows) + duplicate_count
