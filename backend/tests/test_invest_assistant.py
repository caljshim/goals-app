from types import SimpleNamespace

from app.invest import assistant


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


def test_plain_reply_no_tools():
    client = _FakeClient([
        _FakeResp("end_turn", [SimpleNamespace(type="text", text="Index funds are a solid core.")]),
    ])
    out = assistant.run_assistant([{"role": "user", "content": "where do I start?"}], client=client)
    assert out == {"reply": "Index funds are a solid core."}
    assert len(client.messages.calls) == 1
    # read-only guardrail lives in the system prompt
    assert "cannot place" in client.messages.calls[0]["system"]


def test_tool_loop_fetches_portfolio(monkeypatch):
    async def fake_fetch(s):
        return {"environment": "cert", "accounts": []}
    monkeypatch.setattr(assistant, "get_session", lambda: object())
    monkeypatch.setattr(assistant, "fetch_portfolio", fake_fetch)
    client = _FakeClient([
        _FakeResp("tool_use", [SimpleNamespace(type="tool_use", id="tu_1", name="get_portfolio", input={})]),
        _FakeResp("end_turn", [SimpleNamespace(type="text", text="You have no open positions.")]),
    ])
    out = assistant.run_assistant([{"role": "user", "content": "what do I own?"}], client=client)
    assert out["reply"] == "You have no open positions."
    assert len(client.messages.calls) == 2
    # tool result was fed back to the model
    followup = client.messages.calls[1]["messages"][-1]["content"][0]
    assert followup["type"] == "tool_result" and "cert" in followup["content"]


def test_tool_error_is_surfaced_to_model_not_raised(monkeypatch):
    def boom():
        raise RuntimeError("tastytrade credentials are not configured")
    monkeypatch.setattr(assistant, "get_session", boom)
    client = _FakeClient([
        _FakeResp("tool_use", [SimpleNamespace(type="tool_use", id="tu_1", name="get_portfolio", input={})]),
        _FakeResp("end_turn", [SimpleNamespace(type="text", text="Connect tastytrade first.")]),
    ])
    out = assistant.run_assistant([{"role": "user", "content": "what do I own?"}], client=client)
    assert out["reply"] == "Connect tastytrade first."
    followup = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "not configured" in followup["content"]
