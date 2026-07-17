from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.budget import plaid_client
from app.budget.models import Account, PlaidItem, Transaction
from app.budget.services.sync import sync_item


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


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

    assert counts == {"added": 2, "modified": 1, "removed": 1}
    rows = s.exec(select(Transaction)).all()
    assert {r.plaid_transaction_id for r in rows} == {"t1"}
    assert s.exec(select(Transaction)).first().amount == 5.0  # t1 modified
    s.refresh(item)
    assert item.sync_cursor == "C2"
