from collections import defaultdict
from calendar import monthrange
from datetime import date, timedelta

from sqlmodel import Session, select

from app.budget.categories import effective_category, is_incoming_p2p, is_p2p, is_transfer
from app.budget.models import Budget, Transaction
from app.budget.services.rules import load_rules


def _month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def budget_window(period: str, as_of: date) -> tuple[date, date]:
    """Inclusive window for a daily, Sunday-start weekly, or monthly budget."""
    if period == "daily":
        return as_of, as_of
    if period == "weekly":
        start = as_of - timedelta(days=(as_of.weekday() + 1) % 7)
        return start, start + timedelta(days=6)
    start = as_of.replace(day=1)
    return start, as_of.replace(day=monthrange(as_of.year, as_of.month)[1])


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


def spend_by_category_in_range(
    session: Session, start, end, account_ids: set[int] | None = None
) -> dict[str, float]:
    """Reimbursement/rule-aware spend per category over an inclusive [start, end] date
    range — the same accounting as build_summary's monthly spend, for any window
    (used by period-scoped spend-cap goals)."""
    txns = session.exec(select(Transaction)).all()
    rules = load_rules(session)
    by_id = {t.id: t for t in txns}
    reimbursed = defaultdict(float)
    for t in txns:
        target = by_id.get(t.reimburses_transaction_id) if t.reimburses_transaction_id else None
        if target is not None and target.amount > 0:
            reimbursed[target.id] += -t.amount

    spend = defaultdict(float)
    for t in txns:
        if not (start <= t.date <= end):
            continue
        if account_ids and t.account_id not in account_ids:
            continue
        if t.reimburses_transaction_id is not None:
            continue  # folded into the target expense
        if is_incoming_p2p(t):
            cat = effective_category(t, rules)
            if cat != "TRANSFER_IN":          # category-only reimbursement reduces its category
                spend[cat] += t.amount
            continue
        if is_transfer(t):
            continue
        if t.amount >= 0:
            net = t.amount - min(reimbursed.get(t.id, 0.0), t.amount)
            spend[effective_category(t, rules)] += net
    return {c: round(v, 2) for c, v in spend.items()}


def cash_flow_in_range(
    session: Session, start, end, account_ids: set[int] | None = None
) -> tuple[float, float]:
    """Return reimbursement-aware (income, expense) for a financial-goal window."""
    txns = session.exec(select(Transaction)).all()
    rules = load_rules(session)
    by_id = {t.id: t for t in txns}
    reimbursed = defaultdict(float)
    for t in txns:
        target = by_id.get(t.reimburses_transaction_id) if t.reimburses_transaction_id else None
        if target is not None and target.amount > 0:
            reimbursed[target.id] += -t.amount
    income = expense = 0.0
    for t in txns:
        if not (start <= t.date <= end) or (account_ids and t.account_id not in account_ids):
            continue
        if t.reimburses_transaction_id is not None:
            continue
        if is_incoming_p2p(t):
            expense += t.amount
        elif is_transfer(t):
            if is_p2p(t):
                expense += t.amount
        elif t.amount >= 0:
            expense += t.amount - min(reimbursed.get(t.id, 0.0), t.amount)
        else:
            income += -t.amount
    return round(income, 2), round(expense, 2)


def build_summary(session: Session, month: str, as_of: date | None = None) -> dict:
    txns = session.exec(select(Transaction)).all()
    rules = load_rules(session)

    spend = defaultdict(float)
    income_total = 0.0
    expense_total = 0.0
    trend = {m: {"income": 0.0, "expense": 0.0} for m in _prev_months(month, 6)}

    # A linked incoming Zelle reimburses the expense it points at. Sum those
    # reimbursements per expense up front (capped later at the expense amount) so the
    # expense's own row nets them out — which lands the credit in the *expense's*
    # month and category, regardless of when the Zelle arrived.
    by_id = {t.id: t for t in txns}
    reimbursed = defaultdict(float)
    for t in txns:
        target = by_id.get(t.reimburses_transaction_id) if t.reimburses_transaction_id else None
        if target is not None and target.amount > 0:
            reimbursed[target.id] += -t.amount  # incoming amounts are negative

    for t in txns:
        mk = _month_key(t.date)
        # Linked reimbursement: its effect is folded into the target expense below.
        if t.reimburses_transaction_id is not None:
            continue
        # Incoming Zelle/Venmo (money in): a reimbursement or a plain transfer.
        if is_incoming_p2p(t):
            cat = effective_category(t)
            if cat == "TRANSFER_IN":
                # Not yet reviewed, or kept as a transfer — net the global total only.
                if mk == month:
                    expense_total += t.amount
                if mk in trend:
                    trend[mk]["expense"] += t.amount
            else:
                # Assigned to a spending category — reduce that category this month.
                if mk == month:
                    spend[cat] += t.amount
                    expense_total += t.amount
                if mk in trend:
                    trend[mk]["expense"] += t.amount
            continue
        if is_transfer(t):
            # Outgoing Zelle/Venmo kept as a transfer nets the total (incoming handled
            # above); other transfers (card payments, own-account moves) stay excluded.
            if is_p2p(t):
                if mk == month:
                    expense_total += t.amount
                if mk in trend:
                    trend[mk]["expense"] += t.amount
            continue
        if t.amount >= 0:
            # Real expense — subtract any reimbursements pointed at it (capped so the
            # expense never nets below zero).
            net = t.amount - min(reimbursed.get(t.id, 0.0), t.amount)
            if mk == month:
                spend[effective_category(t, rules)] += net
                expense_total += net
            if mk in trend:
                trend[mk]["expense"] += net
        else:
            if mk == month:
                income_total += -t.amount
            if mk in trend:
                trend[mk]["income"] += -t.amount

    spending_by_category = sorted(
        [{"category": c, "total": round(v, 2)} for c, v in spend.items()],
        key=lambda x: x["total"], reverse=True,
    )

    budgets = session.exec(select(Budget).order_by(Budget.period, Budget.category)).all()
    budget_progress = []
    today = as_of or date.today()
    requested_year, requested_month = (int(value) for value in month.split("-"))
    monthly_as_of = date(requested_year, requested_month, min(
        today.day, monthrange(requested_year, requested_month)[1]
    ))
    spend_by_period: dict[str, dict[str, float]] = {}
    for b in budgets:
        period = b.period if b.period in {"daily", "weekly", "monthly"} else "monthly"
        anchor = monthly_as_of if period == "monthly" else today
        start, end = budget_window(period, anchor)
        if period not in spend_by_period:
            spend_by_period[period] = spend_by_category_in_range(session, start, end)
        spent = round(spend_by_period[period].get(b.category, 0.0), 2)
        remaining = round(b.monthly_limit - spent, 2)
        pct = round(spent / b.monthly_limit * 100, 1) if b.monthly_limit else 0.0
        budget_progress.append({
            "budget_id": b.id, "category": b.category, "period": period,
            "window_start": start, "window_end": end, "limit": b.monthly_limit,
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
