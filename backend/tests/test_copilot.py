"""Copilot orchestrator: delegates to the budgeting / investing specialists as tools.

The orchestrator's own reasoning uses a fake Anthropic client (same pattern as the
specialist suites). The specialists themselves are monkeypatched to spies so these
tests never touch Plaid, tastytrade, or Anthropic.
"""
from types import SimpleNamespace
from datetime import date, datetime, timezone

from app.copilot import agent


class _FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _tool_use(tool_id, name, **inp):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=inp)


def _text(t):
    return SimpleNamespace(type="text", text=t)


SENTINEL_SESSION = object()


def test_current_time_context_uses_client_timezone():
    context = agent._current_time_context(
        "America/Los_Angeles",
        now=datetime(2026, 7, 24, 2, 30, tzinfo=timezone.utc),
    )
    assert "2026-07-23T19:30:00-07:00" in context
    assert "America/Los_Angeles" in context


def test_current_time_context_falls_back_for_invalid_timezone():
    context = agent._current_time_context(
        "not/a-timezone",
        now=datetime(2026, 7, 24, 2, 30, tzinfo=timezone.utc),
    )
    assert "2026-07-24T02:30:00+00:00" in context
    assert "(UTC)" in context


def test_plain_reply_no_delegation():
    client = _FakeClient([_FakeResp("end_turn", [_text("Hi! Ask me about budgets or investing.")])])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "hello"}], client=client)
    assert out == {"reply": "Hi! Ask me about budgets or investing.", "actions": [], "refresh": False, "ui_actions": []}
    assert len(client.messages.calls) == 1
    assert "Authoritative user-local time:" in client.messages.calls[0]["system"]
    # all delegation tools are advertised to the model
    tool_names = {t["name"] for t in client.messages.calls[0]["tools"]}
    assert tool_names == {
            "ask_budgeting", "ask_investing", "ask_goals", "list_reminders",
            "create_reminder", "update_reminder", "complete_reminder", "configure_dashboard",
        "list_events", "create_event", "update_event", "delete_event",
        "create_events", "list_goal_connectors",
        "research_goal_integration", "approve_integration_proposal",
        "bind_goal_connector", "list_goal_integrations",
        "run_goal_integration",
    }


def test_delegates_to_budgeting_and_bubbles_actions(monkeypatch):
    seen = {}

    def spy_budget(session, messages, client=None):
        seen["session"] = session
        seen["question"] = messages[0]["content"]
        return {"reply": "Set your FOOD budget to $500.", "actions": ["Added budget FOOD = $500"]}

    monkeypatch.setattr(agent, "run_budgeting", spy_budget)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "ask_budgeting", question="set a food budget of 500")]),
        _FakeResp("end_turn", [_text("Done — I set your food budget to $500.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "budget $500 for food"}], client=client)

    assert out["reply"] == "Done — I set your food budget to $500."
    assert out["actions"] == ["Added budget FOOD = $500"]
    assert out["refresh"] is True
    # the specialist got the orchestrator's DB session and a formulated question
    assert seen["session"] is SENTINEL_SESSION
    assert seen["question"] == "set a food budget of 500"
    # the specialist's reply was fed back to the model as a tool_result
    followup = client.messages.calls[1]["messages"][-1]["content"][0]
    assert followup["type"] == "tool_result" and "FOOD budget" in followup["content"]


def test_delegates_to_goals_and_bubbles_actions(monkeypatch):
    seen = {}

    def spy_goals(session, messages, client=None):
        seen["question"] = messages[0]["content"]
        return {"reply": "Added your Bench press goal.", "actions": ["Created goal Bench press"]}

    monkeypatch.setattr(agent, "run_goals", spy_goals)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "ask_goals", question="track bench press 275 to 315 in 1000 CLUB")]),
        _FakeResp("end_turn", [_text("Done — added your Bench press goal to 1000 CLUB.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "set a bench goal"}], client=client)

    assert out["reply"] == "Done — added your Bench press goal to 1000 CLUB."
    assert out["actions"] == ["Created goal Bench press"] and out["refresh"] is True
    assert "bench press" in seen["question"].lower()


def test_delegates_to_investing_no_actions(monkeypatch):
    monkeypatch.setattr(agent, "run_investing", lambda messages, client=None: {"reply": "You hold VTI — diversified."})
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "ask_investing", question="what do I own?")]),
        _FakeResp("end_turn", [_text("You own VTI, a broad index ETF.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "what do I own?"}], client=client)
    assert out["reply"] == "You own VTI, a broad index ETF."
    assert out["actions"] == []
    assert out["refresh"] is False


def test_creates_persistent_reminder_directly(monkeypatch):
    seen = {}

    def create_reminder(session, payload):
        seen.update(payload)
        return {"id": 7, "title": payload["title"], "repeat_until_completed": True}

    monkeypatch.setattr(agent.schedule_svc, "create_reminder", create_reminder)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1", "create_reminder", title="Go to the grocery store",
            scheduled_for="2026-07-22", reminder_time="17:00",
            repeat_until_completed=True, nudge_interval_minutes=60,
        )]),
        _FakeResp("end_turn", [_text("I’ll remind you hourly until you check it off.")]),
    ])
    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "remind me until I respond"}],
        client=client,
    )

    assert out["refresh"] is True
    assert seen["scheduled_for"] == date(2026, 7, 22)
    assert seen["repeat_until_completed"] is True


