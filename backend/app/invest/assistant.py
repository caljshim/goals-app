"""Investing copilot: Claude with a read-only portfolio tool (phase 1).

Same manual tool-loop pattern as ../finance. Conservative, education-forward stance
per README. No order placement of any kind in this phase.
"""
import asyncio
import json

import anthropic

from app.config import get_settings
from app.invest.tasty import fetch_portfolio, get_session

MAX_TOOL_ITERATIONS = 4
MAX_OUTPUT_TOKENS = 2048

SYSTEM = (
    "You are a careful, education-forward investing copilot inside the user's personal "
    "investing app, connected read-only to their tastytrade account. You cannot place, "
    "modify, or cancel orders — analysis and advice only.\n\n"
    "Stance:\n"
    "- Default to boring, evidence-backed investing: broad low-cost index ETFs, dollar-cost "
    "averaging sized off monthly surplus, long horizons. Options and active trading are "
    "advanced opt-ins the user must raise themselves — and even then, explain the risks first.\n"
    "- Always explain WHY — the user is learning. Define jargon in one clause the first time "
    "it appears.\n"
    "- Be honest about uncertainty; never present a prediction as a fact. You are not a "
    "licensed financial advisor and should say so when giving significant recommendations.\n"
    "- Call get_portfolio before discussing their holdings, allocation, or risk.\n"
    "- Be concise: short paragraphs, compact lists, amounts like $1,234."
)

TOOLS = [
    {
        "name": "get_portfolio",
        "description": (
            "The user's live tastytrade portfolio: accounts with net liquidating value, cash, "
            "buying power, and every open position (symbol, quantity, open price, current "
            "price, market value). Call before discussing holdings, allocation, or risk."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _get_portfolio() -> dict:
    # run_assistant executes in a worker thread (sync FastAPI route), so a private
    # event loop per call is safe; the SDK is async-only.
    return asyncio.run(fetch_portfolio(get_session()))


def run_assistant(messages: list[dict], client=None) -> dict:
    """Run one assistant turn; returns {reply}."""
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    convo = [{"role": m["role"], "content": m["content"]} for m in messages]
    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=settings.assistant_model, max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM, tools=TOOLS, messages=convo,
        )
        if resp.stop_reason != "tool_use":
            return {"reply": "".join(b.text for b in resp.content if b.type == "text").strip()}

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                data = _get_portfolio() if b.name == "get_portfolio" else {"error": f"unknown tool {b.name}"}
            except Exception as exc:  # noqa: BLE001 — surface adapter errors to the model
                data = {"error": str(exc)}
            results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": json.dumps(data, default=str),
            })
        convo.append({"role": "user", "content": results})

    return {"reply": "I took several steps — could you re-ask or narrow that down a bit?"}
