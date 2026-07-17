"""Copilot orchestrator: one agent that delegates to a budgeting or investing specialist.

Same manual tool-use loop as the specialists, but its only tools are the two
specialists themselves — `ask_budgeting` and `ask_investing`. Each specialist is
stateless per call: the orchestrator owns the conversation and formulates a single
question for the specialist. Budgeting actions bubble up so the frontend refreshes.
"""
import json

import anthropic

from app.budget.services.assistant import run_assistant as run_budgeting
from app.config import get_settings
from app.invest.assistant import run_assistant as run_investing

MAX_TOOL_ITERATIONS = 4
MAX_OUTPUT_TOKENS = 2048

SYSTEM = (
    "You are the user's personal-money copilot. You coordinate two specialists and speak "
    "to the user with one voice. All amounts are USD.\n\n"
    "You have two tools:\n"
    "- ask_budgeting(question): a budgeting specialist with live access to the user's bank "
    "transactions, spending categories, and budgets. It can also change categories and "
    "budgets. Use it for income, spending, cash flow, surplus, categories, and budgets.\n"
    "- ask_investing(question): an education-forward investing specialist with read-only "
    "access to the user's tastytrade brokerage account (holdings, balances, risk). It "
    "cannot place trades. Use it for portfolio, allocation, strategy, and market questions.\n\n"
    "Routing:\n"
    "- Send each question to the specialist that owns the data. Pass a clear, self-contained "
    "question — the specialist has no memory of the conversation.\n"
    "- For questions that span both domains (e.g. 'how much of my spare cash should I "
    "invest?'), call BOTH: get the budgeting figure first, then hand it to the investing "
    "specialist, and synthesize one answer.\n"
    "- Answer greetings, clarifications, and general money questions yourself without a tool.\n"
    "- When the budgeting specialist reports it changed something, tell the user plainly.\n"
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
]


def _dispatch(session, name: str, tool_input: dict, client, actions: list[str]) -> dict:
    """Run one delegation tool; specialist errors become error results, never raise."""
    question = (tool_input or {}).get("question", "")
    try:
        if name == "ask_budgeting":
            out = run_budgeting(session, [{"role": "user", "content": question}], client=client)
            actions.extend(out.get("actions", []))
            return {"reply": out.get("reply", ""), "actions": out.get("actions", [])}
        if name == "ask_investing":
            out = run_investing([{"role": "user", "content": question}], client=client)
            return {"reply": out.get("reply", "")}
        return {"error": f"unknown tool {name}"}
    except Exception as exc:  # noqa: BLE001 — surface specialist errors back to the model
        return {"error": str(exc)}


def run_copilot(session, messages: list[dict], client=None) -> dict:
    """Run the orchestrator for one user turn; returns {reply, actions, refresh}."""
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    actions: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=settings.assistant_model, max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM, tools=TOOLS, messages=convo,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"reply": text, "actions": actions, "refresh": bool(actions)}

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            data = _dispatch(session, b.name, b.input or {}, client, actions)
            results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": json.dumps(data, default=str),
            })
        convo.append({"role": "user", "content": results})

    return {
        "reply": "I took several steps — could you re-ask or narrow that down a bit?",
        "actions": actions, "refresh": bool(actions),
    }