def test_updates_persistent_reminder_directly(monkeypatch):
    seen = {}

    def update_reminder(session, reminder_id, payload):
        seen["id"] = reminder_id
        seen.update(payload)
        return {"id": reminder_id, "title": "Go to the grocery store"}

    monkeypatch.setattr(agent.schedule_svc, "update_reminder", update_reminder)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1", "update_reminder", id=7,
            scheduled_for="2026-07-22", reminder_time="18:00",
            repeat_until_completed=True, nudge_interval_minutes=120,
        )]),
        _FakeResp("end_turn", [_text("Snoozed it until 6:00 PM.")]),
    ])
    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "snooze that reminder until 6"}],
        client=client,
    )

    assert out["refresh"] is True
    assert seen["id"] == 7
    assert seen["scheduled_for"] == date(2026, 7, 22)
    assert seen["nudge_interval_minutes"] == 120


def test_creates_calendar_event_directly(monkeypatch):
    seen = {}

    def create_event(session, payload):
        seen.update(payload)
        return {"id": 9, "title": payload["title"]}

    monkeypatch.setattr(agent.schedule_svc, "create_event", create_event)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1", "create_event", title="Dinner with Maya",
            scheduled_for="2026-07-25", start_time="19:00", location="Little Star",
        )]),
        _FakeResp("end_turn", [_text("Dinner is on your calendar for Friday at 7 PM.")]),
    ])
    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "add dinner with Maya Friday at 7"}],
        client=client,
    )

    assert out["refresh"] is True
    assert seen["scheduled_for"] == date(2026, 7, 25)
    assert seen["start_time"] == "19:00"
    assert out["actions"] == ["Created event Dinner with Maya"]


def test_planner_entries_use_atomic_batch_calendar_tool(monkeypatch):
    seen = {}

    def create_events(session, payload):
        seen["events"] = payload
        return {
            "created": [
                {"id": 1, "title": event["title"]}
                for event in payload
            ],
            "skipped_duplicates": [],
        }

    monkeypatch.setattr(agent.schedule_svc, "create_events", create_events)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1",
            "create_events",
            events=[
                {
                    "title": "Dentist",
                    "scheduled_for": "2026-08-03",
                    "start_time": "09:00",
                },
                {
                    "title": "Dinner",
                    "scheduled_for": "2026-08-04",
                    "start_time": "18:30",
                },
            ],
        )]),
        _FakeResp("end_turn", [_text("I added both clear planner entries.")]),
    ])
    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "Add this planner to my calendar"}],
        client=client,
    )

    assert seen["events"][0]["scheduled_for"] == date(2026, 8, 3)
    assert out["actions"] == [
        "Created event Dentist",
        "Created event Dinner",
    ]
    assert out["refresh"] is True


def test_multimodal_user_content_is_preserved_for_orchestrator():
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "abc",
            },
        },
        {"type": "text", "text": "Read my planner"},
    ]
    client = _FakeClient([
        _FakeResp("end_turn", [_text("I can read it.")]),
    ])

    agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": content}],
        client=client,
    )

    assert client.messages.calls[0]["messages"][0]["content"] == content


def test_integration_approval_requires_explicit_current_turn():
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1",
            "approve_integration_proposal",
            proposal_id="proposal-1",
        )]),
        _FakeResp("end_turn", [_text("I still need explicit approval.")]),
    ])

    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "yes, that looks fine"}],
        client=client,
    )

    result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "explicitly say approve or install" in result["content"]
    assert out["actions"] == []


def test_explicit_integration_approval_installs_and_binds(monkeypatch):
    monkeypatch.setattr(
        agent.integration_proposals,
        "approve_proposal",
        lambda session, proposal_id, body: SimpleNamespace(
            id=proposal_id,
            goal_id=12,
            provider_id=4,
        ),
    )
    monkeypatch.setattr(
        agent.integration_bindings,
        "create_binding_from_proposal",
        lambda session, proposal_id: SimpleNamespace(id=7, goal_id=12),
    )
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use(
            "t1",
            "approve_integration_proposal",
            proposal_id="proposal-1",
        )]),
        _FakeResp("end_turn", [_text("Approved and connected.")]),
    ])

    out = agent.run_copilot(
        SENTINEL_SESSION,
        [{"role": "user", "content": "Approve proposal-1"}],
        client=client,
    )

    assert out["actions"] == [
        "Approved integration proposal proposal-1",
        "Connected API tracking to goal 12",
    ]


