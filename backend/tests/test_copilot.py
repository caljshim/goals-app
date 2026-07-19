"""Copilot orchestrator: delegates to the budgeting / investing specialists as tools.

The orchestrator's own reasoning uses a fake Anthropic client (same pattern as the
specialist suites). The specialists themselves are monkeypatched to spies so these
tests never touch Plaid, tastytrade, or Anthropic.
"""
from types import SimpleNamespace

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


def test_plain_reply_no_delegation():
    client = _FakeClient([_FakeResp("end_turn", [_text("Hi! Ask me about budgets or investing.")])])
    out = agent.run_copilot(SENTINEL_SESSION, [{"role": "user", "content": "hello"}], client=client)
    assert out == {"reply": "Hi! Ask me about budgets or investing.", "actions": [], "refresh": False, "ui_actions": []}
    assert len(client.messages.calls) == 1
    # all delegation tools are advertised to the model
    tool_names = {t["name"] for t in client.messages.calls[0]["tools"]}
    assert tool_names == {"ask_budgeting", "ask_investing", "ask_goals", "configure_dashboard"}


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

    monkeypatch.setattr(
        copilot_router, "run_copilot",
        lambda session, messages: {"reply": "hi", "actions": ["did a thing"], "refresh": True, "ui_actions": []},
    )
    resp = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "hi", "actions": ["did a thing"], "refresh": True, "ui_actions": []}


def test_router_missing_key_is_400(client, monkeypatch):
    from app.copilot import router as copilot_router

    def boom(session, messages):
        raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")

    monkeypatch.setattr(copilot_router, "run_copilot", boom)
    resp = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 400
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_router_empty_messages_is_422(client):
    resp = client.post("/api/assistant/chat", json={"messages": []})
    assert resp.status_code == 422
