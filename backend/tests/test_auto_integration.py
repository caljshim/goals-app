from datetime import datetime

import httpx
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import select

from app.auto_integration import executor
from app.auto_integration.models import (
    GoalMeasurement,
    IntegrationOperation,
    IntegrationProvider,
    IntegrationRun,
)
from app.auto_integration.service import seed_builtin_connectors
from app.budget.models import Goal


def _manifest(**overrides):
    manifest = {
        "manifest_version": 1,
        "slug": "example-metrics",
        "name": "Example Metrics",
        "description": "A mocked read-only metric provider.",
        "base_url": "https://api.example.com",
        "documentation_url": "https://docs.example.com",
        "source_url": "https://github.com/example/metrics",
        "license_name": "MIT",
        "auth_type": "none",
        "user_agent": "Audel/tests",
        "metadata": {"category": "testing"},
        "operations": [
            {
                "operation_id": "get_metric",
                "name": "Get metric",
                "method": "GET",
                "path_template": "/v1/items/{item_id}",
                "path_parameters": ["item_id"],
                "fixed_query": {"format": "full"},
                "input_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "item_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 40,
                        },
                        "scale": {"type": "number", "minimum": 0},
                    },
                    "required": ["item_id"],
                    "additionalProperties": False,
                },
                "result_mapping": {
                    "external_id": "/item/id",
                    "value": "/item/value",
                },
            }
        ],
    }
    manifest.update(overrides)
    return manifest


