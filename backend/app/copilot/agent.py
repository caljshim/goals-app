"""Copilot orchestrator: one agent that delegates to a budgeting or investing specialist.

Same manual tool-use loop as the specialists, but its only tools are the two
specialists themselves — `ask_budgeting` and `ask_investing`. Each specialist is
stateless per call: the orchestrator owns the conversation and formulates a single
question for the specialist. Budgeting actions bubble up so the frontend refreshes.
"""
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic

from app.budget.services.assistant import run_assistant as run_budgeting
from app.budget.services.goals_assistant import run_assistant as run_goals
from app.budget.services import schedule as schedule_svc
from app.config import get_settings
from app.invest.assistant import run_assistant as run_investing

MAX_TOOL_ITERATIONS = 4
MAX_OUTPUT_TOKENS = 2048
DEFAULT_TIMEZONE = "UTC"

DASHBOARD_STATIC_WIDGET_IDS = [
    "left-to-spend",
    "monthly-averages",
    "spending-by-category",
    "income-vs-expense",
    "category-transactions",
    "recent-transactions",
    "unbudgeted-transactions",
    "p2p-review",
    "merchant-rules",
    "manual-transaction",
    "account-balances",
    "account-sync",
    "budget-progress",
    "budget-form",
    "schedule-calendar",
    "schedule-today",
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
    "You are Audel, the user's personal-money agent. You coordinate three specialists and speak "
    "to the user with one voice. Money amounts are USD.\n\n"
    "You have specialist, schedule, and dashboard tools:\n"
    "- ask_budgeting(question): a budgeting specialist with live access to the user's bank "
    "transactions, spending categories, and budgets. It can also change categories and "
    "budgets. Use it for income, spending, cash flow, surplus, categories, and budgets.\n"
    "- ask_investing(question): an education-forward investing specialist with read-only "
    "access to the user's tastytrade brokerage account (holdings, balances, risk). It "
    "cannot place trades. Use it for portfolio, allocation, strategy, and market questions.\n"
    "- ask_goals(question): a goals specialist that creates and tracks the user's goals of "
    "outcome and routine goals — savings targets, streaks/habits, AND non-money numeric goals "
    "like fitness or strength (bench press, squat, a '1000 CLUB' total). It can create, "
    "update, and log progress. Use it whenever the user wants to set, group, or track a goal — "
    "including fitness/lifting goals. Recurring requests such as daily/weekly/monthly routines must "
    "go here even when they also say 'remind me'. Preserve requests to keep nudging until done or "
    "snoozed so the goals specialist can make the routine persistent. Do NOT refuse fitness goals; "
    "route them here as numeric goals.\n"
    "- list_reminders(): inspect active reminders before completing or changing one by name.\n"
    "- create_reminder(...): create a one-time scheduled reminder directly. For one-time requests "
    "that say 'keep reminding me', "
    "set repeat_until_completed=true and choose a nudge interval of at least 30 minutes; use "
    "60 minutes when the user does not specify. Persistent reminders require a date and time.\n"
    "- update_reminder(...): reschedule, snooze, or change whether an existing reminder keeps "
    "nudging. Resolve a reminder name with list_reminders first.\n"
    "- complete_reminder(id): acknowledge a reminder so persistent nudges stop. If the user refers "
    "to a reminder by name, list reminders first to find its id.\n"
    "- list_events(): inspect calendar events before changing or deleting one.\n"
    "- create_event(...): add a one-time calendar event with optional start/end times, location, "
    "and notes. Events are plans or appointments; reminders are tasks that notify the user.\n"
    "- update_event(id, ...), delete_event(id): change or remove an existing event. Resolve names "
    "with list_events first.\n"
    "- configure_dashboard(operation, widget_ids): configure the user's Dashboard tab. Use it "
    "when the user asks to add, remove, clear, reset, or replace dashboard widgets. "
    "Available widget_ids: left-to-spend, monthly-averages, spending-by-category, "
    "income-vs-expense, category-transactions, recent-transactions, "
    "unbudgeted-transactions, p2p-review, merchant-rules, "
    "manual-transaction, account-balances, account-sync, budget-progress, budget-form, "
    "schedule-calendar, schedule-today, "
    "portfolio-summary, portfolio-positions. Goal widgets are dynamic: use goal-name:NAME "
    "for an individual goal by exact name, goal-group:GROUP for a user-named goal group/category, "
    "goal:ID if you know the numeric goal id, or goal-section:daily|weekly|monthly|once|ongoing "
    "for goal cadence sections.\n\n"
    "Routing:\n"
    "- Spending limits for a category are ALWAYS budgets, even when phrased as a goal. Route daily, "
    "weekly, and monthly spending caps to ask_budgeting, never ask_goals.\n"
    "- Send each question to the specialist that owns it. Pass a clear, self-contained "
    "question — the specialist has no memory of the conversation. Resolve relative dates "
    "using the authoritative current time below and include absolute dates when delegating.\n"
    "- For questions that span domains (e.g. 'how much of my spare cash should I invest?'), "
    "call the specialists you need, then synthesize one answer.\n"
    "- Answer greetings, clarifications, and general questions yourself without a tool.\n"
    "- For dashboard customization requests, call configure_dashboard directly; do not route "
    "those to the budgeting/goals/investing specialists.\n"
    "- Reminder requests are schedule actions, not goals. Use the reminder tools directly. Never "
    "invent a missing date or time for a persistent reminder; ask one short clarifying question.\n"
    "- Calendar plans and appointments are events. Use event tools directly. Never invent a missing "
    "date; ask one short clarifying question. A time is optional because events may be all-day.\n"
    "- When a specialist reports it changed something, tell the user plainly.\n"
    "- Never invent portfolio holdings or spending numbers — get them from a specialist.\n"
    "- Be concise: short paragraphs, compact lists, amounts like $1,234."
)


