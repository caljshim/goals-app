from datetime import date

from app.budget.models import Account, PlaidItem, Transaction


def _seed_account(session):
    item = PlaidItem(plaid_item_id="i1", access_token="t")
    session.add(item); session.commit(); session.refresh(item)
    acc = Account(plaid_account_id="a1", item_id=item.id, name="Checking", type="depository")
    session.add(acc); session.commit(); session.refresh(acc)
    return acc


def _mk(session, acc, **kw):
    t = Transaction(account_id=acc.id, **kw)
    session.add(t); session.commit(); session.refresh(t)
    return t


def test_set_rule_from_transaction_recategorizes_by_merchant(client, session):
    acc = _seed_account(session)
    t = _mk(session, acc, date=date(2026, 7, 1), name="SAFEWAY #12 CA",
            merchant_name="Safeway", amount=40.0, category="FOOD_AND_DRINK")

    resp = client.patch(f"/api/transactions/{t.id}/merchant-category", json={"category": "groceries"})
    assert resp.status_code == 200
    assert resp.json()["effective_category"] == "GROCERIES"

    rules = client.get("/api/merchant-rules").json()
    assert any(r["merchant"] == "safeway" and r["category"] == "GROCERIES" for r in rules)


def test_set_rule_rejects_transfer_category(client, session):
    acc = _seed_account(session)
    t = _mk(session, acc, date=date(2026, 7, 1), name="X", merchant_name="Safeway",
            amount=40.0, category="FOOD_AND_DRINK")
    resp = client.patch(f"/api/transactions/{t.id}/merchant-category", json={"category": "TRANSFER_OUT"})
    assert resp.status_code == 400


def test_set_rule_missing_transaction(client, session):
    resp = client.patch("/api/transactions/9999/merchant-category", json={"category": "GROCERIES"})
    assert resp.status_code == 404


def test_create_list_delete_merchant_rule(client, session):
    resp = client.post("/api/merchant-rules", json={"merchant": "Trader Joe's", "category": "groceries"})
    assert resp.status_code == 200
    rid = resp.json()["id"]
    assert resp.json()["category"] == "GROCERIES"

    listed = client.get("/api/merchant-rules").json()
    assert any(r["merchant"] == "trader joe's" for r in listed)

    assert client.delete(f"/api/merchant-rules/{rid}").status_code == 204
    assert client.get("/api/merchant-rules").json() == []


def test_delete_missing_rule_404(client, session):
    assert client.delete("/api/merchant-rules/9999").status_code == 404