def _install(client, manifest=None):
    response = client.post(
        "/api/integrations/connectors",
        json=manifest or _manifest(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_builtin_connector_is_seeded_without_calling_external_api(session):
    seed_builtin_connectors(session)

    provider = session.exec(
        select(IntegrationProvider).where(
            IntegrationProvider.slug == "open-food-facts"
        )
    ).one()
    operation = session.exec(
        select(IntegrationOperation).where(
            IntegrationOperation.provider_id == provider.id
        )
    ).one()

    assert provider.base_url == "https://world.openfoodfacts.org"
    assert provider.metadata_json["category"] == "nutrition"
    assert operation.method == "GET"
    assert operation.result_mapping["calories_per_100g"].startswith("/")


def test_integration_payload_columns_are_postgresql_jsonb(engine):
    expected = {
        "integration_provider": {"metadata_json"},
        "integration_operation": {
            "path_parameters",
            "fixed_query",
            "input_schema",
            "response_schema",
            "result_mapping",
        },
        "integration_run": {
            "request_parameters",
            "response_payload",
            "mapped_payload",
        },
        "goal_measurement": {"raw_data"},
    }

    inspector = inspect(engine)
    for table_name, jsonb_columns in expected.items():
        columns = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }
        assert jsonb_columns <= set(columns)
        assert all(
            isinstance(columns[column_name], JSONB)
            for column_name in jsonb_columns
        )


def test_connector_manifest_install_and_listing(client):
    installed = _install(client)

    assert installed["slug"] == "example-metrics"
    assert installed["metadata"] == {"category": "testing"}
    assert installed["operations"][0]["operation_id"] == "get_metric"

    listed = client.get("/api/integrations/connectors")
    assert listed.status_code == 200
    assert [provider["slug"] for provider in listed.json()] == [
        "example-metrics"
    ]

    duplicate = client.post(
        "/api/integrations/connectors",
        json=_manifest(),
    )
    assert duplicate.status_code == 409


def test_connector_manifest_rejects_unsafe_hosts_and_secret_parameters(client):
    private = client.post(
        "/api/integrations/connectors",
        json=_manifest(base_url="https://127.0.0.1"),
    )
    assert private.status_code == 400
    assert "private IP" in private.json()["detail"]

    secret_manifest = _manifest(slug="secret-metrics")
    operation = secret_manifest["operations"][0]
    operation["input_schema"]["properties"]["api_key"] = {"type": "string"}
    secret = client.post(
        "/api/integrations/connectors",
        json=secret_manifest,
    )
    assert secret.status_code == 400
    assert "credentials" in secret.json()["detail"]


def test_execute_maps_payload_logs_run_and_captures_measurement(
    client,
    session,
    monkeypatch,
):
    _install(client)
    goal = Goal(name="Daily calories", kind="numeric", target=2_000)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["path"] = request.url.raw_path.split(b"?", 1)[0].decode()
        seen["query"] = dict(request.url.params)
        seen["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"item": {"id": "food-123", "value": 325.5}},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(executor, "_assert_public_hostname", lambda hostname: None)
    monkeypatch.setattr(executor.httpx, "Client", lambda: mock_client)

    response = client.post(
        "/api/integrations/execute",
        json={
            "provider": "example-metrics",
            "operation": "get_metric",
            "parameters": {"item_id": "protein/bar", "scale": 2},
            "capture": {
                "goal_id": goal.id,
                "metric": "calories",
                "value_from": "value",
                "unit": "kcal",
                "external_id_from": "external_id",
            },
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert run["mapped_payload"] == {
        "external_id": "food-123",
        "value": 325.5,
    }
    assert seen == {
        "method": "GET",
        "path": "/v1/items/protein%2Fbar",
        "query": {"format": "full", "scale": "2"},
        "user_agent": "Audel/tests",
    }

    measurement = session.exec(select(GoalMeasurement)).one()
    assert (
        measurement.goal_id,
        measurement.metric,
        measurement.value,
        measurement.unit,
        measurement.external_id,
    ) == (goal.id, "calories", 325.5, "kcal", "food-123")
    assert measurement.run_id == run["id"]


def test_invalid_parameters_never_make_an_http_request(
    client,
    session,
    monkeypatch,
):
    _install(client)

    def should_not_run():
        raise AssertionError("HTTP client should not be created")

    monkeypatch.setattr(executor.httpx, "Client", should_not_run)
    response = client.post(
        "/api/integrations/execute",
        json={
            "provider": "example-metrics",
            "operation": "get_metric",
            "parameters": {},
        },
    )

    assert response.status_code == 422
    assert "required property" in response.json()["detail"]
    assert session.exec(select(IntegrationRun)).all() == []


def test_upstream_failure_is_persisted_and_redirects_are_not_followed(
    client,
    session,
    monkeypatch,
):
    _install(client)
    seen = {"calls": 0}

    def handler(request: httpx.Request):
        seen["calls"] += 1
        return httpx.Response(
            302,
            headers={
                "content-type": "application/json",
                "location": "http://127.0.0.1/private",
            },
            json={"error": "redirect"},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(executor, "_assert_public_hostname", lambda hostname: None)
    monkeypatch.setattr(executor.httpx, "Client", lambda: mock_client)

    response = client.post(
        "/api/integrations/execute",
        json={
            "provider": "example-metrics",
            "operation": "get_metric",
            "parameters": {"item_id": "abc"},
        },
    )

    assert response.status_code == 502
    assert seen["calls"] == 1
    run = session.exec(select(IntegrationRun)).one()
    assert run.status == "failed"
    assert run.http_status == 302
    assert run.response_payload == {"error": "redirect"}


def test_manual_measurements_are_idempotent_and_filterable(
    client,
    session,
):
    goal = Goal(name="Protein", kind="numeric", target=150)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    payload = {
        "goal_id": goal.id,
        "metric": "protein",
        "value": 42.5,
        "unit": "g",
        "observed_at": datetime(2026, 7, 28, 12, 0).isoformat(),
        "source": "manual-import",
        "external_id": "meal-1",
        "raw_data": {"meal": "lunch"},
    }

    first = client.post("/api/integrations/measurements", json=payload)
    second = client.post("/api/integrations/measurements", json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    response = client.get(
        f"/api/integrations/goals/{goal.id}/measurements",
        params={"metric": "protein"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["raw_data"] == {"meal": "lunch"}
