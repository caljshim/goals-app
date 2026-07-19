from datetime import date

from sqlmodel import select

from app.budget.models import Account, PlaidItem, Transaction
from app.budget.routers import plaid as plaid_router


def test_link_token(client, monkeypatch):
    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "create_link_token", lambda c: "link-sandbox-123")
    resp = client.post("/api/plaid/link-token")
    assert resp.status_code == 200
    assert resp.json() == {"link_token": "link-sandbox-123"}


def test_exchange_creates_item_and_accounts(client, session, monkeypatch):
    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "exchange_public_token",
                        lambda c, pt: {"access_token": "acc-tok", "item_id": "item_1"})
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [
        {"plaid_account_id": "a1", "name": "Checking", "official_name": None,
         "type": "depository", "subtype": "checking", "mask": "0000",
         "current_balance": 100.0, "available_balance": 90.0, "currency": "USD"},
    ])
    resp = client.post("/api/plaid/exchange", json={"public_token": "public-tok"})
    assert resp.status_code == 200
    assert resp.json() == {"item_id": "item_1", "accounts": 1}
    assert session.exec(select(PlaidItem)).one().plaid_item_id == "item_1"
    assert session.exec(select(Account)).one().name == "Checking"


def test_exchange_is_idempotent_on_plaid_item_id(client, session, monkeypatch):
    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "exchange_public_token",
                        lambda c, pt: {"access_token": "acc-tok", "item_id": "item_1"})
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [
        {"plaid_account_id": "a1", "name": "Checking", "official_name": None,
         "type": "depository", "subtype": "checking", "mask": "0000",
         "current_balance": 100.0, "available_balance": 90.0, "currency": "USD"},
    ])

    resp1 = client.post("/api/plaid/exchange", json={"public_token": "public-tok"})
    assert resp1.status_code == 200
    assert resp1.json() == {"item_id": "item_1", "accounts": 1}

    resp2 = client.post("/api/plaid/exchange", json={"public_token": "public-tok"})
    assert resp2.status_code == 200
    assert resp2.json() == {"item_id": "item_1", "accounts": 0}

    assert len(session.exec(select(PlaidItem)).all()) == 1


def test_exchange_relinks_matching_accounts_without_duplicates(client, session, monkeypatch):
    old_item = PlaidItem(plaid_item_id="old_item", access_token="old-token")
    session.add(old_item); session.commit(); session.refresh(old_item)
    old_account = Account(
        plaid_account_id="old-account-id", item_id=old_item.id, name="Checking",
        official_name="Total Checking", type="depository", subtype="checking",
        mask="0992", current_balance=90.0,
    )
    session.add(old_account); session.commit(); session.refresh(old_account)

    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(
        plaid_router, "exchange_public_token",
        lambda c, pt: {"access_token": "new-token", "item_id": "new_item"},
    )
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [{
        "plaid_account_id": "new-account-id", "name": "Checking",
        "official_name": "Total Checking", "type": "depository",
        "subtype": "checking", "mask": "0992", "current_balance": 125.0,
        "available_balance": 120.0, "currency": "USD",
    }])

    response = client.post("/api/plaid/exchange", json={"public_token": "public-tok"})

    assert response.status_code == 200
    assert response.json() == {"item_id": "new_item", "accounts": 0}
    session.expire_all()
    accounts = session.exec(select(Account)).all()
    assert len(accounts) == 1
    assert accounts[0].id == old_account.id
    assert accounts[0].plaid_account_id == "new-account-id"
    assert accounts[0].current_balance == 125.0
    assert [item.plaid_item_id for item in session.exec(select(PlaidItem)).all()] == ["new_item"]


def test_refresh_requests_replay_for_each_item(client, session, monkeypatch):
    session.add(PlaidItem(plaid_item_id="item_1", access_token="tok-1"))
    session.add(PlaidItem(plaid_item_id="item_2", access_token="tok-2"))
    session.commit()

    refreshed = []
    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "refresh_transactions",
                        lambda c, tok: refreshed.append(tok))

    resp = client.post("/api/plaid/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"requested": 2}
    assert refreshed == ["tok-1", "tok-2"]


def test_refresh_without_linked_bank_is_400(client):
    resp = client.post("/api/plaid/refresh")
    assert resp.status_code == 400


def test_refresh_surfaces_plaid_error_as_502(client, session, monkeypatch):
    session.add(PlaidItem(plaid_item_id="item_1", access_token="tok-1"))
    session.commit()

    def boom(c, tok):
        raise RuntimeError("PRODUCT_NOT_READY")

    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "refresh_transactions", boom)

    resp = client.post("/api/plaid/refresh")
    assert resp.status_code == 502
    assert "PRODUCT_NOT_READY" in resp.json()["detail"]


