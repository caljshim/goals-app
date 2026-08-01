from datetime import date

from sqlmodel import select

from app.budget import plaid_client
from app.budget.models import Account, PlaidItem, Transaction
from app.budget.services.sync import reconcile_item_duplicates, sync_item
from tests.postgres import make_session


def _txn(tid, amount, category="FOOD_AND_DRINK"):
    return {
        "plaid_transaction_id": tid, "plaid_account_id": "acc_1", "date": date(2026, 7, 1),
        "name": "Coffee", "merchant_name": "Cafe", "amount": amount,
        "category": category, "pending": False,
    }


def test_sync_item_adds_modifies_removes_and_saves_cursor(monkeypatch):
    s = make_session()
    item = PlaidItem(plaid_item_id="item_1", access_token="tok")
    s.add(item); s.commit(); s.refresh(item)
    s.add(Account(plaid_account_id="acc_1", item_id=item.id, name="Checking", type="depository"))
    s.commit()

    pages = [
        {"added": [_txn("t1", 4.5), _txn("t2", 9.0)], "modified": [], "removed": [],
         "next_cursor": "C1", "has_more": True},
        {"added": [], "modified": [_txn("t1", 5.0)], "removed": ["t2"],
         "next_cursor": "C2", "has_more": False},
    ]
    calls = {"i": 0}

    def fake_sync(client, access_token, cursor):
        page = pages[calls["i"]]; calls["i"] += 1
        return page

    monkeypatch.setattr(plaid_client, "sync_transactions", fake_sync)

    counts = sync_item(s, item, client=None)

    assert counts == {
        "added": 2,
        "modified": 1,
        "removed": 1,
        "deduplicated": 0,
    }
    rows = s.exec(select(Transaction)).all()
    assert {r.plaid_transaction_id for r in rows} == {"t1"}
    assert s.exec(select(Transaction)).first().amount == 5.0  # t1 modified
    s.refresh(item)
    assert item.sync_cursor == "C2"
    assert item.reconciliation_version == 1


def test_incremental_sync_updates_preexisting_row_via_batched_index(monkeypatch):
    """A cursored (incremental) sync that modifies an already-stored transaction
    must update it in place, not insert a duplicate — the preloaded existence
    index has to find rows that predate this sync."""
    s = make_session()
    item = PlaidItem(plaid_item_id="item_1", access_token="tok", sync_cursor="C0")
    s.add(item); s.commit(); s.refresh(item)
    s.add(Account(plaid_account_id="acc_1", item_id=item.id, name="Checking", type="depository"))
    s.commit()
    s.add(Transaction(
        plaid_transaction_id="t1", account_id=1, date=date(2026, 7, 1),
        name="Coffee", merchant_name="Cafe", amount=4.5,
        category="FOOD_AND_DRINK", pending=False,
    ))
    s.commit()

    monkeypatch.setattr(plaid_client, "sync_transactions", lambda client, token, cursor: {
        "added": [], "modified": [_txn("t1", 6.25)], "removed": [],
        "next_cursor": "C1", "has_more": False,
    })

    counts = sync_item(s, item, client=None)

    assert counts["modified"] == 1
    rows = s.exec(select(Transaction)).all()
    assert len(rows) == 1  # updated in place, no duplicate inserted
    assert rows[0].amount == 6.25


def test_initial_relink_matches_raw_name_when_merchant_enrichment_disappears(monkeypatch):
    s = make_session()
    item = PlaidItem(plaid_item_id="item_1", access_token="tok")
    s.add(item); s.commit(); s.refresh(item)
    account = Account(
        plaid_account_id="acc_1",
        item_id=item.id,
        name="Credit card",
        type="credit",
    )
    s.add(account); s.commit(); s.refresh(account)
    original = Transaction(
        plaid_transaction_id="old-item-transaction",
        account_id=account.id,
        date=date(2026, 7, 1),
        name="APF*M M Property Managem",
        merchant_name="M M Property Management",
        amount=1282.22,
        category="GENERAL_SERVICES",
        pending=False,
        user_category="RENT_AND_UTILITIES",
    )
    s.add(original); s.commit(); s.refresh(original)

    replay = {
        "plaid_transaction_id": "new-item-transaction",
        "plaid_account_id": "acc_1",
        "date": date(2026, 7, 1),
        "name": "APF*M M Property Managem",
        "merchant_name": None,
        "amount": 1282.22,
        "category": "OTHER",
        "pending": False,
    }
    monkeypatch.setattr(plaid_client, "sync_transactions", lambda client, token, cursor: {
        "added": [replay],
        "modified": [],
        "removed": [],
        "next_cursor": "end",
        "has_more": False,
    })

    counts = sync_item(s, item, client=None)

    rows = s.exec(select(Transaction)).all()
    assert counts["added"] == 1
    assert counts["deduplicated"] == 0
    assert len(rows) == 1
    assert rows[0].id == original.id
    assert rows[0].plaid_transaction_id == "new-item-transaction"
    assert rows[0].user_category == "RENT_AND_UTILITIES"