def test_configures_dashboard():
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "configure_dashboard", operation="add", widget_ids=["budget-progress", "portfolio-summary"])]),
        _FakeResp("end_turn", [_text("Done - I added budget progress and portfolio summary to your dashboard.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "add budget progress to my dashboard"}], client=client)

    assert out["actions"] == ["Added dashboard widgets: budget-progress, portfolio-summary"]
    assert out["ui_actions"] == [{
        "type": "dashboard.add_widgets",
        "widget_ids": ["budget-progress", "portfolio-summary"],
    }]
    assert out["refresh"] is True


def test_cross_domain_calls_both_specialists(monkeypatch):
    calls = []

    def spy_budget(session, messages, client=None):
        calls.append("budget")
        return {"reply": "You have ~$800/mo surplus.", "actions": []}

    def spy_invest(messages, client=None):
        calls.append("invest")
        return {"reply": "Consider DCAing into a broad ETF."}

    monkeypatch.setattr(agent, "run_budgeting", spy_budget)
    monkeypatch.setattr(agent, "run_investing", spy_invest)
    client = _FakeClient([
        _FakeResp("tool_use", [
            _tool_use("t1", "ask_budgeting", question="monthly surplus?"),
            _tool_use("t2", "ask_investing", question="how to invest surplus?"),
        ]),
        _FakeResp("end_turn", [_text("You have ~$800/mo spare; DCA it into an index ETF.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "how much can I invest?"}], client=client)
    assert set(calls) == {"budget", "invest"}
    assert "800" in out["reply"]
    # two tool_results returned in a single user turn
    assert len(client.messages.calls[1]["messages"][-1]["content"]) == 2


def test_specialist_error_surfaced_not_raised(monkeypatch):
    def boom(messages, client=None):
        raise RuntimeError("tastytrade credentials are not configured")

    monkeypatch.setattr(agent, "run_investing", boom)
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "ask_investing", question="my positions?")]),
        _FakeResp("end_turn", [_text("Connect tastytrade first.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "my positions?"}], client=client)
    assert out["reply"] == "Connect tastytrade first."
    followup = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "not configured" in followup["content"]


def test_unknown_tool_handled():
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "frobnicate")]),
        _FakeResp("end_turn", [_text("Sorry, I can't do that.")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "frobnicate"}], client=client)
    assert out["reply"] == "Sorry, I can't do that."
    followup = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "unknown tool" in followup["content"]


def test_empty_model_text_falls_back_to_actions_summary(monkeypatch):
    # Weak model delegates, then ends the turn with blank text — must not be surfaced blank.
    monkeypatch.setattr(
        agent, "run_budgeting",
        lambda session, messages, client=None: {
            "reply": "Created 5 rules.", "actions": ["Created 5 merchant rule(s) from history"]},
    )
    client = _FakeClient([
        _FakeResp("tool_use", [_tool_use("t1", "ask_budgeting", question="reclassify from history")]),
        _FakeResp("end_turn", [_text("   ")]),
    ])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "reclassify"}], client=client)
    assert out["reply"].strip() != ""
    assert "Created 5 merchant rule(s) from history" in out["reply"]
    assert out["refresh"] is True


def test_empty_model_text_without_actions_has_fallback():
    client = _FakeClient([_FakeResp("end_turn", [_text("")])])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "hi"}], client=client)
    assert out["reply"].strip() != ""


def test_max_tokens_truncation_is_not_blank():
    client = _FakeClient([_FakeResp("max_tokens", [])])  # truncated, no text block
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "do a lot"}], client=client)
    assert out["reply"].strip() != ""


# --- router wiring (uses the DB-backed client fixture from conftest) ---

def test_router_success(client, monkeypatch):
    from app.copilot import router as copilot_router

    seen = {}

    def run(session, messages, timezone_name=None):
        seen["timezone"] = timezone_name
        return {"reply": "hi", "actions": ["did a thing"], "refresh": True, "ui_actions": []}

    monkeypatch.setattr(
        copilot_router, "run_copilot",
        run,
    )
    resp = client.post(
        "/api/assistant/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "timezone": "America/Los_Angeles",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"reply": "hi", "actions": ["did a thing"], "refresh": True, "ui_actions": []}
    assert seen["timezone"] == "America/Los_Angeles"


def test_router_missing_key_is_400(client, monkeypatch):
    from app.copilot import router as copilot_router

    def boom(session, messages, timezone_name=None):
        raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")

    monkeypatch.setattr(copilot_router, "run_copilot", boom)
    resp = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 400
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_router_empty_messages_is_422(client):
    resp = client.post("/api/assistant/chat", json={"messages": []})
    assert resp.status_code == 422
