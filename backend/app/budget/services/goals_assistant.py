"""Goals specialist: a tool-using agent over the user's goals of ANY kind — financial and
spending targets, general numeric targets (including fitness/strength like bench press or
a "1000 CLUB" total), and streaks. Delegated to by the copilot orchestrator."""
import json
from datetime import date

import anthropic
from sqlmodel import Session

from app.config import get_settings
from app.budget.services import goals as goals_svc

MAX_TOOL_ITERATIONS = 6
MAX_OUTPUT_TOKENS = 2048

SYSTEM = (
    "You are the user's goals specialist embedded in their money app. You manage goals of ANY "
    "kind — not just money:\n"
    "- save: legacy savings records only. Do not create new save goals.\n"
    "- financial: flexible money goal. Choose financial_source accounts for automatic bank tracking "
    "or manual for user-entered progress. For accounts, choose financial_metric account_balance, "
    "debt_balance, net_worth, income, or cash_flow; financial_rule reach, stay_under, or reduce_to; "
    "account_ids selects sources and period scopes flow metrics. Manual goals use account_balance as the metric, "
    "accept current and step, and do not use account_ids. ALWAYS use financial for new money goals.\n"
    "- numeric: any current→target number — USE THIS for fitness/strength (bench press, squat, a "
    "'1000 CLUB' total), net worth, AND any habit/count that repeats. direction 'reach' (default) "
    "or 'under'. An under goal MUST include `current`; that first value becomes its fixed starting "
    "anchor and must be greater than the target.\n"
    "- streak: a CONTINUOUS days-since counter (days sober, days since an event). It does NOT "
    "repeat weekly/daily — use it ONLY for 'days since ...'.\n\n"
    "Spending limits are budgets, not goals. Never create spend_cap or category_spend goals; tell the "
    "orchestrator/user to use Budgets instead.\n\n"
    "CADENCE — this matters: set period (once/daily/weekly/monthly) on numeric goals.\n"
    "- A habit or count that REPEATS and resets each period — 'go to church every week', 'work out "
    "3× a week', 'read every day' — is a NUMERIC goal with period=weekly/daily and a per-period "
    "target (e.g. target 1, period weekly). It resets automatically each period. DO NOT use streak "
    "for these; streak is only continuous days-since.\n"
    "- If you (or a prior turn) created the wrong thing, fix it: update_goal can change period, or "
    "delete_goal + create_goal with the right kind/period.\n\n"
    "Group related goals with a shared `group` name (e.g. '1000 CLUB' for the three big lifts) — the "
    "app shows a rolled-up % for the group. Manual goals hold a `current` value you change with "
    "log_progress (set current, or add a delta); `step` sizes the +/- buttons. raise_goal bumps a "
    "reached legacy save, manual financial, or numeric goal to a new target and logs the old one as a milestone.\n\n"
    "Guidelines:\n"
    "- Call list_goals first when the user refers to goals that may already exist.\n"
    "- Create/update/log directly when the intent is clear, then summarize what you changed.\n"
    "- For a multi-part target like a 1000 club, create one numeric goal per lift with a shared group.\n"
    "- Be concise. Numeric goals have no currency; financial goals are dollars."
)

TOOLS = [
    {
        "name": "list_goals",
        "description": "List the user's current goals with their progress.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_goal",
        "description": (
            "Create a goal. kind is financial|numeric|streak — use financial for money outcomes "
            "and numeric for any non-money "
            "target such as a lift. Spending limits belong in Budgets, not this tool. Provide target for "
            "financial/numeric; period (daily/weekly/monthly/interval) for cadence; weekly_days as a list of "
            "monday-sunday values to schedule a weekly goal on multiple days; group to bundle related goals; "
            "current for a manual starting value (required and greater than target when direction=under); "
            "direction reach|under for numeric; since "
            "(YYYY-MM-DD) for a streak start; step for the +/- increment; deadline (YYYY-MM-DD)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "description": "financial | numeric | streak"},
                "target": {"type": "number"},
                "current": {"type": "number"},
                "group": {"type": "string"},
                "period": {"type": "string"},
                "weekly_days": {"type": "array", "items": {"type": "string"}},
                "reset_time": {"type": "string"},
                "weekly_reset_day": {"type": "string"},
                "monthly_reset_day": {"type": "integer"},
                "interval_days": {"type": "integer"},
                "direction": {"type": "string"},
                "category": {"type": "string"},
                "account_id": {"type": "integer"},
                "account_ids": {"type": "array", "items": {"type": "integer"}},
                "financial_metric": {"type": "string"},
                "financial_rule": {"type": "string"},
                "financial_source": {"type": "string", "description": "accounts | manual"},
                "since": {"type": "string"},
                "step": {"type": "number"},
                "deadline": {"type": "string"},
            },
            "required": ["name", "kind"],
        },
    },
    {
        "name": "update_goal",
        "description": (
            "Edit an existing goal: name, target, group, deadline, category, and crucially its "
            "cadence — period (once/daily/weekly/monthly), direction (reach/under), or step. Use "
            "this to fix a goal's period (e.g. make a habit repeat weekly)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"}, "name": {"type": "string"}, "target": {"type": "number"},
                "group": {"type": "string"}, "deadline": {"type": "string"}, "category": {"type": "string"},
                "period": {"type": "string"},
                "weekly_days": {"type": "array", "items": {"type": "string"}},
                "reset_time": {"type": "string"}, "weekly_reset_day": {"type": "string"},
                "monthly_reset_day": {"type": "integer"}, "interval_days": {"type": "integer"},
                "direction": {"type": "string"}, "step": {"type": "number"},
                "account_ids": {"type": "array", "items": {"type": "integer"}},
                "financial_metric": {"type": "string"}, "financial_rule": {"type": "string"},
                "financial_source": {"type": "string", "description": "accounts | manual"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "raise_goal",
        "description": (
            "Raise a reached legacy save, manual financial, or numeric goal to a new target — logs the cleared target as "
            "a milestone, then sets the new one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "target": {"type": "number"}},
            "required": ["id", "target"],
        },
    },
    {
        "name": "log_progress",
        "description": "Update a manual goal's value: set `current`, or `add` a delta to it.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "current": {"type": "number"}, "add": {"type": "number"}},
            "required": ["id"],
        },
    },
    {
        "name": "reset_streak",
        "description": "Reset a streak goal to today (records the best streak).",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "delete_goal",
        "description": "Delete a goal.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
]


