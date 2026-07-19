"""Goals service: builds the live GoalContext, orchestrates per-type progress, and
owns goal CRUD + the manual-progress and streak-reset operations. Type-specific math
lives in budget.goal_types, not here."""
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from collections import defaultdict

from app.budget.goal_types import GOAL_TYPES, GoalContext, goal_period_start, goal_progress, period_window
from app.budget.models import Account, Goal, GoalCheckin, GoalHistory, GoalMilestone
from app.budget.services.summary import spend_by_category_in_range

_VALID_KINDS = set(GOAL_TYPES)
_VALID_PERIODS = {"once", "daily", "weekly", "monthly", "interval"}
_VALID_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_WEEKDAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _normalize_weekly_days(value) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    days = {str(day).strip().lower() for day in values if str(day).strip()}
    unknown = days - _VALID_WEEKDAYS
    if unknown:
        raise ValueError(f"unknown weekday: {sorted(unknown)[0]}")
    return [day for day in _WEEKDAY_ORDER if day in days]


def _validate_reset_settings(data: dict, period: str) -> tuple[str, str, int, int | None]:
    reset_time = data.get("reset_time") or "00:00"
    try:
        hour, minute = (int(part) for part in reset_time.split(":"))
        _require(0 <= hour <= 23 and 0 <= minute <= 59, "reset_time must be HH:MM")
    except (AttributeError, TypeError, ValueError):
        raise ValueError("reset_time must be HH:MM")
    weekly_reset_day = str(data.get("weekly_reset_day") or "sunday").lower()
    _require(weekly_reset_day in _VALID_WEEKDAYS, f"unknown weekday: {weekly_reset_day}")
    monthly_reset_day = int(data.get("monthly_reset_day") or 1)
    _require(1 <= monthly_reset_day <= 28, "monthly_reset_day must be between 1 and 28")
    interval_days = data.get("interval_days")
    if period == "interval":
        _require(interval_days is not None and int(interval_days) >= 2, "interval_days must be at least 2")
        interval_days = int(interval_days)
    else:
        interval_days = None
    return reset_time, weekly_reset_day, monthly_reset_day, interval_days


def _is_manual(goal: Goal) -> bool:
    """A goal whose value is tallied by hand (so its trajectory is worth recording)."""
    return goal.kind == "numeric" or (goal.kind == "save" and goal.account_id is None)


def _record_history(session: Session, goal: Goal) -> None:
    if _is_manual(goal):
        session.add(GoalHistory(goal_id=goal.id, value=goal.current or 0.0))
        session.commit()


def _history_map(session: Session) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for h in session.exec(select(GoalHistory).order_by(GoalHistory.id)).all():
        out[h.goal_id].append({"value": h.value, "at": h.at})
    return out


def _milestone_map(session: Session) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for m in session.exec(select(GoalMilestone).order_by(GoalMilestone.id)).all():
        out[m.goal_id].append({"value": m.value, "at": m.at})
    return out


def build_context(session: Session) -> GoalContext:
    """Live data goal types resolve against: account balances + reimbursement-aware spend
    for each cadence window (daily/weekly/monthly)."""
    accounts = session.exec(select(Account)).all()
    balances = {a.id: (a.current_balance or 0.0) for a in accounts}
    names = {a.id: a.name for a in accounts}
    today = date.today()
    by_period = {}
    for period in ("daily", "weekly", "monthly"):
        start, end = period_window(period, today)
        by_period[period] = spend_by_category_in_range(session, start, end)
    return GoalContext(balances, names, by_period, today)


def _base_fields(g: Goal) -> dict:
    return {
        "id": g.id, "name": g.name, "kind": g.kind, "target": g.target,
        "account_id": g.account_id, "category": g.category, "current": g.current,
        "since": g.since, "deadline": g.deadline, "period": g.period,
        "direction": g.direction, "step": g.step, "group": g.group,
        "weekly_day": (g.weekly_day.split(",")[0] if g.weekly_day else None),
        "weekly_days": _normalize_weekly_days(g.weekly_day),
        "reset_time": g.reset_time, "weekly_reset_day": g.weekly_reset_day,
        "monthly_reset_day": g.monthly_reset_day, "interval_days": g.interval_days,
    }


def goal_to_read(session: Session, goal: Goal) -> dict:
    return {
        **_base_fields(goal), **goal_progress(goal, build_context(session)),
        "history": _history_map(session).get(goal.id, []),
        "milestones": _milestone_map(session).get(goal.id, []),
    }


