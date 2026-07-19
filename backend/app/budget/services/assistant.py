"""AI finance assistant: a tool-using agent over the user's transactions and budgets.

Runs a manual tool-use loop against the Anthropic Messages API. Tools read the
financial overview / transactions and mutate categories / budgets. Kept model-
agnostic via `settings.assistant_model` (a weak/cheap model by default).
"""
import json
from datetime import date

import anthropic
from sqlmodel import Session, select

from app.budget.categories import effective_category, is_incoming_p2p, is_p2p, is_transfer
from app.config import get_settings
from app.budget.models import Budget, Category, Transaction
from app.budget.services import rules as rules_svc
from app.budget.services.rules import load_rules
from app.budget.services.summary import data_covered_months

MAX_TOOL_ITERATIONS = 6
MAX_OUTPUT_TOKENS = 2048
AVG_MONTHS = 3

SYSTEM = (
    "You are a friendly personal-finance assistant embedded in the user's finance tracker app. "
    "All amounts are in USD. Categories use UPPER_SNAKE_CASE (e.g. FOOD_AND_DRINK). "
    "Credit-card payments and own-account transfers are already excluded from spending and "
    "income — never try to recategorize them. Zelle/Venmo with real people is netted into "
    "spending totals automatically (incoming reimbursements reduce it, outgoing payments add "
    "to it); avg_monthly_p2p_net in get_overview shows that net (negative = net reimbursed).\n\n"
    "You have tools to read the user's financial overview and individual transactions, "
    "recategorize transactions, and set monthly budgets.\n\n"
    "Guidelines:\n"
    "- Call get_overview before proposing a budget OR recategorizing — it returns "
    "known_categories, the user's real spending buckets.\n"
    "- ALWAYS reuse a category from known_categories when one reasonably fits. Only invent a new "
    "UPPER_SNAKE_CASE category when nothing in the list applies — don't fragment (e.g. a "
    "restaurant is FOOD_AND_DRINK, not a new DINING category).\n"
    "- You have FULL control over budgets: create, update, or delete them directly with "
    "set_budget / delete_budget whenever the user's intent is clear — no confirmation needed. "
    "Always summarize what you changed. Budget the categories the user actually spends in, and "
    "keep total budgeted spending at or below average monthly income so there is room to save.\n"
    "- To fix categorization efficiently, prefer set_merchant_rule — it makes a category stick "
    "for a whole merchant (past AND future), so the user isn't re-fixing it every sync. Use "
    "bootstrap_rules once to convert their existing categorizations into rules. Use recategorize "
    "only for a genuine one-off exception on a single transaction. Map to known_categories.\n"
    "- To introduce a genuinely new bucket the user wants, use add_category; recategorize and "
    "set_budget also register any new category automatically. Categories persist.\n"
    "- Be concise. Use short paragraphs or compact lists. Show amounts like $1,234."
)


def _normalize_category(name: str) -> str:
    return "_".join((name or "").strip().upper().split())


def _ensure_category(session: Session, name: str) -> None:
    """Add a category to the DB if it's new (caller commits)."""
    if name and not session.exec(select(Category).where(Category.name == name)).first():
        session.add(Category(name=name))


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _prev_complete_months(n: int) -> list[str]:
    """The `n` most recent complete months (excludes the current, partial month)."""
    today = date.today()
    year, mon = today.year, today.month
    out = []
    for _ in range(n):
        mon -= 1
        if mon == 0:
            mon, year = 12, year - 1
        out.append(f"{year:04d}-{mon:02d}")
    return out


# --- tool handlers: each returns (result_dict, action_str_or_None) -------------