def _iso(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _goal_view(g: dict) -> dict:
    return {k: g[k] for k in ("id", "name", "kind", "financial_metric", "financial_rule", "financial_source", "account_ids", "current_value", "anchor_value", "target", "pct", "status", "unit", "group", "period", "weekly_days", "reset_time", "weekly_reset_day", "monthly_reset_day", "interval_days")}


def _list_goals(session: Session) -> tuple[dict, None]:
    return {"goals": [_goal_view(g) for g in goals_svc.list_with_progress(session)]}, None


def _create_goal(session: Session, data: dict) -> tuple[dict, str | None]:
    payload = dict(data or {})
    payload["since"] = _iso(payload.get("since"))
    payload["deadline"] = _iso(payload.get("deadline"))
    try:
        goal = goals_svc.create_goal(session, payload)
    except ValueError as exc:
        return {"error": str(exc)}, None
    return {"created": goal.id, "name": goal.name, "kind": goal.kind, "group": goal.group}, f"Created goal {goal.name}"


def _update_goal(session: Session, data: dict) -> tuple[dict, str | None]:
    gid = data.get("id")
    fields = {k: data[k] for k in ("name", "target", "group", "deadline", "category", "account_ids", "financial_metric", "financial_rule", "financial_source",
                                   "period", "weekly_days", "reset_time", "weekly_reset_day",
                                   "monthly_reset_day", "interval_days", "direction", "step") if k in data}
    if "deadline" in fields:
        fields["deadline"] = _iso(fields["deadline"])
    goal = goals_svc.update_goal(session, int(gid), fields) if gid is not None else None
    if not goal:
        return {"error": "goal not found"}, None
    return {"updated": goal.id, "name": goal.name}, f"Updated goal {goal.name}"


def _raise_goal(session: Session, data: dict) -> tuple[dict, str | None]:
    gid, target = data.get("id"), data.get("target")
    goal = goals_svc.raise_goal(session, int(gid), float(target)) if (gid is not None and target is not None) else None
    if not goal:
        return {"error": "goal not found"}, None
    return {"id": goal.id, "target": goal.target}, f"Raised {goal.name} to {goal.target}"


def _log_progress(session: Session, data: dict) -> tuple[dict, str | None]:
    gid = data.get("id")
    goal = goals_svc.set_progress(session, int(gid), current=data.get("current"), add=data.get("add")) if gid is not None else None
    if not goal:
        return {"error": "goal not found"}, None
    return {"id": goal.id, "current": goal.current}, f"Logged progress on {goal.name}"


def _reset_streak(session: Session, data: dict) -> tuple[dict, str | None]:
    gid = data.get("id")
    goal = goals_svc.reset_streak(session, int(gid)) if gid is not None else None
    if not goal:
        return {"error": "goal not found"}, None
    return {"id": goal.id, "reset": True}, f"Reset streak {goal.name}"


def _delete_goal(session: Session, data: dict) -> tuple[dict, str | None]:
    gid = data.get("id")
    ok = goals_svc.delete_goal(session, int(gid)) if gid is not None else False
    return ({"archived": True}, "Archived a goal") if ok else ({"error": "goal not found"}, None)


_HANDLERS = {
    "list_goals": lambda s, i: _list_goals(s),
    "create_goal": lambda s, i: _create_goal(s, i),
    "update_goal": lambda s, i: _update_goal(s, i),
    "raise_goal": lambda s, i: _raise_goal(s, i),
    "log_progress": lambda s, i: _log_progress(s, i),
    "reset_streak": lambda s, i: _reset_streak(s, i),
    "delete_goal": lambda s, i: _delete_goal(s, i),
}


def _execute_tool(session: Session, name: str, tool_input: dict) -> tuple[dict, str | None]:
    handler = _HANDLERS.get(name)
    if not handler:
        return {"error": f"unknown tool {name}"}, None
    try:
        return handler(session, tool_input or {})
    except Exception as exc:  # noqa: BLE001 — surface tool errors back to the model
        return {"error": str(exc)}, None


def run_assistant(session: Session, messages: list[dict], client=None) -> dict:
    """Run the goals agent loop for one turn; returns {reply, actions, refresh}."""
    if client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    model = get_settings().assistant_model
    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    actions: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=model, max_tokens=MAX_OUTPUT_TOKENS, system=SYSTEM, tools=TOOLS, messages=convo,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not text:
                text = ("Done — " + "; ".join(actions)) if actions else (
                    "I wasn't able to put that into words — could you rephrase or narrow it down?"
                )
            return {"reply": text, "actions": actions, "refresh": bool(actions)}

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            data, action = _execute_tool(session, b.name, b.input or {})
            if action:
                actions.append(action)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(data, default=str)})
        convo.append({"role": "user", "content": results})

    return {
        "reply": "I took several steps — could you re-ask or narrow that down a bit?",
        "actions": actions, "refresh": bool(actions),
    }
