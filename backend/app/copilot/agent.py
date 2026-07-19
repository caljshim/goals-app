"""Copilot orchestrator: one agent that delegates to a budgeting or investing specialist.

Same manual tool-use loop as the specialists, but its only tools are the two
specialists themselves — `ask_budgeting` and `ask_investing`. Each specialist is
stateless per call: the orchestrator owns the conversation and formulates a single
question for the specialist. Budgeting actions bubble up so the frontend refreshes.
"""
import json

import anthropic

from app.budget.services.assistant import run_assistant as run_budgeting
from app.budget.services.goals_assistant import run_assistant as run_goals
from app.config import get_settings
from app.invest.assistant import run_assistant as run_investing

MAX_TOOL_ITERATIONS = 4
MAX_OUTPUT_TOKENS = 2048

DASHBOARD_STATIC_WIDGET_IDS = [
    "left-to-spend",
    "monthly-averages",
    "spending-by-category",
    "income-vs-expense",
    "category-transactions",
    "recent-transactions",
    "merchant-rules",
    "manual-transaction",
    "account-balances",
    "account-sync",
    "budget-progress",
    "budget-form",
    "goal-todo-day",
    "goal-todo-week",
    "goal-todo-month",
    "portfolio-summary",
    "portfolio-positions",
]


def _valid_dashboard_widget_id(widget_id: str) -> bool:
    if widget_id in DASHBOARD_STATIC_WIDGET_IDS:
        return True
    if widget_id.startswith("goal-name:") and widget_id.removeprefix("goal-name:").strip():
        return True
    if widget_id.startswith("goal-group:") and widget_id.removeprefix("goal-group:").strip():
        return True
    if widget_id.startswith("goal:") and widget_id.removeprefix("goal:").isdigit():
        return True
    return widget_id in {
        "goal-section:daily",
        "goal-section:weekly",
        "goal-section:monthly",
        "goal-section:interval",
        "goal-section:once",
        "goal-section:ongoing",
    }

SYSTEM = (
    "You are the user's personal-money copilot. You coordinate three specialists and speak "
    "to the user with one voice. Money amounts are USD.\n\n"
    "You have four tools:\n"
    "- ask_budgeting(question): a budgeting specialist with live access to the user's bank "
    "transactions, spending categories, and budgets. It can also change categories and "
    "budgets. Use it for income, spending, cash flow, surplus, categories, and budgets.\n"
    "- ask_investing(question): an education-forward investing specialist with read-only "
    "access to the user's tastytrade brokerage account (holdings, balances, risk). It "
    "cannot place trades. Use it for portfolio, allocation, strategy, and market questions.\n"
    "- ask_goals(question): a goals specialist that creates and tracks the user's goals of "
    "ANY kind — savings targets, spending caps, streaks/habits, AND non-money numeric goals "
    "like fitness or strength (bench press, squat, a '1000 CLUB' total). It can create, "
    "update, and log progress. Use it whenever the user wants to set, group, or track a goal — "
    "including fitness/lifting goals. Do NOT refuse fitness goals; route them here as numeric goals.\n"
    "- configure_dashboard(operation, widget_ids): configure the user's Dashboard tab. Use it "
    "when the user asks to add, remove, clear, reset, or replace dashboard widgets. "
    "Available widget_ids: left-to-spend, monthly-averages, spending-by-category, "
    "income-vs-expense, category-transactions, recent-transactions, merchant-rules, "
    "manual-transaction, account-balances, account-sync, budget-progress, budget-form, "
    "portfolio-summary, portfolio-positions. Goal widgets are dynamic: use goal-name:NAME "
    "for an individual goal by exact name, goal-group:GROUP for a user-named goal group/category, "
    "goal:ID if you know the numeric goal id, or goal-section:daily|weekly|monthly|once|ongoing "
    "for goal cadence sections.\n\n"
    "Routing:\n"
    "- Send each question to the specialist that owns it. Pass a clear, self-contained "
    "question — the specialist has no memory of the conversation.\n"
    "- For questions that span domains (e.g. 'how much of my spare cash should I invest?'), "
    "call the specialists you need, then synthesize one answer.\n"
    "- Answer greetings, clarifications, and general questions yourself without a tool.\n"
    "- For dashboard customization requests, call configure_dashboard directly; do not route "
    "those to the budgeting/goals/investing specialists.\n"
    "- When a specialist reports it changed something, tell the user plainly.\n"
    "- Never invent portfolio holdings or spending numbers — get them from a specialist.\n"
    "- Be concise: short paragraphs, compact lists, amounts like $1,234."
)