def _current_time_context(
    timezone_name: str | None,
    *,
    now: datetime | None = None,
) -> str:
    """Return compact, authoritative user-local clock context for the model."""
    requested = (timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        user_timezone = ZoneInfo(requested)
    except ZoneInfoNotFoundError:
        requested = DEFAULT_TIMEZONE
        user_timezone = ZoneInfo(DEFAULT_TIMEZONE)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(user_timezone).replace(second=0, microsecond=0)
    return (
        f"Authoritative user-local time: {local.isoformat()} ({requested}). "
        "Use this for today, tomorrow, weekdays, and other relative dates."
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
        "name": "list_reminders",
        "description": "List active reminders, including persistent nudge settings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_reminder",
        "description": (
            "Create a scheduled reminder. Set repeat_until_completed for repeated nudges until the "
            "user checks it off. Persistent reminders require reminder_time and use a minimum "
            "30-minute interval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "scheduled_for": {"type": "string", "description": "YYYY-MM-DD"},
                "reminder_time": {"type": "string", "description": "Local HH:MM"},
                "notes": {"type": "string"},
                "repeat_until_completed": {"type": "boolean"},
                "nudge_interval_minutes": {"type": "integer", "minimum": 30, "maximum": 1440},
            },
            "required": ["title", "scheduled_for"],
        },
    },
    {
        "name": "update_reminder",
        "description": (
            "Reschedule or snooze an active reminder, or change its persistent nudge settings. "
            "Use list_reminders first when the user identifies it by name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "scheduled_for": {"type": "string", "description": "Optional YYYY-MM-DD"},
                "reminder_time": {"type": "string", "description": "Optional local HH:MM"},
                "repeat_until_completed": {"type": "boolean"},
                "nudge_interval_minutes": {"type": "integer", "minimum": 30, "maximum": 1440},
            },
            "required": ["id"],
        },
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder complete and stop any persistent notification nudges.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "list_events",
        "description": "List calendar events, optionally within an inclusive date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "Optional YYYY-MM-DD"},
                "end": {"type": "string", "description": "Optional YYYY-MM-DD"},
            },
            "required": [],
        },
    },
    {
        "name": "create_event",
        "description": "Create a one-time all-day or timed calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "scheduled_for": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": "string", "description": "Optional local HH:MM"},
                "end_time": {"type": "string", "description": "Optional local HH:MM"},
                "location": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["title", "scheduled_for"],
        },
    },
    {
        "name": "update_event",
        "description": "Update an existing calendar event by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "scheduled_for": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": ["string", "null"]},
                "end_time": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete a calendar event by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
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
        if name == "list_reminders":
            return {"reminders": schedule_svc.list_reminders(session)}
        if name == "create_reminder":
            payload = dict(tool_input or {})
            try:
                payload["scheduled_for"] = date.fromisoformat(payload.get("scheduled_for", ""))
            except (TypeError, ValueError):
                return {"error": "scheduled_for must be YYYY-MM-DD"}
            reminder = schedule_svc.create_reminder(session, payload)
            actions.append(f"Created reminder {reminder['title']}")
            return {"created": reminder}
        if name == "update_reminder":
            payload = dict(tool_input or {})
            reminder_id = payload.pop("id", None)
            if reminder_id is None:
                return {"error": "id is required"}
            if "scheduled_for" in payload:
                try:
                    payload["scheduled_for"] = date.fromisoformat(payload["scheduled_for"])
                except (TypeError, ValueError):
                    return {"error": "scheduled_for must be YYYY-MM-DD"}
            reminder = schedule_svc.update_reminder(session, int(reminder_id), payload)
            if reminder is None:
                return {"error": "reminder not found"}
            actions.append(f"Updated reminder {reminder['title']}")
            return {"updated": reminder}
        if name == "complete_reminder":
            reminder_id = (tool_input or {}).get("id")
            if reminder_id is None:
                return {"error": "id is required"}
            reminder = schedule_svc.update_reminder(session, int(reminder_id), {"completed": True})
            if reminder is None:
                return {"error": "reminder not found"}
            actions.append(f"Completed reminder {reminder['title']}")
            return {"completed": reminder}
        if name == "list_events":
            payload = tool_input or {}
            try:
                start = date.fromisoformat(payload["start"]) if payload.get("start") else None
                end = date.fromisoformat(payload["end"]) if payload.get("end") else None
            except (TypeError, ValueError):
                return {"error": "start and end must be YYYY-MM-DD"}
            return {"events": schedule_svc.list_events(session, start, end)}
        if name == "create_event":
            payload = dict(tool_input or {})
            try:
                payload["scheduled_for"] = date.fromisoformat(payload.get("scheduled_for", ""))
            except (TypeError, ValueError):
                return {"error": "scheduled_for must be YYYY-MM-DD"}
            event = schedule_svc.create_event(session, payload)
            actions.append(f"Created event {event['title']}")
            return {"created": event}
        if name == "update_event":
            payload = dict(tool_input or {})
            event_id = payload.pop("id", None)
            if event_id is None:
                return {"error": "id is required"}
            if "scheduled_for" in payload:
                try:
                    payload["scheduled_for"] = date.fromisoformat(payload["scheduled_for"])
                except (TypeError, ValueError):
                    return {"error": "scheduled_for must be YYYY-MM-DD"}
            event = schedule_svc.update_event(session, int(event_id), payload)
            if event is None:
                return {"error": "event not found"}
            actions.append(f"Updated event {event['title']}")
            return {"updated": event}
        if name == "delete_event":
            event_id = (tool_input or {}).get("id")
            if event_id is None:
                return {"error": "id is required"}
            if not schedule_svc.delete_event(session, int(event_id)):
                return {"error": "event not found"}
            actions.append("Deleted calendar event")
            return {"deleted": True}
        if name == "configure_dashboard":
            return _dashboard_action(tool_input or {}, actions, ui_actions)
        return {"error": f"unknown tool {name}"}
    except Exception as exc:  # noqa: BLE001 — surface specialist errors back to the model
        return {"error": str(exc)}


def run_copilot(
    session,
    messages: list[dict],
    client=None,
    timezone_name: str | None = None,
) -> dict:
    """Run the orchestrator for one user turn; returns {reply, actions, refresh, ui_actions}."""
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    actions: list[str] = []
    ui_actions: list[dict] = []
    system = f"{SYSTEM}\n\n{_current_time_context(timezone_name)}"

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=settings.assistant_model, max_tokens=MAX_OUTPUT_TOKENS,
            system=system, tools=TOOLS, messages=convo,
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