def test_sync_endpoint(client, session, monkeypatch):
    item = PlaidItem(plaid_item_id="item_1", access_token="acc-tok")
    session.add(item); session.commit(); session.refresh(item)
    session.add(Account(plaid_account_id="a1", item_id=item.id, name="Checking", type="depository"))
    session.commit()

    def fake_sync_transactions(clientobj, access_token, cursor):
        return {"added": [{
            "plaid_transaction_id": "t1", "plaid_account_id": "a1", "date": date(2026, 7, 1),
            "name": "Coffee", "merchant_name": "Cafe", "amount": 4.5,
            "category": "FOOD_AND_DRINK", "pending": False,
        }], "modified": [], "removed": [], "next_cursor": "C1", "has_more": False}

    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [{
        "plaid_account_id": "a1", "name": "Checking", "official_name": None,
        "type": "depository", "subtype": "checking", "mask": "0000",
        "current_balance": 125.0, "available_balance": 120.0, "currency": "USD",
    }])
    # sync_item lives in services.sync and calls plaid_client.sync_transactions
    from app.budget import plaid_client as pc
    monkeypatch.setattr(pc, "sync_transactions", fake_sync_transactions)

    resp = client.post("/api/plaid/sync")
    assert resp.status_code == 200
    assert resp.json()["added"] == 1
    assert session.exec(select(Transaction)).one().name == "Coffee"


def test_initial_sync_reconciles_relinked_transactions(client, session, monkeypatch):
    item = PlaidItem(plaid_item_id="new_item", access_token="new-token")
    session.add(item); session.commit(); session.refresh(item)
    account = Account(
        plaid_account_id="new-account-id", item_id=item.id, name="Checking",
        type="depository", subtype="checking", mask="0992",
    )
    session.add(account); session.commit(); session.refresh(account)
    old_transaction = Transaction(
        plaid_transaction_id="old-txn-id", account_id=account.id,
        date=date(2026, 7, 1), name="Coffee", merchant_name="Cafe",
        amount=4.5, category="FOOD_AND_DRINK", pending=False,
        user_category="EATING_OUT",
    )
    session.add(old_transaction); session.commit(); session.refresh(old_transaction)

    def fake_sync_transactions(clientobj, access_token, cursor):
        return {"added": [{
            "plaid_transaction_id": "new-txn-id", "plaid_account_id": "new-account-id",
            "date": date(2026, 7, 1), "name": "Coffee", "merchant_name": "Cafe",
            "amount": 4.5, "category": "FOOD_AND_DRINK", "pending": False,
        }], "modified": [], "removed": [], "next_cursor": "C1", "has_more": False}

    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [{
        "plaid_account_id": "new-account-id", "name": "Checking", "official_name": None,
        "type": "depository", "subtype": "checking", "mask": "0992",
        "current_balance": 125.0, "available_balance": 120.0, "currency": "USD",
    }])
    from app.budget import plaid_client as pc
    monkeypatch.setattr(pc, "sync_transactions", fake_sync_transactions)

    response = client.post("/api/plaid/sync")

    assert response.status_code == 200
    session.expire_all()
    transactions = session.exec(select(Transaction)).all()
    assert len(transactions) == 1
    assert transactions[0].id == old_transaction.id
    assert transactions[0].plaid_transaction_id == "new-txn-id"
    assert transactions[0].user_category == "EATING_OUT"


def test_initial_sync_preserves_two_identical_new_transactions(client, session, monkeypatch):
    item = PlaidItem(plaid_item_id="item_1", access_token="token")
    session.add(item); session.commit(); session.refresh(item)
    account = Account(
        plaid_account_id="account_1", item_id=item.id, name="Checking",
        type="depository", subtype="checking", mask="0992",
    )
    session.add(account); session.commit()

    def transaction(transaction_id: str):
        return {
            "plaid_transaction_id": transaction_id, "plaid_account_id": "account_1",
            "date": date(2026, 7, 1), "name": "Coffee", "merchant_name": "Cafe",
            "amount": 4.5, "category": "FOOD_AND_DRINK", "pending": False,
        }

    monkeypatch.setattr(plaid_router, "get_client", lambda: object())
    monkeypatch.setattr(plaid_router, "fetch_accounts", lambda c, tok: [{
        "plaid_account_id": "account_1", "name": "Checking", "official_name": None,
        "type": "depository", "subtype": "checking", "mask": "0992",
        "current_balance": 125.0, "available_balance": 120.0, "currency": "USD",
    }])
    from app.budget import plaid_client as pc
    monkeypatch.setattr(pc, "sync_transactions", lambda clientobj, token, cursor: {
        "added": [transaction("txn-1"), transaction("txn-2")],
        "modified": [], "removed": [], "next_cursor": "C1", "has_more": False,
    })

    response = client.post("/api/plaid/sync")

    assert response.status_code == 200
    session.expire_all()
    rows = session.exec(select(Transaction)).all()
    assert len(rows) == 2
    assert {row.plaid_transaction_id for row in rows} == {"txn-1", "txn-2"}


def test_sync_ignores_manual_account_item(client, session, monkeypatch):
    session.add(PlaidItem(plaid_item_id="manual-local", access_token=""))
    session.commit()
    monkeypatch.setattr(plaid_router, "get_client", lambda: object())

    resp = client.post("/api/plaid/sync")

    assert resp.status_code == 200
    assert resp.json() == {"added": 0, "modified": 0, "removed": 0}
