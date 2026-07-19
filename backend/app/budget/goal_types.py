"""Polymorphic goal types.

Each goal `kind` is a GoalType that knows how to compute its own progress from a
Goal row plus a GoalContext (live account balances and this month's category spend).
Adding a new goal type = add a GoalType subclass and register it — no edits to
callers or a growing conditional."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.budget.models import Goal


def period_window(period: str, today: date) -> tuple[date | None, date | None]:
    """Inclusive [start, end] of the current period for a cadence, or (None, None) for
    a one-time goal. Weeks run Sunday–Saturday (US)."""
    if period == "daily":
        return today, today
    if period == "weekly":
        start = today - timedelta(days=(today.weekday() + 1) % 7)  # weekday(): Mon=0..Sun=6
        return start, start + timedelta(days=6)
    if period == "monthly":
        start = today.replace(day=1)
        nxt = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        return start, nxt - timedelta(days=1)
    return None, None


def goal_period_start(goal: Goal, now: datetime | None = None) -> date | None:
    """Start date of a goal's user-configured reset cycle."""
    if goal.period in (None, "once"):
        return None
    now = now or datetime.now()
    try:
        hour, minute = (int(part) for part in (goal.reset_time or "00:00").split(":"))
        reset_at = time(hour, minute)
    except (TypeError, ValueError):
        reset_at = time(0, 0)
    if goal.period == "daily":
        boundary = datetime.combine(now.date(), reset_at)
        return (boundary if now >= boundary else boundary - timedelta(days=1)).date()
    if goal.period == "weekly":
        weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
        target = weekdays.get(goal.weekly_reset_day or "sunday", 6)
        boundary_date = now.date() - timedelta(days=(now.weekday() - target) % 7)
        boundary = datetime.combine(boundary_date, reset_at)
        return (boundary if now >= boundary else boundary - timedelta(days=7)).date()
    if goal.period == "monthly":
        day = max(1, min(goal.monthly_reset_day or 1, 28))
        boundary = datetime.combine(now.date().replace(day=day), reset_at)
        if now >= boundary:
            return boundary.date()
        previous = (now.date().replace(day=1) - timedelta(days=1)).replace(day=day)
        return previous
    if goal.period == "interval":
        interval = max(1, goal.interval_days or 1)
        anchor = datetime.combine(goal.created_at.date(), reset_at)
        if now < anchor:
            return anchor.date()
        return (anchor + timedelta(days=((now - anchor).days // interval) * interval)).date()
    return None


@dataclass
class GoalContext:
    """Live data goal types resolve against, built once per request (services.goals).
    category_spend_by_period maps a cadence ("daily"/"weekly"/"monthly") to that window's
    reimbursement-aware spend per category."""
    account_balances: dict[int, float]
    account_names: dict[int, str]
    category_spend_by_period: dict[str, dict[str, float]]
    today: date


def _pct(current: float, target: float | None) -> float | None:
    return round(current / target * 100, 1) if target else None


def _manual_current(goal: Goal, ctx: GoalContext) -> float:
    """Manual value, honoring cadence: for a recurring goal the stored `current` only
    counts while its period_anchor is the current period (else the period rolled over
    and it reads 0 until the next contribution resets it — see services.goals)."""
    if goal.period in (None, "once"):
        return goal.current or 0.0
    start = goal_period_start(goal)
    return (goal.current or 0.0) if goal.period_anchor == start else 0.0


class GoalType(ABC):
    kind: str
    unit: str = ""

    @abstractmethod
    def progress(self, goal: Goal, ctx: GoalContext) -> dict:
        """Return the computed view of this goal: current_value, pct, status, unit,
        linked_label, days, best_days (keys not relevant to a kind are None)."""


class SaveGoalType(GoalType):
    kind = "save"
    unit = "$"

    def progress(self, goal, ctx):
        if goal.account_id is not None:
            current = ctx.account_balances.get(goal.account_id, 0.0)
            label = ctx.account_names.get(goal.account_id)
        else:
            current = _manual_current(goal, ctx)
            label = None
        status = "reached" if (goal.target and current >= goal.target) else "active"
        return {"current_value": round(current, 2), "pct": _pct(current, goal.target),
                "status": status, "unit": self.unit, "linked_label": label,
                "days": None, "best_days": None}


class SpendCapGoalType(GoalType):
    kind = "spend_cap"
    unit = "$"

    def progress(self, goal, ctx):
        period = goal.period if goal.period in ("daily", "weekly", "monthly") else "monthly"
        current = ctx.category_spend_by_period.get(period, {}).get(goal.category, 0.0)
        status = "over" if (goal.target and current > goal.target) else "under"
        return {"current_value": round(current, 2), "pct": _pct(current, goal.target),
                "status": status, "unit": self.unit, "linked_label": goal.category,
                "days": None, "best_days": None}


class NumericGoalType(GoalType):
    kind = "numeric"
    unit = ""

    def progress(self, goal, ctx):
        current = _manual_current(goal, ctx)
        if goal.direction == "under":
            status = "over" if (goal.target and current > goal.target) else "under"
        else:
            status = "reached" if (goal.target and current >= goal.target) else "active"
        return {"current_value": round(current, 2), "pct": _pct(current, goal.target),
                "status": status, "unit": self.unit, "linked_label": None,
                "days": None, "best_days": None}


class StreakGoalType(GoalType):
    kind = "streak"
    unit = "days"

    def progress(self, goal, ctx):
        since = goal.since or ctx.today
        days = max((ctx.today - since).days, 0)
        best = max(goal.best_days or 0, days)
        status = "milestone" if (goal.target and days >= goal.target) else "active"
        return {"current_value": days, "pct": _pct(days, goal.target), "status": status,
                "unit": self.unit, "linked_label": None, "days": days, "best_days": best}


GOAL_TYPES: dict[str, GoalType] = {
    t.kind: t for t in (SaveGoalType(), SpendCapGoalType(), NumericGoalType(), StreakGoalType())
}


def goal_type(kind: str) -> GoalType:
    try:
        return GOAL_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown goal kind: {kind}")


def goal_progress(goal: Goal, ctx: GoalContext) -> dict:
    return goal_type(goal.kind).progress(goal, ctx)
