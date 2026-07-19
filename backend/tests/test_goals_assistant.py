from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.services import goals as goals_svc
from app.budget.services import goals_assistant as ga


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_create_goal_tool_makes_a_numeric_gym_goal_in_a_group():
    s = make_session()
    data, action = ga._create_goal(s, {"name": "Bench press", "kind": "numeric",
                                       "target": 315, "current": 275, "group": "1000 CLUB"})
    assert data["created"] and data["group"] == "1000 CLUB"
    assert action and "Bench press" in action
    g = goals_svc.list_with_progress(s)[0]
    assert g["name"] == "Bench press" and g["current_value"] == 275.0 and g["group"] == "1000 CLUB"


def test_list_goals_tool_returns_trimmed_view():
    s = make_session()
    ga._create_goal(s, {"name": "Squat", "kind": "numeric", "target": 405, "current": 315})
    data, _ = ga._list_goals(s)
    assert data["goals"][0]["name"] == "Squat" and data["goals"][0]["current_value"] == 315.0


def test_log_progress_tool_adds_a_delta():
    s = make_session()
    created, _ = ga._create_goal(s, {"name": "Bench", "kind": "numeric", "target": 315, "current": 275})
    ga._log_progress(s, {"id": created["created"], "add": 5})
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 280.0


def test_create_goal_tool_surfaces_validation_error():
    s = make_session()
    data, action = ga._create_goal(s, {"name": "x", "kind": "spend_cap", "target": 100})  # no category
    assert "error" in data and action is None


def test_tools_registered():
    names = {t["name"] for t in ga.TOOLS}
    assert {"list_goals", "create_goal", "update_goal", "log_progress",
            "reset_streak", "delete_goal", "raise_goal"} <= names
    assert set(ga._HANDLERS) == names


def test_create_weekly_numeric_goal_via_agent():
    # The church case: a weekly-repeating count, NOT an ongoing streak.
    s = make_session()
    ga._create_goal(s, {"name": "Go to church", "kind": "numeric", "target": 1, "period": "weekly"})
    g = goals_svc.list_with_progress(s)[0]
    assert g["kind"] == "numeric" and g["period"] == "weekly"


def test_update_goal_tool_can_change_period():
    s = make_session()
    created, _ = ga._create_goal(s, {"name": "Church", "kind": "numeric", "target": 1, "current": 0})
    ga._update_goal(s, {"id": created["created"], "period": "weekly"})
    assert goals_svc.list_with_progress(s)[0]["period"] == "weekly"


def test_raise_goal_tool_logs_milestone():
    s = make_session()
    created, _ = ga._create_goal(s, {"name": "Bench", "kind": "numeric", "target": 315, "current": 315})
    data, action = ga._raise_goal(s, {"id": created["created"], "target": 335})
    assert data["target"] == 335.0 and action is not None
    assert goals_svc.list_with_progress(s)[0]["milestones"][0]["value"] == 315.0


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


def test_run_assistant_creates_goal_then_replies():
    s = make_session()
    tool_block = SimpleNamespace(type="tool_use", id="tu1", name="create_goal",
                                 input={"name": "Bench", "kind": "numeric", "target": 315, "current": 275})
    text_block = SimpleNamespace(type="text", text="Added your Bench goal (275 → 315).")
    client = _FakeClient([_FakeResp("tool_use", [tool_block]), _FakeResp("end_turn", [text_block])])

    result = ga.run_assistant(s, [{"role": "user", "content": "track bench press 275 to 315"}], client=client)
    assert result["refresh"] is True
    assert any("Bench" in a for a in result["actions"])
    assert goals_svc.list_with_progress(s)[0]["name"] == "Bench"