def list_with_progress(session: Session) -> list[dict]:
    ctx = build_context(session)
    goals = session.exec(select(Goal).order_by(Goal.id)).all()
    history = _history_map(session)
    milestones = _milestone_map(session)
    return [
        {**_base_fields(g), **goal_progress(g, ctx),
         "history": history.get(g.id, []), "milestones": milestones.get(g.id, [])}
        for g in goals
    ]


def _previous_month_start(today: date) -> date:
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def _task_dates(goal: Goal, scope: str, today: date) -> list[date]:
    if scope == "day" and goal.period == "daily":
        dates = [today - timedelta(days=1), today]
    elif scope == "day" and goal.period == "interval":
        interval = max(2, goal.interval_days or 2)
        anchor = goal.created_at.date()
        elapsed = (today - anchor).days
        current = anchor + timedelta(days=max(0, elapsed // interval) * interval)
        dates = [current - timedelta(days=interval), current, current + timedelta(days=interval)]
    elif scope == "week":
        current_start = goal_period_start(goal, datetime.combine(today, datetime.max.time()))
        # Include last, current, and next week so a goal created near the weekend still
        # shows its upcoming scheduled days instead of producing an empty checklist.
        starts = [current_start - timedelta(days=7), current_start, current_start + timedelta(days=7)]
        selected = _normalize_weekly_days(goal.weekly_day)
        if selected:
            offsets = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
                       "thursday": 4, "friday": 5, "saturday": 6}
            dates = [start + timedelta(days=offsets[day]) for start in starts for day in selected]
        else:
            dates = [start + timedelta(days=6) for start in starts]
    else:
        current_start = goal_period_start(goal, datetime.combine(today, datetime.max.time()))
        previous_month = _previous_month_start(current_start)
        next_month = (current_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        day = max(1, min(goal.monthly_reset_day or 1, 28))
        dates = [previous_month.replace(day=day), current_start, next_month.replace(day=day)]
    # created_at is stored in UTC while scheduling uses the user's local calendar date.
    # Near midnight UTC that timestamp can be one day ahead locally, so clamp it to today.
    created = min(goal.created_at.date(), today)
    return [scheduled for scheduled in dates if scheduled >= created]


def list_tasks(session: Session, scope: str) -> list[dict]:
    _require(scope in {"day", "week", "month"}, f"unknown task scope: {scope}")
    periods = {"day": {"daily", "interval"}, "week": {"weekly"}, "month": {"monthly"}}[scope]
    today = date.today()
    goals = session.exec(select(Goal).where(Goal.period.in_(periods)).order_by(Goal.name)).all()
    checkins = session.exec(select(GoalCheckin)).all()
    completed = {(item.goal_id, item.scheduled_for) for item in checkins}
    return [
        {"goal_id": goal.id, "name": goal.name, "period": goal.period,
         "scheduled_for": scheduled, "completed": (goal.id, scheduled) in completed,
         "missed": scheduled < today and (goal.id, scheduled) not in completed}
        for goal in goals for scheduled in _task_dates(goal, scope, today)
    ]


def set_checkin(session: Session, goal_id: int, scheduled_for: date, completed: bool,
                allow_overdue: bool = False) -> dict | None:
    goal = session.get(Goal, goal_id)
    if not goal or goal.period not in {"daily", "weekly", "monthly", "interval"}:
        return None
    scope = {"daily": "day", "interval": "day", "weekly": "week", "monthly": "month"}[goal.period]
    valid = {(task["goal_id"], task["scheduled_for"]) for task in list_tasks(session, scope)}
    if (goal_id, scheduled_for) not in valid:
        return None
    if scheduled_for < date.today() and not allow_overdue:
        raise ValueError("Missed occurrences can only be corrected from the Goals tab")
    existing = session.exec(select(GoalCheckin).where(
        GoalCheckin.goal_id == goal_id, GoalCheckin.scheduled_for == scheduled_for
    )).first()
    if completed and not existing:
        session.add(GoalCheckin(goal_id=goal_id, scheduled_for=scheduled_for))
    elif not completed and existing:
        session.delete(existing)
    session.commit()
    return next((task for task in list_tasks(session, scope)
                 if task["goal_id"] == goal_id and task["scheduled_for"] == scheduled_for), None)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def create_goal(session: Session, data: dict) -> Goal:
    kind = data.get("kind")
    _require(kind in _VALID_KINDS, f"unknown goal kind: {kind}")
    name = (data.get("name") or "").strip()
    _require(bool(name), "name is required")
    if kind in ("save", "spend_cap", "numeric"):
        _require(data.get("target") is not None, "target is required")
    if kind == "spend_cap":
        _require(bool((data.get("category") or "").strip()), "category is required for a spending cap")

    direction = data.get("direction") or "reach"
    _require(direction in ("reach", "under"), f"unknown direction: {direction}")
    period = data.get("period") or ("monthly" if kind == "spend_cap" else "once")
    _require(period in _VALID_PERIODS, f"unknown period: {period}")
    if kind == "spend_cap":
        _require(period != "once", "a spending cap needs a daily, weekly, or monthly period")
    if kind == "streak":
        period = "once"  # streaks are continuous, not periodic
    requested_days = data.get("weekly_days")
    if requested_days is None:
        requested_days = data.get("weekly_day")
    weekly_days = _normalize_weekly_days(requested_days) if period == "weekly" else []
    weekly_day = ",".join(weekly_days) or None
    reset_time, weekly_reset_day, monthly_reset_day, interval_days = _validate_reset_settings(data, period)

    # Recurring manual goals anchor their `current` to the current period so it resets
    # automatically when the week/month rolls over.
    anchor = None

    goal = Goal(
        name=name, kind=kind, target=data.get("target"),
        account_id=data.get("account_id"),
        category=(data.get("category") or None),
        current=data.get("current"),
        since=data.get("since") or (date.today() if kind == "streak" else None),
        deadline=data.get("deadline"),
        period=period, period_anchor=anchor, direction=direction, weekly_day=weekly_day,
        reset_time=reset_time, weekly_reset_day=weekly_reset_day,
        monthly_reset_day=monthly_reset_day, interval_days=interval_days,
        step=(data.get("step") or 1.0), group=((data.get("group") or "").strip() or None),
    )
    session.add(goal); session.commit(); session.refresh(goal)
    if kind in ("save", "numeric") and period != "once":
        goal.period_anchor = goal_period_start(goal)
        session.add(goal); session.commit(); session.refresh(goal)
    _record_history(session, goal)
    return goal


_EDITABLE = ("name", "target", "account_id", "category", "deadline", "group", "period", "weekly_day", "reset_time", "weekly_reset_day", "monthly_reset_day", "interval_days", "direction", "step")


def update_goal(session: Session, goal_id: int, data: dict) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal:
        return None
    next_period = data.get("period", goal.period)
    requested_days = data.get("weekly_days")
    if requested_days is None:
        requested_days = data.get("weekly_day", goal.weekly_day)
    weekly_days = _normalize_weekly_days(requested_days) if next_period == "weekly" else []
    weekly_day = ",".join(weekly_days) or None
    reset_time, weekly_reset_day, monthly_reset_day, interval_days = _validate_reset_settings(
        {"reset_time": data.get("reset_time", goal.reset_time),
         "weekly_reset_day": data.get("weekly_reset_day", goal.weekly_reset_day),
         "monthly_reset_day": data.get("monthly_reset_day", goal.monthly_reset_day),
         "interval_days": data.get("interval_days", goal.interval_days)}, next_period)
    data = {**data, "weekly_day": weekly_day, "reset_time": reset_time,
            "weekly_reset_day": weekly_reset_day, "monthly_reset_day": monthly_reset_day,
            "interval_days": interval_days}
    for field in _EDITABLE:
        if field in data:
            setattr(goal, field, data[field])
    if "period" in data:
        # Re-anchor so the current value belongs to (and counts for) the new period.
        goal.period_anchor = goal_period_start(goal)
    session.add(goal); session.commit(); session.refresh(goal)
    return goal


def raise_goal(session: Session, goal_id: int, new_target: float) -> Goal | None:
    """Record the just-cleared target as a milestone, then raise the goal to new_target."""
    goal = session.get(Goal, goal_id)
    if not goal:
        return None
    if goal.target is not None:
        session.add(GoalMilestone(goal_id=goal.id, value=goal.target))
    goal.target = new_target
    session.add(goal); session.commit(); session.refresh(goal)
    return goal


def set_progress(session: Session, goal_id: int, current=None, add=None) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal:
        return None
    # If the goal is recurring and its period has rolled over, start the new period fresh.
    if goal.period not in (None, "once"):
        start = goal_period_start(goal)
        if goal.period_anchor != start:
            goal.current = 0.0
            goal.period_anchor = start
    if add is not None:
        goal.current = (goal.current or 0.0) + add
    elif current is not None:
        goal.current = current
    session.add(goal); session.commit(); session.refresh(goal)
    _record_history(session, goal)
    return goal


def reset_streak(session: Session, goal_id: int) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal:
        return None
    since = goal.since or date.today()
    days = max((date.today() - since).days, 0)
    goal.best_days = max(goal.best_days or 0, days)
    goal.since = date.today()
    session.add(goal); session.commit(); session.refresh(goal)
    return goal


def delete_goal(session: Session, goal_id: int) -> bool:
    goal = session.get(Goal, goal_id)
    if not goal:
        return False
    session.delete(goal); session.commit()
    return True
