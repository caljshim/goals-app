import json
from datetime import date
from types import SimpleNamespace

from sqlmodel import Session, select

from app.budget.models import AgentJob, Budget, Transaction
from app.budget.services import batch_categorization
from tests.postgres import seed_accounts


class FakeMessages:
    def __init__(self, assignments):
        self.assignments = assignments
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[
            SimpleNamespace(
                type="tool_use",
                name="submit_categorizations",
                input={
                    "assignments": self.assignments,
                    "uncertain_transaction_ids": [],
                },
            )
        ])


class FakeClient:
    def __init__(self, assignments):
        self.messages = FakeMessages(assignments)


def _seed_job(session: Session, month: str) -> tuple[AgentJob, list[Transaction]]:
    session.add_all([
        Budget(category="FOOD_AND_DRINK", monthly_limit=300),
        Budget(category="TRANSPORTATION", monthly_limit=150),
    ])
    rows = [
        Transaction(
            account_id=1,
            date=date.fromisoformat(f"{month}-04"),
            name="Corner Cafe",
            amount=18.25,
            category="GENERAL_MERCHANDISE",
        ),
        Transaction(
            account_id=1,
            date=date.fromisoformat(f"{month}-05"),
            name="Mystery charge",
            amount=9.50,
            category="GENERAL_SERVICES",
        ),
    ]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    job = AgentJob(
        id="job-1",
        kind="categorize_unbudgeted",
        idempotency_key="request-12345",
        result_json=json.dumps({"month": month}),
    )
    session.add(job)
    session.commit()
    return job, rows


def test_batch_job_uses_one_structured_call_and_applies_only_confident_assignments(engine):
    month = "2026-07"
    with Session(engine) as session:
        seed_accounts(session)
        job, rows = _seed_job(session, month)
        job_id = job.id
        row_ids = [row.id for row in rows]
        client = FakeClient([
            {
                "transaction_id": row_ids[0],
                "category": "FOOD_AND_DRINK",
                "confidence": 0.94,
            },
            {
                "transaction_id": row_ids[1],
                "category": "TRANSPORTATION",
                "confidence": 0.40,
            },
            {
                "transaction_id": 999999,
                "category": "FOOD_AND_DRINK",
                "confidence": 0.99,
            },
        ])

    batch_categorization.run_job(job_id, engine, client=client)

    with Session(engine) as session:
        saved = session.get(AgentJob, job_id)
        first = session.get(Transaction, row_ids[0])
        second = session.get(Transaction, row_ids[1])
        assert saved.status == "completed"
        assert saved.total == 2
        assert saved.completed == 1
        assert first.user_category == "FOOD_AND_DRINK"
        assert second.user_category is None
        result = json.loads(saved.result_json)
        assert result["categorized"] == 1
        assert result["remaining"] == 1
    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["tool_choice"]["name"] == "submit_categorizations"


def test_batch_job_without_budgets_leaves_transactions_for_review(engine):
    with Session(engine) as session:
        seed_accounts(session)
        transaction = Transaction(
            account_id=1,
            date=date(2026, 7, 4),
            name="Corner Cafe",
            amount=18.25,
            category="FOOD_AND_DRINK",
        )
        job = AgentJob(
            id="job-no-budgets",
            kind="categorize_unbudgeted",
            idempotency_key="request-no-budgets",
            result_json=json.dumps({"month": "2026-07"}),
        )
        session.add_all([transaction, job])
        session.commit()
        job_id = job.id

    batch_categorization.run_job(job_id, engine)

    with Session(engine) as session:
        saved = session.get(AgentJob, job_id)
        result = json.loads(saved.result_json)
        assert saved.status == "completed"
        assert saved.total == 1
        assert result["remaining"] == 1


def test_job_api_is_idempotent_and_pollable(client, monkeypatch):
    from app.copilot import jobs

    started = []
    monkeypatch.setattr(jobs, "run_job", lambda job_id, engine: started.append(job_id))
    body = {
        "month": "2026-07",
        "timezone": "America/Los_Angeles",
        "idempotency_key": "same-request-123",
    }

    first = client.post("/api/assistant/jobs/categorize-unbudgeted", json=body)
    second = client.post("/api/assistant/jobs/categorize-unbudgeted", json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(started) == 1
    polled = client.get(f"/api/assistant/jobs/{first.json()['id']}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "queued"


def test_job_api_rejects_invalid_month(client):
    response = client.post(
        "/api/assistant/jobs/categorize-unbudgeted",
        json={"month": "July", "idempotency_key": "request-12345"},
    )
    assert response.status_code == 422