def _overview(session: Session) -> tuple[dict, None]:
    # Average only over complete months the data fully covers (a partial leading
    # month would understate the averages), and divide by that count — not a fixed 3.
    candidate = _prev_complete_months(AVG_MONTHS)
    covered = data_covered_months(session, candidate) or candidate
    months = set(covered)
    divisor = len(months)

    spend: dict[str, float] = {}
    income_total = 0.0
    p2p_net = 0.0
    in_use: set[str] = set()
    # Linked reimbursements reduce the expense they point at (capped at its amount),
    # in that expense's month — mirror of services.summary so the copilot's numbers
    # match the dashboard.
    txns = session.exec(select(Transaction)).all()
    rules = load_rules(session)
    by_id = {t.id: t for t in txns}
    reimbursed: dict[int, float] = {}
    for t in txns:
        target = by_id.get(t.reimburses_transaction_id) if t.reimburses_transaction_id else None
        if target is not None and target.amount > 0:
            reimbursed[target.id] = reimbursed.get(target.id, 0.0) + -t.amount

    for t in txns:
        in_window = _month_key(t.date) in months
        # Linked reimbursement: folded into its target expense below.
        if t.reimburses_transaction_id is not None:
            continue
        # Incoming Zelle/Venmo (money in): a reimbursement or a plain transfer.
        if is_incoming_p2p(t):
            cat = effective_category(t)
            if cat == "TRANSFER_IN":
                if in_window:      # kept as a transfer / unreviewed — net the total
                    p2p_net += t.amount
            else:
                in_use.add(cat)
                if in_window:      # assigned to a category — reduce that category
                    spend[cat] = spend.get(cat, 0.0) + t.amount
            continue
        if is_transfer(t):
            # Outgoing Zelle/Venmo kept as a transfer nets the total; other transfers
            # (card payments, own-account moves) stay excluded.
            if is_p2p(t) and in_window:
                p2p_net += t.amount
            continue
        ec = effective_category(t, rules)
        in_use.add(ec)
        if not in_window:
            continue
        if t.amount >= 0:
            net = t.amount - min(reimbursed.get(t.id, 0.0), t.amount)
            spend[ec] = spend.get(ec, 0.0) + net
        else:
            income_total += -t.amount
    by_category = sorted(
        ({"category": c, "avg_monthly": round(v / divisor, 2)} for c, v in spend.items()),
        key=lambda x: x["avg_monthly"], reverse=True,
    )
    budgets = session.exec(select(Budget)).all()
    db_categories = {c.name for c in session.exec(select(Category)).all()}
    known = sorted(db_categories | (in_use - {"INCOME"}))
    return {
        "window_months": sorted(months),
        "months_averaged": divisor,
        "avg_monthly_income": round(income_total / divisor, 2),
        "avg_monthly_spend_total": round((sum(spend.values()) + p2p_net) / divisor, 2),
        "avg_monthly_p2p_net": round(p2p_net / divisor, 2),
        "avg_monthly_by_category": by_category,
        "current_budgets": [{"category": b.category, "monthly_limit": b.monthly_limit} for b in budgets],
        "known_categories": known,
    }, None


def _list_transactions(session: Session, month=None, category=None, limit=50) -> tuple[dict, None]:
    limit = min(max(int(limit or 50), 1), 200)
    cat = _normalize_category(category) if category else None
    rows = session.exec(
        select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())
    ).all()
    rules = load_rules(session)
    out = []
    for t in rows:
        if is_transfer(t):
            continue
        ec = effective_category(t, rules)
        if (month and _month_key(t.date) != month) or (cat and ec != cat):
            continue
        out.append({
            "id": t.id, "date": t.date.isoformat(),
            "name": t.merchant_name or t.name, "amount": t.amount, "category": ec,
        })
        if len(out) >= limit:
            break
    return {"transactions": out, "count": len(out)}, None


def _recategorize(session: Session, transaction_ids, category) -> tuple[dict, str | None]:
    cat = _normalize_category(category)
    if not cat:
        return {"error": "category is required"}, None
    updated = 0
    skipped_payments: list[int] = []
    for tid in transaction_ids or []:
        t = session.get(Transaction, int(tid))
        if not t:
            continue
        # Credit-card payment legs are money movement, never spending — recategorizing
        # them would double-count the purchases already on the card. Immutable.
        if t.category in ("LOAN_PAYMENTS", "LOAN_DISBURSEMENTS"):
            skipped_payments.append(t.id)
            continue
        t.user_category = cat
        session.add(t)
        updated += 1
    if updated:
        _ensure_category(session, cat)
    session.commit()
    result: dict = {"updated": updated, "category": cat}
    if skipped_payments:
        result["skipped_payment_ids"] = skipped_payments
        result["note"] = "credit-card payments cannot be recategorized (they are transfers, not spending)"
    action = f"Recategorized {updated} transaction(s) → {cat}" if updated else None
    return result, action


def _delete_budget(session: Session, category) -> tuple[dict, str | None]:
    cat = _normalize_category(category)
    if not cat:
        return {"error": "category is required"}, None
    budget = session.exec(select(Budget).where(Budget.category == cat)).first()
    if not budget:
        return {"error": f"no budget exists for {cat}"}, None
    session.delete(budget)
    session.commit()
    return {"category": cat, "deleted": True}, f"Deleted budget {cat}"


def _add_category(session: Session, name) -> tuple[dict, str | None]:
    cat = _normalize_category(name)
    if not cat:
        return {"error": "name is required"}, None
    if session.exec(select(Category).where(Category.name == cat)).first():
        return {"category": cat, "created": False}, None
    session.add(Category(name=cat))
    session.commit()
    return {"category": cat, "created": True}, f"Added category {cat}"


def _set_merchant_rule(session: Session, merchant, category) -> tuple[dict, str | None]:
    try:
        rule = rules_svc.set_merchant_rule(session, merchant or "", category or "")
    except ValueError as exc:
        return {"error": str(exc)}, None
    return (
        {"merchant": rule.merchant, "category": rule.category},
        f"Rule: {rule.merchant} → {rule.category}",
    )


def _list_merchant_rules(session: Session) -> tuple[dict, None]:
    rules = rules_svc.list_rules(session)
    return {"rules": rules, "count": len(rules)}, None


