def test_same_category_can_have_each_budget_period(client, session):
    for period, limit in (("daily", 25), ("weekly", 100), ("monthly", 300)):
        response = client.post("/api/budgets", json={
            "category": "eating out", "monthly_limit": limit, "period": period,
        })
        assert response.status_code == 201
        assert response.json()["category"] == "EATING_OUT"
        assert response.json()["period"] == period

    rows = client.get("/api/budgets").json()
    assert {(row["period"], row["monthly_limit"]) for row in rows} == {
        ("daily", 25), ("weekly", 100), ("monthly", 300),
    }


def test_duplicate_category_and_period_is_rejected(client, session):
    body = {"category": "GROCERIES", "monthly_limit": 50, "period": "weekly"}
    assert client.post("/api/budgets", json=body).status_code == 201
    assert client.post("/api/budgets", json=body).status_code == 409


def test_budget_period_validation(client, session):
    response = client.post("/api/budgets", json={
        "category": "GROCERIES", "monthly_limit": 50, "period": "yearly",
    })
    assert response.status_code == 400
