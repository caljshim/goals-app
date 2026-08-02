from datetime import timedelta

import httpx
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import select

from app.auto_integration import executor
from app.auto_integration.models import (
    GoalIntegrationBinding,
    GoalMeasurement,
    utc_now,
)
from app.auto_integration.service import seed_builtin_connectors
from app.budget.models import Goal


def _goal(session, **overrides):
    values = {
        "name": "Daily protein",
        "kind": "numeric",
        "target": 150,
        "period": "daily",
    }
    values.update(overrides)
    goal = Goal(**values)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def _binding(client, goal_id, **overrides):
    body = {
        "goal_id": goal_id,
        "provider": "open-food-facts",
        "operation": "get_product",
        "metric": "protein",
        "unit": "g",
        "aggregation": "sum",
        "value_from": "protein_per_100g",
        "external_id_from": "barcode",
        "trigger_mode": "barcode",
    }
    body.update(overrides)
    response = client.post("/api/integrations/bindings", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_binding_table_uses_jsonb_and_one_binding_per_goal(
    client,
    session,
    engine,
):
    seed_builtin_connectors(session)
    goal = _goal(session)
    binding = _binding(
        client,
        goal.id,
        default_parameters={},
    )
    assert binding["goal_id"] == goal.id
    columns = {
        column["name"]: column["type"]
        for column in inspect(engine).get_columns(
            "goal_integration_binding"
        )
    }
    assert isinstance(columns["default_parameters"], JSONB)

    duplicate = client.post(
        "/api/integrations/bindings",
        json={
            "goal_id": goal.id,
            "provider": "open-food-facts",
            "operation": "get_product",
            "metric": "calories",
            "unit": "kcal",
            "value_from": "calories_per_100g",
        },
    )
    assert duplicate.status_code == 409


def test_binding_execution_records_measurement_and_moves_goal_progress(
    client,
    session,
    monkeypatch,
):
    seed_builtin_connectors(session)
    goal = _goal(session)
    binding = _binding(client, goal.id)

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "product": {
                    "code": "12345678",
                    "product_name": "Beans",
                    "nutriments": {"proteins_100g": 21.5},
                }
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        executor,
        "_assert_public_hostname",
        lambda hostname: None,
    )
    monkeypatch.setattr(executor.httpx, "Client", lambda: mock_client)
    executed = client.post(
        f"/api/integrations/bindings/{binding['id']}/execute",
        json={"parameters": {"barcode": "12345678"}},
    )

    assert executed.status_code == 200, executed.text
    assert executed.json()["mapped_payload"]["protein_per_100g"] == 21.5
    measurement = session.exec(select(GoalMeasurement)).one()
    assert measurement.value == 21.5
    assert measurement.source == "open-food-facts"

    goals = client.get("/api/goals").json()
    tracked = next(item for item in goals if item["id"] == goal.id)
    assert tracked["current_value"] == 21.5
    assert tracked["unit"] == "g"
    assert tracked["linked_label"] == "Open Food Facts"


def test_aggregation_honors_current_goal_period(client, session):
    seed_builtin_connectors(session)
    goal = _goal(session)
    _binding(client, goal.id, external_id_from=None)
    now = utc_now()
    session.add(
        GoalMeasurement(
            goal_id=goal.id,
            metric="protein",
            value=30,
            unit="g",
            observed_at=now - timedelta(days=2),
            source="open-food-facts",
        )
    )
    session.add(
        GoalMeasurement(
            goal_id=goal.id,
            metric="protein",
            value=45,
            unit="g",
            observed_at=now,
            source="open-food-facts",
        )
    )
    session.commit()

    tracked = next(
        item
        for item in client.get("/api/goals").json()
        if item["id"] == goal.id
    )
    assert tracked["current_value"] == 45


def test_non_numeric_goal_and_unknown_mapping_are_rejected(
    client,
    session,
):
    seed_builtin_connectors(session)
    streak = _goal(
        session,
        name="No soda",
        kind="streak",
        target=30,
        period="once",
    )
    wrong_kind = client.post(
        "/api/integrations/bindings",
        json={
            "goal_id": streak.id,
            "provider": "open-food-facts",
            "operation": "get_product",
            "metric": "protein",
            "unit": "g",
            "value_from": "protein_per_100g",
        },
    )
    assert wrong_kind.status_code == 400

    numeric = _goal(session, name="Calories")
    bad_mapping = client.post(
        "/api/integrations/bindings",
        json={
            "goal_id": numeric.id,
            "provider": "open-food-facts",
            "operation": "get_product",
            "metric": "calories",
            "unit": "kcal",
            "value_from": "invented_field",
        },
    )
    assert bad_mapping.status_code == 400