def _bootstrap_rules(session: Session) -> tuple[dict, str | None]:
    out = rules_svc.bootstrap_rules(session)
    action = f"Created {out['count']} merchant rule(s) from history" if out["count"] else None
    return out, action


def _set_budget(session: Session, category, monthly_limit) -> tuple[dict, str | None]:
    cat = _normalize_category(category)
    if not cat:
        return {"error": "category is required"}, None
    limit = float(monthly_limit)
    existing = session.exec(select(Budget).where(Budget.category == cat)).first()
    verb = "Updated" if existing else "Added"
    if existing:
        existing.monthly_limit = limit
        session.add(existing)
    else:
        session.add(Budget(category=cat, monthly_limit=limit))
    _ensure_category(session, cat)
    session.commit()
    return {"category": cat, "monthly_limit": limit, "created": not existing}, f"{verb} budget {cat} = ${limit:,.0f}"


TOOLS = [
    {
        "name": "get_overview",
        "description": (
            "Financial overview: average monthly income, spend total, and per-category spend, "
            "averaged over recent COMPLETE months the data fully covers (window_months lists them; "
            "months_averaged is the count — a partial leading month is excluded so figures aren't "
            "understated). Credit-card payments/own-account transfers excluded; Zelle/Venmo with "
            "people is netted into avg_monthly_spend_total (avg_monthly_p2p_net shows the net). "
            "Also current budgets. Call before proposing a budget."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_transactions",
        "description": (
            "List individual transactions (newest first, transfers excluded) to review "
            "categories. Optionally filter by month (YYYY-MM) or category (UPPER_SNAKE_CASE)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "YYYY-MM"},
                "category": {"type": "string", "description": "UPPER_SNAKE_CASE category filter"},
                "limit": {"type": "integer", "description": "Max rows (default 50, max 200)"},
            },
            "required": [],
        },
    },
    {
        "name": "recategorize",
        "description": (
            "Change the category of one or more transactions. Prefer a category from "
            "get_overview's known_categories; only invent a new UPPER_SNAKE_CASE name when nothing "
            "fits. Summarize what you changed afterward."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_ids": {"type": "array", "items": {"type": "integer"}},
                "category": {"type": "string"},
            },
            "required": ["transaction_ids", "category"],
        },
    },
    {
        "name": "set_merchant_rule",
        "description": (
            "Create/update a MERCHANT rule so a category sticks for ALL of a merchant's past & "
            "future transactions — the efficient way to fix categories (prefer this over "
            "recategorize for a merchant that recurs). merchant is matched case-insensitively on "
            "the cleaned merchant name. Clears any one-off overrides on that merchant. Cannot map "
            "to a transfer category. Use recategorize only for a genuine one-off exception."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "merchant": {"type": "string", "description": "Merchant name, e.g. Safeway"},
                "category": {"type": "string", "description": "UPPER_SNAKE_CASE custom category"},
            },
            "required": ["merchant", "category"],
        },
    },
    {
        "name": "list_merchant_rules",
        "description": "List existing merchant→category rules.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "bootstrap_rules",
        "description": (
            "Scan transaction history and create merchant rules from the user's existing "
            "categorizations (majority category per merchant). Run once to convert past manual "
            "recategorizations into rules that apply going forward. Summarize what was created."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_budget",
        "description": (
            "Create or update a monthly budget limit for a category (UPPER_SNAKE_CASE). Apply "
            "directly when the user's intent is clear; summarize changes afterward."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "monthly_limit": {"type": "number"},
            },
            "required": ["category", "monthly_limit"],
        },
    },
    {
        "name": "delete_budget",
        "description": "Delete the budget for a category (UPPER_SNAKE_CASE).",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category"],
        },
    },
    {
        "name": "add_category",
        "description": (
            "Add a new spending category (UPPER_SNAKE_CASE) to the user's category list. Use only "
            "when the user wants a bucket that doesn't exist yet in known_categories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]

_HANDLERS = {
    "get_overview": lambda s, i: _overview(s),
    "list_transactions": lambda s, i: _list_transactions(s, i.get("month"), i.get("category"), i.get("limit", 50)),
    "recategorize": lambda s, i: _recategorize(s, i.get("transaction_ids", []), i.get("category", "")),
    "set_merchant_rule": lambda s, i: _set_merchant_rule(s, i.get("merchant", ""), i.get("category", "")),
    "list_merchant_rules": lambda s, i: _list_merchant_rules(s),
    "bootstrap_rules": lambda s, i: _bootstrap_rules(s),
    "set_budget": lambda s, i: _set_budget(s, i.get("category", ""), i.get("monthly_limit")),
    "delete_budget": lambda s, i: _delete_budget(s, i.get("category", "")),
    "add_category": lambda s, i: _add_category(s, i.get("name", "")),
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
    """Run the agent loop for one user turn; returns {reply, actions, refresh}."""
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
            model=model, max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM, tools=TOOLS, messages=convo,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not text:
                # The weak/cheap model sometimes ends a tool turn with no text, or the
                # reply is cut off by max_tokens. Never surface a blank reply.
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
