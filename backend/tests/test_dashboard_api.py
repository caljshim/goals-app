from datetime import date

from app.budget.models import Budget, Transaction


def test_dashboard_summary(client, session):
    session.add(Transaction(account_id=1, date=date(2026, 7, 2), name="G", amount=80.0, category="GROCERIES"))
    session.add(Transaction(account_id=1, date=date(2026, 7, 6), name="Pay", amount=-2000.0, category="INCOME"))
    session.add(Budget(category="GROCERIES", monthly_limit=300.0))
    session.commit()

    resp = client.get("/api/dashboard/summary?month=2026-07")
    assert resp.status_code == 200
    data = resp.json()
    assert data["expense_total"] == 80.0
    assert data["income_total"] == 2000.0
    assert data["budget_progress"][0]["spent"] == 80.0
    assert len(data["monthly_trend"]) == 6


def test_dashboard_summary_rejects_malformed_month(client, session):
    resp = client.get("/api/dashboard/summary?month=2026-13")
    assert resp.status_code == 422

    resp = client.get("/api/dashboard/summary?month=bad")
    assert resp.status_code == 422
