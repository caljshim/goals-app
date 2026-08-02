from types import SimpleNamespace

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import select

from app.auto_integration import researcher
from app.auto_integration.models import (
    IntegrationProposal,
    IntegrationProvider,
)
from app.auto_integration.researcher import ResearchError, ResearchResult
from app.auto_integration.schemas import (
    DiscoveryDraft,
    ProposalCreate,
    ResearchSource,
)
from app.budget.db import ensure_schema
from app.config import get_settings


def _draft(**overrides) -> DiscoveryDraft:
    data = {
        "recommendation_status": "found",
        "summary": "Open Nutrition provides public nutrition measurements.",
        "fit_rationale": "It exposes documented product data as JSON.",
        "limitations": ["Coverage depends on community submissions."],
        "connector": {
            "slug": "open-nutrition",
            "name": "Open Nutrition",
            "description": "Mock open-source nutrition API.",
            "base_url": "https://api.opennutrition.example",
            "documentation_url": "https://docs.opennutrition.example/api",
            "source_url": "https://github.com/example/open-nutrition",
            "license_name": "MIT",
            "authentication": "none",
            "user_agent": "Audel/auto-integration",
            "category": "nutrition",
            "operations": [
                {
                    "operation_id": "get_food",
                    "name": "Get food",
                    "description": "Get nutrition by barcode.",
                    "path_template": "/v1/foods/{barcode}",
                    "parameters": [
                        {
                            "name": "barcode",
                            "location": "path",
                            "schema_type": "string",
                            "required": True,
                            "description": "Product barcode",
                            "min_length": 8,
                            "max_length": 14,
                        },
                        {
                            "name": "servings",
                            "location": "query",
                            "schema_type": "number",
                            "required": False,
                            "minimum": 0,
                        },
                    ],
                    "fixed_query": [{"name": "format", "value": "json"}],
                    "result_mapping": [
                        {
                            "output_key": "external_id",
                            "json_pointer": "/food/id",
                        },
                        {
                            "output_key": "calories",
                            "json_pointer": "/food/calories",
                        },
                    ],
                }
            ],
        },
        "suggested_capture": {
            "operation": "get_food",
            "metric": "calories",
            "value_from": "calories",
            "unit": "kcal",
            "external_id_from": "external_id",
        },
        "sources": [
            {
                "kind": "documentation",
                "title": "API docs",
                "url": "https://docs.opennutrition.example/api",
                "notes": "Documents the product endpoint.",
            },
            {
                "kind": "source",
                "title": "Source repository",
                "url": "https://github.com/example/open-nutrition",
                "notes": "Public source code.",
            },
            {
                "kind": "license",
                "title": "MIT license",
                "url": "https://github.com/example/open-nutrition/blob/main/LICENSE",
                "notes": "Repository license.",
            },
        ],
        "alternatives": [],
    }
    data.update(overrides)
    return DiscoveryDraft.model_validate(data)


def _mock_research(monkeypatch, draft=None):
    sources = (
        ResearchSource(
            title="API docs",
            url="https://docs.opennutrition.example/api",
        ),
        ResearchSource(
            title="Source repository",
            url="https://github.com/example/open-nutrition",
        ),
        ResearchSource(
            title="License",
            url="https://github.com/example/open-nutrition/blob/main/LICENSE",
        ),
    )
    result = ResearchResult(
        draft=draft or _draft(),
        model="mock-research-model",
        response_id="msg_mock_123",
        sources=sources,
    )
    monkeypatch.setattr(
        researcher,
        "research_connector",
        lambda body: result,
    )


def _create(client, **overrides):
    body = {
        "intent": "Track the calories in food products by scanning a barcode",
        "desired_metric": "daily_calories",
        "desired_unit": "kcal",
        "constraints": ["No API key"],
    }
    body.update(overrides)
    response = client.post("/api/integrations/proposals", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_proposal_payload_columns_are_postgresql_jsonb(engine):
    columns = {
        column["name"]: column["type"]
        for column in inspect(engine).get_columns("integration_proposal")
    }
    expected = {
        "constraints_json",
        "draft_json",
        "research_sources_json",
        "manifest_json",
        "validation_errors",
    }
    assert expected <= set(columns)
    assert all(isinstance(columns[name], JSONB) for name in expected)


def test_existing_proposal_table_gains_research_sources_column(
    postgres_engine_factory,
):
    engine = postgres_engine_factory()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE integration_proposal ("
            "id VARCHAR PRIMARY KEY, "
            "intent TEXT NOT NULL, "
            "constraints_json JSONB NOT NULL, "
            "draft_json JSONB, "
            "manifest_json JSONB, "
            "validation_errors JSONB NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO integration_proposal "
            "(id, intent, constraints_json, validation_errors) "
            "VALUES ('old-proposal', 'Existing proposal', '[]', '[]')"
        )

    ensure_schema(engine)

    columns = {
        column["name"]: column["type"]
        for column in inspect(engine).get_columns("integration_proposal")
    }
    assert isinstance(columns["research_sources_json"], JSONB)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT id, research_sources_json FROM integration_proposal"
        ).one()
    assert row == ("old-proposal", [])


