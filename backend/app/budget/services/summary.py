from collections import defaultdict
from datetime import date

from sqlmodel import Session, select

from app.budget.categories import effective_category, is_p2p, is_transfer
from app.budget.models import Budget, Transaction


def _month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def data_covered_months(session: Session, months: list[str]) -> list[str]:
    """From candidate YYYY-MM months, keep only those the transaction history fully
    covers — i.e. data begins on or before the first of the month. Excludes a partial
    leading month (e.g. Plaid pulled from mid-April) so averages aren't dragged down."""
    earliest = session.exec(select(Transaction.date).order_by(Transaction.date)).first()
    if earliest is None:
        return []
    return [mk for mk in months if date(int(mk[:4]), int(mk[5:7]), 1) >= earliest]


def _prev_months(month: str, n: int) -> list[str]:
    year, mon = (int(x) for x in month.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            mon = 12
            year -= 1
    return list(reversed(out))


def build_summary(session: Session, month: str) -> dict:
    txns = session.exec(select(Transaction)).all()

    spend = defaultdict(float)
    income_total = 0.0
    expense_total = 0.0
    trend = {m: {"income": 0.0, "expense": 0.0} for m in _prev_months(month, 6)}

    for t in txns:
        if is_transfer(t):
            # Zelle/Venmo with real people changes true spending: incoming (−) is a
            # reimbursement, outgoing (+) is paying your share. Totals only — never
            # attributed to a category. Other transfers (card payments, own-account
            # moves) stay fully excluded.
            if is_p2p(t):
                mk = _month_key(t.date)
                if mk == month:
                    expense_total += t.amount
                if mk in trend:
                    trend[mk]["expense"] += t.amount
            continue
        mk = _month_key(t.date)
        if t.amount >= 0:
            if mk == month:
                spend[effective_category(t)] += t.amount
                expense_total += t.amount
            if mk in trend:
                trend[mk]["expense"] += t.amount
        else:
            if mk == month:
                income_total += -t.amount
            if mk in trend:
                trend[mk]["income"] += -t.amount

    spending_by_category = sorted(
        [{"category": c, "total": round(v, 2)} for c, v in spend.items()],
        key=lambda x: x["total"], reverse=True,
    )

    budgets = session.exec(select(Budget)).all()
    budget_progress = []
    for b in budgets:
        spent = round(spend.get(b.category, 0.0), 2)
        remaining = round(b.monthly_limit - spent, 2)
        pct = round(spent / b.monthly_limit * 100, 1) if b.monthly_limit else 0.0
        budget_progress.append({
            "category": b.category, "limit": b.monthly_limit,
            "spent": spent, "remaining": remaining, "pct": pct,
        })

    monthly_trend = [
        {"month": m, "income": round(v["income"], 2), "expense": round(v["expense"], 2)}
        for m, v in trend.items()
    ]

    # Complete (non-current) months the data fully covers — accurate months to average.
    complete_months = data_covered_months(session, [m for m in trend if m != month])

    return {
        "spending_by_category": spending_by_category,
        "income_total": round(income_total, 2),
        "expense_total": round(expense_total, 2),
        "net": round(income_total - expense_total, 2),
        "monthly_trend": monthly_trend,
        "budget_progress": budget_progress,
        "complete_months": complete_months,
    }
