import threading
from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.budget import plaid_client
from app.budget.models import Account, PlaidItem, Transaction
from app.budget.services import sync as sync_service


def _seed(engine) -> int:
    with Session(engine) as s:
        item = PlaidItem(plaid_item_id="item_1", access_token="tok")
        s.add(item); s.commit(); s.refresh(item)
        s.add(Account(plaid_account_id="a1", item_id=item.id, name="Checking", type="depository"))
        s.commit()
        return item.id


def test_concurrent_syncs_do_not_crash_or_duplicate(tmp_path, monkeypatch):
    """Two overlapping /plaid/sync requests (auto-sync + a manual button) run in
    FastAPI's threadpool on separate SQLite connections and both ingest the same
    Plaid transaction. Without serialization, _upsert's check-then-insert races and
    the loser hits `UNIQUE constraint failed: transaction.plaid_transaction_id` on
    autoflush. The sync must instead be idempotent: no crash, exactly one row."""
    # File DB with default pooling => each thread's Session gets its own connection,
    # exactly like production db.py (StaticPool in-memory would hide the race).
    db = tmp_path / "concurrent.db"
    engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    item_id = _seed(engine)

    # Force both threads into the critical section together so the race is reliable.
    # Once serialized, the second thread can never reach the barrier, so the first
    # times out and proceeds — the barrier just widens the race window when unfixed.
    barrier = threading.Barrier(2, timeout=1.5)

    def fake_sync(client, access_token, cursor):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return {
            "added": [{
                "plaid_transaction_id": "t1", "plaid_account_id": "a1", "date": date(2026, 7, 16),
                "name": "PAYMENT TO CHASE CARD", "merchant_name": None, "amount": 91.93,
                "category": "LOAN_PAYMENTS", "pending": True,
            }],
            "modified": [], "removed": [], "next_cursor": "C1", "has_more": False,
        }

    monkeypatch.setattr(plaid_client, "sync_transactions", fake_sync)

    errors: list[Exception] = []

    def run():
        try:
            with Session(engine) as s:
                item = s.get(PlaidItem, item_id)
                sync_service.sync_item(s, item, client=None)
        except Exception as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    t1 = threading.Thread(target=run)
    t2 = threading.Thread(target=run)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == [], f"concurrent sync raised: {errors!r}"
    with Session(engine) as s:
        rows = s.exec(select(Transaction)).all()
    assert len(rows) == 1
    assert rows[0].plaid_transaction_id == "t1"
