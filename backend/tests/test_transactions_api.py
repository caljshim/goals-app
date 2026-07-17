from datetime import date

from app.budget.models import Account, PlaidItem, Transaction


def _seed_account(session):
    item = PlaidItem(plaid_item_id="i1", access_token="t")
    session.add(item); session.commit(); session.refresh(item)
    acc = Account(plaid_account_id="a1", item_id=item.id, name="Checking", type="depository")
    session.add(acc); session.commit(); session.refresh(acc)
    return acc


def test_create_list_recategorize_delete(client, session):
    acc = _seed_account(session)

    # manual create
    resp = client.post("/api/transactions", json={
        "account_id": acc.id, "date": "2026-07-01", "name": "Cash lunch", "amount": 12.5,
    })
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["effective_category"] == "UNCATEGORIZED"
    assert resp.json()["is_manual"] is True

    # list
    resp = client.get("/api/transactions")
    assert len(resp.json()) == 1

    # recategorize
    resp = client.patch(f"/api/transactions/{tid}", json={"user_category": "DINING"})
    assert resp.status_code == 200
    assert resp.json()["effective_category"] == "DINING"

    # delete manual ok
    resp = client.delete(f"/api/transactions/{tid}")
    assert resp.status_code == 204
    assert client.get("/api/transactions").json() == []


def test_cannot_delete_plaid_transaction(client, session):
    acc = _seed_account(session)
    session.add(Transaction(plaid_transaction_id="p1", account_id=acc.id,
                            date=date(2026, 7, 1), name="Coffee", amount=4.0))
    session.commit()
    row = client.get("/api/transactions").json()[0]
    assert row["is_manual"] is False
    resp = client.delete(f"/api/transactions/{row['id']}")
    assert resp.status_code == 400


def test_category_filter_uses_effective(client, session):
    acc = _seed_account(session)
    session.add(Transaction(account_id=acc.id, date=date(2026, 7, 1), name="A",
                            amount=1.0, category="GROCERIES"))
    session.add(Transaction(account_id=acc.id, date=date(2026, 7, 1), name="B",
                            amount=1.0, category="GROCERIES", user_category="DINING"))
    session.commit()
    resp = client.get("/api/transactions?category=DINING")
    names = [t["name"] for t in resp.json()]
    assert names == ["B"]
