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
    # sync_item lives in services.sync and calls plaid_client.sync_transactions
    from app.budget import plaid_client as pc
    monkeypatch.setattr(pc, "sync_transactions", fake_sync_transactions)

    resp = client.post("/api/plaid/sync")
    assert resp.status_code == 200
    assert resp.json()["added"] == 1
    assert session.exec(select(Transaction)).one().name == "Coffee"