def test_research_produces_reviewable_compiled_manifest(
    client,
    session,
    monkeypatch,
):
    _mock_research(monkeypatch)

    proposal = _create(client)

    assert proposal["status"] == "ready_for_review"
    assert proposal["model"] == "mock-research-model"
    assert proposal["model_response_id"] == "msg_mock_123"
    assert proposal["manifest"]["auth_type"] == "none"
    operation = proposal["manifest"]["operations"][0]
    assert operation["method"] == "GET"
    assert operation["path_parameters"] == ["barcode"]
    assert operation["fixed_query"] == {"format": "json"}
    assert operation["input_schema"]["additionalProperties"] is False
    assert operation["input_schema"]["properties"]["barcode"]["maxLength"] == 14
    assert proposal["draft"]["suggested_capture"]["metric"] == "daily_calories"
    assert session.exec(select(IntegrationProvider)).all() == []

    stored = session.get(IntegrationProposal, proposal["id"])
    assert stored.manifest_json["metadata"]["discovered_by"] == (
        "anthropic-web-search"
    )


def test_approval_is_separate_atomic_install_step(
    client,
    session,
    monkeypatch,
):
    _mock_research(monkeypatch)
    proposal = _create(client)

    approved = client.post(
        f"/api/integrations/proposals/{proposal['id']}/approve",
        json={"note": "Reviewed docs and license."},
    )

    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["provider_id"] is not None
    provider = session.get(IntegrationProvider, approved_body["provider_id"])
    assert provider.slug == "open-nutrition"

    duplicate_review = client.post(
        f"/api/integrations/proposals/{proposal['id']}/approve",
        json={},
    )
    assert duplicate_review.status_code == 409


def test_rejection_never_installs_connector(client, session, monkeypatch):
    _mock_research(monkeypatch)
    proposal = _create(client)

    response = client.post(
        f"/api/integrations/proposals/{proposal['id']}/reject",
        json={"note": "Not enough data coverage."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert session.exec(select(IntegrationProvider)).all() == []


def test_unsafe_research_is_saved_as_invalid(client, session, monkeypatch):
    draft = _draft()
    draft.connector.base_url = "https://127.0.0.1"
    _mock_research(monkeypatch, draft)

    proposal = _create(client)

    assert proposal["status"] == "invalid"
    assert "private IP" in proposal["validation_errors"][0]
    assert proposal["manifest"] is None
    assert session.exec(select(IntegrationProvider)).all() == []


def test_no_match_and_research_failures_are_auditable(
    client,
    session,
    monkeypatch,
):
    no_match = DiscoveryDraft(
        recommendation_status="not_found",
        summary="No unauthenticated open-source API was sufficiently documented.",
    )
    _mock_research(monkeypatch, no_match)
    proposal = _create(client)
    assert proposal["status"] == "no_match"
    assert proposal["manifest"] is None

    def fail(body):
        raise ResearchError("API discovery request failed")

    monkeypatch.setattr(researcher, "research_connector", fail)
    failed = _create(
        client,
        intent="Track a different health metric from an open source API",
    )
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "API discovery request failed"
    assert len(session.exec(select(IntegrationProposal)).all()) == 2


def test_reviewer_can_replace_invalid_manifest_before_approval(
    client,
    monkeypatch,
):
    unsafe = _draft()
    unsafe.connector.base_url = "https://127.0.0.1"
    _mock_research(monkeypatch, unsafe)
    proposal = _create(client)
    assert proposal["status"] == "invalid"

    safe_manifest = _draft()
    from app.auto_integration.proposals import compile_draft
    manifest = compile_draft(
        safe_manifest,
        ProposalCreate(
            intent="Track the calories in food products by scanning a barcode",
            desired_metric="daily_calories",
            desired_unit="kcal",
        ),
    )
    edited = client.put(
        f"/api/integrations/proposals/{proposal['id']}/manifest",
        json={
            "manifest": manifest.model_dump(mode="json"),
            "note": "Replaced the unsafe host after manual review.",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "ready_for_review"

    approved = client.post(
        f"/api/integrations/proposals/{proposal['id']}/approve",
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_unknown_goal_is_rejected_before_research(client, monkeypatch):
    called = {"value": False}

    def should_not_research(body):
        called["value"] = True
        raise AssertionError("research should not run")

    monkeypatch.setattr(researcher, "research_connector", should_not_research)
    response = client.post(
        "/api/integrations/proposals",
        json={
            "intent": "Track a metric for a goal that does not exist",
            "goal_id": 999_999,
        },
    )
    assert response.status_code == 404
    assert called["value"] is False


def test_researcher_uses_web_search_and_structured_output(monkeypatch):
    draft = _draft()
    seen = {}

    class FakeMessages:
        def parse(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                parsed_output=draft,
                stop_reason="end_turn",
                id="msg_web_search",
                content=[
                    {
                        "type": "web_search_tool_result",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "API docs",
                                "url": "https://docs.opennutrition.example/api",
                            }
                        ],
                    }
                ],
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("INTEGRATION_DISCOVERY_MODEL", "test-model")
    get_settings.cache_clear()
    monkeypatch.setattr(researcher.anthropic, "Anthropic", FakeAnthropic)

    result = researcher.research_connector(
        ProposalCreate(
            intent="Track calories from product barcodes with no API key",
        )
    )

    assert result.response_id == "msg_web_search"
    assert seen["client"] == {"api_key": "test-key"}
    assert seen["model"] == "test-model"
    assert seen["output_format"] is DiscoveryDraft
    assert seen["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }
    ]
    assert result.sources[0].url == "https://docs.opennutrition.example/api"
    get_settings.cache_clear()