TOOLS = [
    {
        "name": "ask_budgeting",
        "description": (
            "Ask the budgeting specialist (live access to the user's bank transactions, "
            "spending, categories, and budgets; can modify categories and budgets). Use for "
            "income, spending, cash flow, surplus, categories, and budgets. Pass a clear, "
            "self-contained question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Self-contained question for the budgeting specialist"}},
            "required": ["question"],
        },
    },
    {
        "name": "ask_investing",
        "description": (
            "Ask the education-forward investing specialist (read-only access to the user's "
            "tastytrade portfolio; cannot place trades). Use for holdings, allocation, risk, "
            "strategy, and market questions. Pass a clear, self-contained question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Self-contained question for the investing specialist"}},
            "required": ["question"],
        },
    },
    {
        "name": "ask_goals",
        "description": (
            "Ask the goals specialist, which creates and tracks goals of ANY kind — savings "
            "targets, spending caps, streaks/habits, and non-money numeric goals like fitness "
            "or strength (bench press, squat, a '1000 CLUB'). It can create, update, group, and "
            "log progress. Route any goal-setting or goal-tracking request here, fitness included."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Self-contained request for the goals specialist"}},
            "required": ["question"],
        },
    },
    {
        "name": "configure_dashboard",
        "description": (
            "Configure the user's Dashboard tab. Use for requests like 'add budget progress "
            "to my dashboard', 'remove portfolio positions', 'make my dashboard show goals "
            "and account balances', 'clear the dashboard', or 'reset dashboard'. Valid "
            f"static widget_ids are: {', '.join(DASHBOARD_STATIC_WIDGET_IDS)}. Goal widget ids "
            "may also be goal-name:NAME, goal-group:GROUP, goal:ID, or "
            "goal-section:daily|weekly|monthly|once|ongoing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["set", "add", "remove", "clear", "reset"],
                    "description": "set replaces the layout; add/remove changes it; clear empties it; reset restores defaults.",
                },
                "widget_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Widget ids for set/add/remove. Omit for clear/reset.",
                },
            },
            "required": ["operation"],
        },
    },
]


def _dashboard_action(tool_input: dict, actions: list[str], ui_actions: list[dict]) -> dict:
    op = (tool_input or {}).get("operation")
    raw_ids = (tool_input or {}).get("widget_ids") or []
    widget_ids = [w for w in raw_ids if isinstance(w, str) and _valid_dashboard_widget_id(w)]
    if op in ("set", "add", "remove") and not widget_ids:
        return {"error": "widget_ids are required for set/add/remove"}

    action_map = {
        "set": "dashboard.set_widgets",
        "add": "dashboard.add_widgets",
        "remove": "dashboard.remove_widgets",
        "clear": "dashboard.clear_widgets",
        "reset": "dashboard.reset_widgets",
    }
    action_type = action_map.get(op)
    if not action_type:
        return {"error": f"unknown dashboard operation {op}"}

    ui_action = {"type": action_type}
    if op in ("set", "add", "remove"):
        ui_action["widget_ids"] = widget_ids
    ui_actions.append(ui_action)

    label = {
        "set": f"Set dashboard widgets: {', '.join(widget_ids)}",
        "add": f"Added dashboard widgets: {', '.join(widget_ids)}",
        "remove": f"Removed dashboard widgets: {', '.join(widget_ids)}",
        "clear": "Cleared dashboard widgets",
        "reset": "Reset dashboard widgets",
    }[op]
    actions.append(label)
    return {"configured": True, "operation": op, "widget_ids": widget_ids}


def _dispatch(session, name: str, tool_input: dict, client, actions: list[str], ui_actions: list[dict]) -> dict:
    """Run one delegation tool; specialist errors become error results, never raise."""
    question = (tool_input or {}).get("question", "")
    try:
        if name == "ask_budgeting":
            out = run_budgeting(session, [{"role": "user", "content": question}], client=client)
            actions.extend(out.get("actions", []))
            return {"reply": out.get("reply", ""), "actions": out.get("actions", [])}
        if name == "ask_goals":
            out = run_goals(session, [{"role": "user", "content": question}], client=client)
            actions.extend(out.get("actions", []))
            return {"reply": out.get("reply", ""), "actions": out.get("actions", [])}
        if name == "ask_investing":
            out = run_investing([{"role": "user", "content": question}], client=client)
            return {"reply": out.get("reply", "")}
        if name == "configure_dashboard":
            return _dashboard_action(tool_input or {}, actions, ui_actions)
        return {"error": f"unknown tool {name}"}
    except Exception as exc:  # noqa: BLE001 — surface specialist errors back to the model
        return {"error": str(exc)}


def run_copilot(session, messages: list[dict], client=None) -> dict:
    """Run the orchestrator for one user turn; returns {reply, actions, refresh, ui_actions}."""
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    actions: list[str] = []
    ui_actions: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=settings.assistant_model, max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM, tools=TOOLS, messages=convo,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not text:
                # The weak/cheap model sometimes ends a tool turn with no text, or the
                # reply is cut off by max_tokens. Never surface a blank reply to the user.
                text = ("Done — " + "; ".join(actions)) if actions else (
                    "I wasn't able to put that into words — could you rephrase or narrow it down?"
                )
            return {"reply": text, "actions": actions, "refresh": bool(actions), "ui_actions": ui_actions}

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            data = _dispatch(session, b.name, b.input or {}, client, actions, ui_actions)
            results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": json.dumps(data, default=str),
            })
        convo.append({"role": "user", "content": results})

    return {
        "reply": "I took several steps — could you re-ask or narrow that down a bit?",
        "actions": actions, "refresh": bool(actions), "ui_actions": ui_actions,
    }