def test_initial_relink_does_not_merge_distinct_same_amount_transactions(monkeypatch):
    s = make_session()
    item = PlaidItem(plaid_item_id="item_1", access_token="tok")
    s.add(item); s.commit(); s.refresh(item)
    account = Account(
        plaid_account_id="acc_1",
        item_id=item.id,
        name="Checking",
        type="depository",
    )
    s.add(account); s.commit(); s.refresh(account)
    s.add_all([
        Transaction(
            plaid_transaction_id=f"old-{index}",
            account_id=account.id,
            date=date(2026, 7, 1),
            name=name,
            merchant_name=None,
            amount=-27.0,
            category="TRANSFER_IN",
            pending=False,
        )
        for index, name in enumerate(("Zelle payment from Ryan", "Zelle payment from Rohit"))
    ])
    s.commit()

    replays = [
        {
            "plaid_transaction_id": f"new-{index}",
            "plaid_account_id": "acc_1",
            "date": date(2026, 7, 1),
            "name": name,
            "merchant_name": None,
            "amount": -27.0,
            "category": "TRANSFER_IN",
            "pending": False,
        }
        for index, name in enumerate(("Zelle payment from Ryan", "Zelle payment from Rohit"))
    ]
    monkeypatch.setattr(plaid_client, "sync_transactions", lambda client, token, cursor: {
        "added": replays,
        "modified": [],
        "removed": [],
        "next_cursor": "end",
        "has_more": False,
    })

    sync_item(s, item, client=None)

    rows = s.exec(select(Transaction)).all()
    assert len(rows) == 2
    assert {row.plaid_transaction_id for row in rows} == {"new-0", "new-1"}
    assert {row.name for row in rows} == {
        "Zelle payment from Ryan",
        "Zelle payment from Rohit",
    }


def test_authoritative_reconciliation_removes_only_stale_relink_copies(monkeypatch):
    s = make_session()
    item = PlaidItem(
        plaid_item_id="item_1",
        access_token="tok",
        sync_cursor="existing-cursor",
    )
    s.add(item); s.commit(); s.refresh(item)
    account = Account(
        plaid_account_id="acc_1",
        item_id=item.id,
        name="Checking",
        type="depository",
    )
    s.add(account); s.commit(); s.refresh(account)

    current = Transaction(
        plaid_transaction_id="current-1",
        account_id=account.id,
        date=date(2026, 7, 1),
        name="Coffee",
        merchant_name="Cafe",
        amount=4.5,
        category="FOOD_AND_DRINK",
        pending=False,
    )
    stale = Transaction(
        plaid_transaction_id="old-item-1",
        account_id=account.id,
        date=date(2026, 7, 1),
        name="Coffee",
        merchant_name="Cafe",
        amount=4.5,
        category="FOOD_AND_DRINK",
        user_category="EATING_OUT",
        pending=False,
    )
    s.add_all([current, stale]); s.commit(); s.refresh(current); s.refresh(stale)
    reimbursement = Transaction(
        plaid_transaction_id="reimbursement",
        account_id=account.id,
        date=date(2026, 7, 2),
        name="Zelle from Sam",
        amount=-4.5,
        category="TRANSFER_IN",
        reimburses_transaction_id=stale.id,
        pending=False,
    )
    s.add(reimbursement); s.commit(); s.refresh(reimbursement)

    current_data = _txn("current-1", 4.5)
    # Plaid can change the raw description across Items while retaining the
    # cleaned merchant. Reconciliation should use the stable merchant identity.
    current_data["name"] = "CAFE PURCHASE 07/01"
    reimbursement_data = {
        "plaid_transaction_id": "reimbursement",
        "plaid_account_id": "acc_1",
        "date": date(2026, 7, 2),
        "name": "Zelle from Sam",
        "merchant_name": None,
        "amount": -4.5,
        "category": "TRANSFER_IN",
        "pending": False,
    }
    monkeypatch.setattr(plaid_client, "sync_transactions", lambda client, token, cursor: {
        "added": [current_data, reimbursement_data],
        "modified": [],
        "removed": [],
        "next_cursor": "authoritative-end",
        "has_more": False,
    })

    removed = reconcile_item_duplicates(s, item, client=None)

    assert removed == 1
    rows = s.exec(select(Transaction)).all()
    assert {row.plaid_transaction_id for row in rows} == {
        "current-1",
        "reimbursement",
    }
    retained = next(row for row in rows if row.plaid_transaction_id == "current-1")
    linked = next(row for row in rows if row.plaid_transaction_id == "reimbursement")
    assert retained.user_category == "EATING_OUT"
    assert linked.reimburses_transaction_id == retained.id
    s.refresh(item)
    assert item.reconciliation_version == 1


def test_authoritative_reconciliation_collapses_two_current_identical_relink_rows(
    monkeypatch,
):
    s = make_session()
    item = PlaidItem(plaid_item_id="item_1", access_token="tok")
    s.add(item); s.commit(); s.refresh(item)
    account = Account(
        plaid_account_id="acc_1",
        item_id=item.id,
        name="Checking",
        type="depository",
    )
    s.add(account); s.commit(); s.refresh(account)
    s.add_all([
        Transaction(
            plaid_transaction_id=transaction_id,
            account_id=account.id,
            date=date(2026, 7, 1),
            name="Coffee",
            merchant_name="Cafe",
            amount=4.5,
            category="FOOD_AND_DRINK",
            pending=False,
        )
        for transaction_id in ("current-1", "current-2")
    ])
    s.commit()
    monkeypatch.setattr(plaid_client, "sync_transactions", lambda client, token, cursor: {
        "added": [_txn("current-1", 4.5), _txn("current-2", 4.5)],
        "modified": [],
        "removed": [],
        "next_cursor": "end",
        "has_more": False,
    })

    removed = reconcile_item_duplicates(s, item, client=None)

    assert removed == 1
    rows = s.exec(select(Transaction)).all()
    assert len(rows) == 1
    assert rows[0].plaid_transaction_id == "current-1"
