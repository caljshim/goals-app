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


def test_transaction_read_exposes_reimburses_field(client, session):
    acc = _seed_account(session)
    _mk(session, acc, date=date(2026, 7, 1), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    row = client.get("/api/transactions").json()[0]
    assert row["reimburses_transaction_id"] is None


def test_link_and_unlink_reimbursement(client, session):
    acc = _seed_account(session)
    dinner = _mk(session, acc, date=date(2026, 7, 1), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle from Ryan", amount=-60.0, category="TRANSFER_IN")

    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": dinner.id})
    assert resp.status_code == 200
    assert resp.json()["reimburses_transaction_id"] == dinner.id

    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": None})
    assert resp.status_code == 200
    assert resp.json()["reimburses_transaction_id"] is None


def test_link_rejects_missing_source(client, session):
    _seed_account(session)
    resp = client.patch("/api/transactions/9999/reimburses", json={"target_id": 1})
    assert resp.status_code == 404


def test_link_rejects_missing_target(client, session):
    acc = _seed_account(session)
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle", amount=-60.0, category="TRANSFER_IN")
    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": 9999})
    assert resp.status_code == 404


def test_link_rejects_non_expense_target(client, session):
    acc = _seed_account(session)
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle in", amount=-60.0, category="TRANSFER_IN")
    income = _mk(session, acc, date=date(2026, 7, 1), name="Paycheck", amount=-2000.0, category="INCOME")
    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": income.id})
    assert resp.status_code == 400


def test_link_rejects_self(client, session):
    acc = _seed_account(session)
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle", amount=-60.0, category="TRANSFER_IN")
    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": zelle.id})
    assert resp.status_code == 400


def test_link_rejects_non_incoming_source(client, session):
    acc = _seed_account(session)
    a = _mk(session, acc, date=date(2026, 7, 1), name="A", amount=20.0, category="FOOD_AND_DRINK")
    b = _mk(session, acc, date=date(2026, 7, 2), name="B", amount=30.0, category="FOOD_AND_DRINK")
    resp = client.patch(f"/api/transactions/{a.id}/reimburses", json={"target_id": b.id})
    assert resp.status_code == 400


def test_linking_clears_any_category(client, session):
    # Link and category are mutually exclusive — linking drops a prior category.
    acc = _seed_account(session)
    dinner = _mk(session, acc, date=date(2026, 7, 1), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle from Ryan", amount=-60.0,
                category="TRANSFER_IN", user_category="ENTERTAINMENT")
    resp = client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": dinner.id})
    assert resp.status_code == 200
    assert resp.json()["reimburses_transaction_id"] == dinner.id
    assert resp.json()["user_category"] is None


def test_categorizing_clears_any_link(client, session):
    # ...and the reverse: assigning a category unlinks a prior reimbursement link.
    acc = _seed_account(session)
    dinner = _mk(session, acc, date=date(2026, 7, 1), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    zelle = _mk(session, acc, date=date(2026, 7, 2), name="Zelle from Ryan", amount=-60.0, category="TRANSFER_IN")
    client.patch(f"/api/transactions/{zelle.id}/reimburses", json={"target_id": dinner.id})
    resp = client.patch(f"/api/transactions/{zelle.id}", json={"user_category": "EATING_OUT"})
    assert resp.status_code == 200
    assert resp.json()["reimburses_transaction_id"] is None
    assert resp.json()["effective_category"] == "EATING_OUT"
