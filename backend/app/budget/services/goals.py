"""Goals service: builds the live GoalContext, orchestrates per-type progress, and
owns goal CRUD + the manual-progress and streak-reset operations. Type-specific math
lives in budget.goal_types, not here."""
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from collections import defaultdict

from app.budget import goal_customization
from app.budget.goal_types import GOAL_TYPES, GoalContext, goal_period_start, goal_progress, period_window
from app.budget.models import Account, Goal, GoalAccountLink, GoalCheckin, GoalGroupSettings, GoalHistory, GoalMilestone
from app.budget.services.summary import cash_flow_in_range, spend_by_category_in_range

_VALID_KINDS = set(GOAL_TYPES)
_VALID_PERIODS = {"once", "daily", "weekly", "monthly", "interval"}
_VALID_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_WEEKDAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_INDEX = {day: index for index, day in enumerate(_WEEKDAY_ORDER)}
_FINANCIAL_METRICS = {"account_balance", "category_spend", "debt_balance", "net_worth", "income", "cash_flow"}
_FINANCIAL_RULES = {"reach", "stay_under", "reduce_to"}
_FINANCIAL_SOURCES = {"accounts", "manual"}
_MIN_NUDGE_MINUTES = 30
_MAX_NUDGE_MINUTES = 1440


def _normalize_weekly_days(value) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    days = {str(day).strip().lower() for day in values if str(day).strip()}
    unknown = days - _VALID_WEEKDAYS
    if unknown:
        raise ValueError(f"unknown weekday: {sorted(unknown)[0]}")
    return [day for day in _WEEKDAY_ORDER if day in days]


def _normalize_reminder_time(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
        _require(0 <= hour <= 23 and 0 <= minute <= 59, "reminder_time must be HH:MM")
    except (TypeError, ValueError):
        raise ValueError("reminder_time must be HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _persistent_routine_policy(
    data: dict,
    *,
    period: str,
    reminder_time: str | None,
    current: Goal | None = None,
) -> tuple[bool, int | None]:
    persistent = bool(data.get(
        "repeat_until_completed",
        current.repeat_until_completed if current is not None else False,
    ))
    if not persistent:
        return False, None
    _require(period in {"daily", "weekly", "monthly", "interval"},
             "persistent nudges require a recurring routine")
    _require(bool(reminder_time), "persistent routines require a reminder_time")
    raw_interval = data.get(
        "nudge_interval_minutes",
        current.nudge_interval_minutes if current is not None else None,
    )
    interval = int(raw_interval or 60)
    _require(
        _MIN_NUDGE_MINUTES <= interval <= _MAX_NUDGE_MINUTES,
        f"nudge_interval_minutes must be between {_MIN_NUDGE_MINUTES} and {_MAX_NUDGE_MINUTES}",
    )
    return True, interval


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
    return (
        goal.kind == "numeric"
        or (goal.kind == "save" and goal.account_id is None)
        or (goal.kind == "financial" and goal.financial_source == "manual")
    )


def _record_history(session: Session, goal: Goal) -> None:
    if _is_manual(goal):
        session.add(GoalHistory(goal_id=goal.id, value=goal.current or 0.0))
        session.commit()


def record_financial_goal_snapshots(session: Session) -> int:
    """Upsert today's computed value for each bank-derived financial goal.

    One point per calendar day keeps long-range charts compact while allowing a
    later sync on the same day to replace a stale morning balance or spend total.
    """
    goals = [
        goal for goal in session.exec(
            select(Goal).where(Goal.archived_at.is_(None))
        ).all()
        if (goal.kind == "save" and goal.account_id is not None)
        or goal.kind == "spend_cap"
        or (goal.kind == "financial" and goal.financial_source != "manual")
    ]
    ctx = build_context(session)
    day_start = datetime.combine(date.today(), time.min)
    changed = 0
    for goal in goals:
        value = goal_progress(goal, ctx)["current_value"]
        point = session.exec(
            select(GoalHistory)
            .where(GoalHistory.goal_id == goal.id, GoalHistory.at >= day_start)
            .order_by(GoalHistory.id.desc())
        ).first()
        if point:
            point.value = value
            point.at = datetime.utcnow()
        else:
            point = GoalHistory(goal_id=goal.id, value=value)
        session.add(point)
        changed += 1
    if changed:
        session.commit()
    return changed


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


def _goal_account_map(session: Session) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    for link in session.exec(select(GoalAccountLink)).all():
        out[link.goal_id].append(link.account_id)
    return {goal_id: sorted(ids) for goal_id, ids in out.items()}


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
    financial_values: dict[int, float] = {}
    financial_labels: dict[int, str] = {}
    account_links = _goal_account_map(session)
    all_accounts = {account.id: account for account in accounts}
    for goal in session.exec(select(Goal).where(Goal.kind == "financial")).all():
        if goal.financial_source == "manual":
            continue
        selected_ids = set(account_links.get(goal.id, []))
        selected = [a for aid, a in all_accounts.items() if not selected_ids or aid in selected_ids]
        metric = goal.financial_metric or "account_balance"
        if metric == "account_balance":
            value = sum(a.current_balance or 0.0 for a in selected)
        elif metric == "debt_balance":
            value = sum(a.current_balance or 0.0 for a in selected if a.type in {"credit", "loan"})
        elif metric == "net_worth":
            value = sum(
                -(a.current_balance or 0.0) if a.type in {"credit", "loan"}
                else (a.current_balance or 0.0)
                for a in selected
            )
        else:
            period = goal.period if goal.period in {"daily", "weekly", "monthly"} else "monthly"
            start, end = period_window(period, today)
            if metric == "category_spend":
                spend = spend_by_category_in_range(session, start, end, selected_ids or None)
                value = spend.get(goal.category or "", 0.0)
            else:
                income, expense = cash_flow_in_range(session, start, end, selected_ids or None)
                value = income if metric == "income" else income - expense
        financial_values[goal.id] = round(value, 2)
        financial_labels[goal.id] = (
            ", ".join(a.name for a in selected)
            if selected_ids else (goal.category or "All accounts")
        )
    from app.auto_integration.bindings import integration_goal_aggregates

    integration_values, integration_units, integration_labels = (
        integration_goal_aggregates(session)
    )
    return GoalContext(
        balances,
        names,
        by_period,
        today,
        financial_values,
        financial_labels,
        integration_values,
        integration_units,
        integration_labels,
    )


_KIND_ICON = {"save": "bank", "spend_cap": "card", "financial": "cashflow",
              "numeric": "chart", "streak": "flame"}


def _default_icon_token(g: Goal) -> str:
    return _KIND_ICON.get(g.kind, "target")


def _base_fields(g: Goal, account_links: dict[int, list[int]] | None = None,
                 group_settings: dict[str, "GoalGroupSettings"] | None = None) -> dict:
    gs = (group_settings or {}).get(g.group) if g.group else None
    default_color = "honey" if g.kind == "streak" else "pine"
    resolved_color = g.color or (gs.color if gs else None) or default_color
    return {
        "id": g.id, "name": g.name, "kind": g.kind, "target": g.target,
        "account_id": g.account_id, "category": g.category, "current": g.current,
        "anchor_value": g.anchor_value,
        "account_ids": (account_links or {}).get(g.id, []),
        "financial_metric": g.financial_metric, "financial_rule": g.financial_rule,
        "financial_source": ((g.financial_source or "accounts") if g.kind == "financial" else None),
        "since": g.since, "deadline": g.deadline, "period": g.period,
        "direction": g.direction, "step": g.step, "group": g.group,
        "weekly_day": (g.weekly_day.split(",")[0] if g.weekly_day else None),
        "weekly_days": _normalize_weekly_days(g.weekly_day),
        "reminder_time": g.reminder_time,
        "repeat_until_completed": g.repeat_until_completed,
        "nudge_interval_minutes": g.nudge_interval_minutes,
        "reset_time": g.reset_time, "weekly_reset_day": g.weekly_reset_day,
        "monthly_reset_day": g.monthly_reset_day, "interval_days": g.interval_days,
        "archived_at": g.archived_at,
        "icon": g.icon, "color": g.color,
        "resolved_icon": g.icon or _default_icon_token(g),
        "resolved_color": resolved_color,
        "group_icon": (gs.icon if gs else None),
        "group_color": (gs.color if gs else None),
    }


def _weekly_offset(day: str, week_starts_on: str) -> int:
    """Number of days from a configured week boundary to a weekday."""
    return (_WEEKDAY_INDEX[day] - _WEEKDAY_INDEX[week_starts_on]) % 7


def _checkin_map(session: Session) -> dict[int, set[date]]:
    completed: dict[int, set[date]] = defaultdict(set)
    for checkin in session.exec(select(GoalCheckin)).all():
        completed[checkin.goal_id].add(checkin.scheduled_for)
    return completed


def _weekly_streak(goal: Goal, completed: set[date], today: date) -> int:
    """Return consecutive fully-completed scheduled weeks.

    The active week is ignored until its final scheduled occurrence is due, so a
    Sunday routine does not lose last week's streak on Monday morning. Weeks
    before the routine was created are never considered.
    """
    if goal.period != "weekly":
        return 0

    selected = _normalize_weekly_days(goal.weekly_day) or ["saturday"]
    created = min(goal.created_at.date(), today)
    week_starts_on = goal.weekly_reset_day or "sunday"
    week_start = goal_period_start(goal, datetime.combine(today, time.max))

    def scheduled_dates(start: date) -> list[date]:
        return [
            start + timedelta(days=_weekly_offset(day, week_starts_on))
            for day in selected
            if start + timedelta(days=_weekly_offset(day, week_starts_on)) >= created
        ]

    if week_start is None:
        return 0
    current_dates = scheduled_dates(week_start)
    if current_dates and max(current_dates) > today:
        week_start -= timedelta(days=7)

    streak = 0
    while week_start + timedelta(days=6) >= created:
        due = scheduled_dates(week_start)
        if not due:
            week_start -= timedelta(days=7)
            continue
        if not all(item in completed for item in due):
            break
        streak += 1
        week_start -= timedelta(days=7)
    return streak


def goal_to_read(session: Session, goal: Goal) -> dict:
    account_links = _goal_account_map(session)
    completed = _checkin_map(session).get(goal.id, set())
    return {
        **_base_fields(goal, account_links, _group_settings_map(session)),
        **goal_progress(goal, build_context(session)),
        "history": _history_map(session).get(goal.id, []),
        "milestones": _milestone_map(session).get(goal.id, []),
        "weekly_streak": _weekly_streak(goal, completed, date.today()),
    }


def list_with_progress(session: Session, archived: bool = False) -> list[dict]:
    ctx = build_context(session)
    archived_filter = Goal.archived_at.is_not(None) if archived else Goal.archived_at.is_(None)
    goals = session.exec(select(Goal).where(archived_filter).order_by(Goal.id)).all()
    history = _history_map(session)
    milestones = _milestone_map(session)
    account_links = _goal_account_map(session)
    group_settings = _group_settings_map(session)
    checkins = _checkin_map(session)
    today = date.today()
    return [
        {**_base_fields(g, account_links, group_settings), **goal_progress(g, ctx),
         "history": history.get(g.id, []), "milestones": milestones.get(g.id, []),
         "weekly_streak": _weekly_streak(g, checkins.get(g.id, set()), today)}
        for g in goals
    ]


def _previous_month_start(today: date) -> date:
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def _task_dates(goal: Goal, scope: str, today: date) -> list[date]:
    if scope == "day" and goal.period == "daily":
        dates = [today - timedelta(days=1), today]
        upcoming: list[date] = []
        current_start = today
    elif scope == "day" and goal.period == "interval":
        interval = max(2, goal.interval_days or 2)
        anchor = goal.created_at.date()
        elapsed = (today - anchor).days
        current = anchor + timedelta(days=max(0, elapsed // interval) * interval)
        dates = [current - timedelta(days=interval), current]
        upcoming = [current + timedelta(days=interval)]
        current_start = current
    elif scope == "week":
        current_start = goal_period_start(goal, datetime.combine(today, datetime.max.time()))
        starts = [current_start - timedelta(days=7), current_start]
        next_starts = [current_start + timedelta(days=7)]
        selected = _normalize_weekly_days(goal.weekly_day)
        if selected:
            week_starts_on = goal.weekly_reset_day or "sunday"
            current_dates = [
                current_start + timedelta(days=_weekly_offset(day, week_starts_on))
                for day in selected
            ]
            dates = [
                start + timedelta(days=_weekly_offset(day, week_starts_on))
                for start in starts for day in selected
            ]
            upcoming = [
                start + timedelta(days=_weekly_offset(day, week_starts_on))
                for start in next_starts for day in selected
            ]
        else:
            current_dates = [current_start + timedelta(days=6)]
            dates = [start + timedelta(days=6) for start in starts]
            upcoming = [start + timedelta(days=6) for start in next_starts]
    else:
        current_start = goal_period_start(goal, datetime.combine(today, datetime.max.time()))
        previous_month = _previous_month_start(current_start)
        next_month = (current_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        day = max(1, min(goal.monthly_reset_day or 1, 28))
        dates = [previous_month.replace(day=day), current_start]
        upcoming = [next_month.replace(day=day)]
    # created_at is stored in UTC while scheduling uses the user's local calendar date.
    # Near midnight UTC that timestamp can be one day ahead locally, so clamp it to today.
    created = min(goal.created_at.date(), today)
    dates = [scheduled for scheduled in dates if scheduled >= created]
    if scope == "week":
        # Preserve every selected weekday on a newly-created routine's board. If
        # this cycle's occurrence predates the routine, surface that weekday's next
        # occurrence instead of silently dropping the checkbox.
        dates += [
            future for scheduled, future in zip(current_dates, upcoming)
            if scheduled < created and future >= created
        ]
    elif not any(scheduled >= current_start for scheduled in dates):
        dates += [scheduled for scheduled in upcoming if scheduled >= created]
    return sorted(set(dates))


def list_tasks(session: Session, scope: str) -> list[dict]:
    _require(scope in {"day", "week", "month"}, f"unknown task scope: {scope}")
    periods = {"day": {"daily", "interval"}, "week": {"weekly"}, "month": {"monthly"}}[scope]
    today = date.today()
    goals = session.exec(
        select(Goal).where(Goal.period.in_(periods), Goal.archived_at.is_(None)).order_by(Goal.name)
    ).all()
    checkins = session.exec(select(GoalCheckin)).all()
    completed = {(item.goal_id, item.scheduled_for) for item in checkins}
    return [
        {"goal_id": goal.id, "name": goal.name, "period": goal.period,
         "scheduled_for": scheduled, "completed": (goal.id, scheduled) in completed,
         "missed": scheduled < today and (goal.id, scheduled) not in completed,
         "reminder_time": goal.reminder_time}
        for goal in goals for scheduled in _task_dates(goal, scope, today)
    ]


def routine_occurs_on(
    goal: Goal,
    scheduled_for: date,
    today: date | None = None,
    include_archived_history: bool = False,
) -> bool:
    """Whether a recurring goal owns an occurrence on a calendar date.

    This is intentionally independent of the legacy current-period task windows so
    calendar clients can request arbitrary bounded ranges without manufacturing rows.
    """
    if goal.period not in {"daily", "weekly", "monthly", "interval"}:
        return False
    if goal.archived_at is not None and not include_archived_history:
        return False
    if (
        goal.archived_at is not None
        and scheduled_for > goal.archived_at.date()
    ):
        return False
    today = today or date.today()
    created = min(goal.created_at.date(), today)
    if scheduled_for < created:
        return False
    if goal.period == "daily":
        return True
    if goal.period == "interval":
        return (scheduled_for - created).days % max(1, goal.interval_days or 1) == 0
    if goal.period == "monthly":
        return scheduled_for.day == max(1, min(goal.monthly_reset_day or 1, 28))

    selected = _normalize_weekly_days(goal.weekly_day)
    if selected:
        return scheduled_for.strftime("%A").lower() in selected
    week_start = goal_period_start(goal, datetime.combine(scheduled_for, datetime.max.time()))
    return week_start is not None and scheduled_for == week_start + timedelta(days=6)


def set_checkin(session: Session, goal_id: int, scheduled_for: date, completed: bool,
                allow_overdue: bool = False) -> dict | None:
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None or goal.period not in {"daily", "weekly", "monthly", "interval"}:
        return None
    today = date.today()
    if scheduled_for > today or not routine_occurs_on(goal, scheduled_for, today=today):
        return None
    existing = session.exec(select(GoalCheckin).where(
        GoalCheckin.goal_id == goal_id, GoalCheckin.scheduled_for == scheduled_for
    )).first()
    # Creating a late completion requires an explicit override. Reversing an
    # existing check-in is always safe: otherwise its `missed` flag has already
    # disappeared and clients cannot undo an accidental check.
    if completed and not existing and scheduled_for < today and not allow_overdue:
        raise ValueError("Missed occurrences require an overdue correction")
    if completed and not existing:
        session.add(GoalCheckin(goal_id=goal_id, scheduled_for=scheduled_for))
    elif not completed and existing:
        session.delete(existing)
    session.commit()
    return {
        "goal_id": goal.id, "name": goal.name, "period": goal.period,
        "scheduled_for": scheduled_for, "completed": completed,
        "missed": scheduled_for < today and not completed,
        "reminder_time": goal.reminder_time,
    }


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def create_goal(session: Session, data: dict) -> Goal:
    kind = data.get("kind")
    _require(kind in _VALID_KINDS, f"unknown goal kind: {kind}")
    _require(kind != "spend_cap", "Spending limits belong in Budgets, not Goals")
    name = (data.get("name") or "").strip()
    _require(bool(name), "name is required")
    if kind in ("save", "spend_cap", "numeric", "financial"):
        _require(data.get("target") is not None, "target is required")
    if data.get("target") is not None:
        _require(float(data["target"]) > 0, "target must be positive")
    if kind == "spend_cap":
        _require(bool((data.get("category") or "").strip()), "category is required for a spending cap")

    direction = data.get("direction") or "reach"
    _require(direction in ("reach", "under"), f"unknown direction: {direction}")
    financial_metric = data.get("financial_metric")
    financial_rule = data.get("financial_rule")
    financial_source = data.get("financial_source")
    account_ids = sorted(set(data.get("account_ids") or []))
    if kind == "financial":
        financial_source = financial_source or "accounts"
        financial_metric = financial_metric or "account_balance"
        financial_rule = financial_rule or "reach"
        _require(financial_source in _FINANCIAL_SOURCES, f"unknown financial source: {financial_source}")
        _require(financial_metric in _FINANCIAL_METRICS, f"unknown financial metric: {financial_metric}")
        _require(financial_metric != "category_spend", "Category spending limits belong in Budgets")
        _require(financial_rule in _FINANCIAL_RULES, f"unknown financial rule: {financial_rule}")
        if financial_source == "manual":
            _require(financial_metric == "account_balance", "manual financial goals track an amount")
            _require(not account_ids, "manual financial goals do not use source accounts")
        elif financial_metric in {"account_balance", "debt_balance"}:
            _require(bool(account_ids), "choose at least one source account")
        if financial_source == "accounts" and financial_metric == "category_spend":
            _require(bool((data.get("category") or "").strip()), "category is required for spending")
        for account_id in account_ids:
            _require(session.get(Account, account_id) is not None, f"unknown account: {account_id}")
        direction = "under" if financial_rule in {"stay_under", "reduce_to"} else "reach"
    if kind == "numeric" and direction == "under":
        _require(data.get("current") is not None, "a starting value is required for an under goal")
        _require(float(data["current"]) > float(data["target"]),
                 "the starting value must be greater than the under target")
    default_financial_period = (
        "monthly" if kind == "financial" and financial_metric in {"category_spend", "income", "cash_flow"}
        else "once"
    )
    period = data.get("period") or ("monthly" if kind == "spend_cap" else default_financial_period)
    _require(period in _VALID_PERIODS, f"unknown period: {period}")
    if kind == "spend_cap":
        _require(period != "once", "a spending cap needs a daily, weekly, or monthly period")
    if kind == "financial" and financial_source == "accounts" and financial_metric in {"category_spend", "income", "cash_flow"}:
        _require(period in {"daily", "weekly", "monthly"}, "this financial metric needs a daily, weekly, or monthly period")
    if kind == "streak":
        period = "once"  # streaks are continuous, not periodic
    requested_days = data.get("weekly_days")
    if requested_days is None:
        requested_days = data.get("weekly_day")
    weekly_days = _normalize_weekly_days(requested_days) if period == "weekly" else []
    weekly_day = ",".join(weekly_days) or None
    reminder_time = _normalize_reminder_time(data.get("reminder_time"))
    repeat_until_completed, nudge_interval_minutes = _persistent_routine_policy(
        data, period=period, reminder_time=reminder_time
    )
    reset_time, weekly_reset_day, monthly_reset_day, interval_days = _validate_reset_settings(data, period)

    # Recurring manual goals anchor their `current` to the current period so it resets
    # automatically when the week/month rolls over.
    anchor = None

    goal = Goal(
        name=name, kind=kind, target=data.get("target"),
        account_id=data.get("account_id"),
        category=(data.get("category") or None),
        current=data.get("current"),
        anchor_value=(float(data["current"])
                      if kind == "numeric" and direction == "under" else None),
        financial_metric=financial_metric, financial_rule=financial_rule,
        financial_source=financial_source,
        since=data.get("since") or (date.today() if kind == "streak" else None),
        deadline=data.get("deadline"),
        period=period, period_anchor=anchor, direction=direction, weekly_day=weekly_day,
        reminder_time=reminder_time,
        repeat_until_completed=repeat_until_completed,
        nudge_interval_minutes=nudge_interval_minutes,
        reset_time=reset_time, weekly_reset_day=weekly_reset_day,
        monthly_reset_day=monthly_reset_day, interval_days=interval_days,
        step=(data.get("step") or 1.0), group=((data.get("group") or "").strip() or None),
    )
    session.add(goal); session.commit(); session.refresh(goal)
    for account_id in account_ids:
        session.add(GoalAccountLink(goal_id=goal.id, account_id=account_id))
    if account_ids:
        session.commit()
    if kind == "financial" and financial_rule == "reduce_to":
        starting_value = goal_progress(goal, build_context(session))["current_value"]
        if starting_value <= goal.target:
            for link in session.exec(select(GoalAccountLink).where(GoalAccountLink.goal_id == goal.id)).all():
                session.delete(link)
            session.delete(goal); session.commit()
            raise ValueError("the current financial value must be greater than a reduce-to target")
        goal.anchor_value = starting_value
        session.add(goal); session.commit(); session.refresh(goal)
    if (kind in ("save", "numeric") or (kind == "financial" and financial_source == "manual")) and period != "once":
        goal.period_anchor = goal_period_start(goal)
        session.add(goal); session.commit(); session.refresh(goal)
    _record_history(session, goal)
    if ((goal.kind == "save" and goal.account_id is not None)
            or goal.kind == "spend_cap"
            or (goal.kind == "financial" and goal.financial_source != "manual")):
        record_financial_goal_snapshots(session)
    return goal


_EDITABLE = ("name", "target", "account_id", "category", "deadline", "group", "period", "weekly_day", "reminder_time", "repeat_until_completed", "nudge_interval_minutes", "reset_time", "weekly_reset_day", "monthly_reset_day", "interval_days", "direction", "step", "financial_metric", "financial_rule", "financial_source", "icon", "color")


def update_goal(session: Session, goal_id: int, data: dict) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None:
        return None
    if data.get("step") is not None:
        _require(data["step"] > 0, "step must be positive")
    if data.get("target") is not None:
        _require(float(data["target"]) > 0, "target must be positive")
    if data.get("financial_metric") is not None:
        _require(data["financial_metric"] in _FINANCIAL_METRICS, "unknown financial metric")
    if data.get("financial_rule") is not None:
        _require(data["financial_rule"] in _FINANCIAL_RULES, "unknown financial rule")
    if data.get("financial_source") is not None:
        _require(data["financial_source"] in _FINANCIAL_SOURCES, "unknown financial source")
    if "icon" in data:
        goal_customization.validate_icon(data["icon"])
    if "color" in data:
        goal_customization.validate_color(data["color"])
    if "reminder_time" in data:
        data = {**data, "reminder_time": _normalize_reminder_time(data["reminder_time"])}
    if goal.kind == "financial":
        next_source = data.get("financial_source") or goal.financial_source or "accounts"
        next_metric = data.get("financial_metric") or goal.financial_metric or "account_balance"
        next_category = data.get("category", goal.category)
        next_account_ids = (sorted(set(data.get("account_ids") or []))
                            if "account_ids" in data else _goal_account_map(session).get(goal.id, []))
        if next_source == "manual":
            _require(next_metric == "account_balance", "manual financial goals track an amount")
            # Switching an existing linked goal to manual deliberately detaches it.
            if "financial_source" in data and "account_ids" not in data:
                data = {**data, "account_ids": []}
                next_account_ids = []
            _require(not next_account_ids, "manual financial goals do not use source accounts")
        elif next_metric in {"account_balance", "debt_balance"}:
            _require(bool(next_account_ids), "choose at least one source account")
        if next_source == "accounts" and next_metric == "category_spend":
            _require(bool((next_category or "").strip()), "category is required for spending")
    next_direction = data.get("direction", goal.direction)
    next_target = float(data.get("target", goal.target)) if data.get("target", goal.target) is not None else None
    if goal.kind == "numeric" and next_direction == "under":
        next_anchor = goal.anchor_value if goal.anchor_value is not None else goal.current
        _require(next_anchor is not None, "a starting value is required for an under goal")
        _require(next_target is not None and next_anchor > next_target,
                 "the starting value must be greater than the under target")
        if goal.anchor_value is None:
            goal.anchor_value = next_anchor
    next_period = data.get("period", goal.period)
    next_reminder_time = data.get("reminder_time", goal.reminder_time)
    repeat_until_completed, nudge_interval_minutes = _persistent_routine_policy(
        data,
        period=next_period,
        reminder_time=next_reminder_time,
        current=goal,
    )
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
            "interval_days": interval_days,
            "repeat_until_completed": repeat_until_completed,
            "nudge_interval_minutes": nudge_interval_minutes}
    for field in _EDITABLE:
        if field in data:
            setattr(goal, field, data[field])
    if "account_ids" in data:
        account_ids = sorted(set(data["account_ids"] or []))
        for account_id in account_ids:
            _require(session.get(Account, account_id) is not None, f"unknown account: {account_id}")
        for link in session.exec(select(GoalAccountLink).where(GoalAccountLink.goal_id == goal.id)).all():
            session.delete(link)
        for account_id in account_ids:
            session.add(GoalAccountLink(goal_id=goal.id, account_id=account_id))
    if "period" in data:
        # Re-anchor so the current value belongs to (and counts for) the new period.
        goal.period_anchor = goal_period_start(goal)
    session.add(goal); session.commit(); session.refresh(goal)
    if goal.kind == "financial":
        rule = goal.financial_rule or "reach"
        goal.direction = "under" if rule in {"stay_under", "reduce_to"} else "reach"
        links = _goal_account_map(session).get(goal.id, [])
        if goal.financial_source == "manual":
            _require(goal.financial_metric == "account_balance", "manual financial goals track an amount")
            _require(not links, "manual financial goals do not use source accounts")
        elif goal.financial_metric in {"account_balance", "debt_balance"}:
            _require(bool(links), "choose at least one source account")
        if goal.financial_source != "manual" and goal.financial_metric == "category_spend":
            _require(bool((goal.category or "").strip()), "category is required for spending")
        if rule == "reduce_to" and (goal.anchor_value is None or "financial_rule" in data):
            current_value = goal_progress(goal, build_context(session))["current_value"]
            _require(goal.target is not None and current_value > goal.target,
                     "the current financial value must be greater than a reduce-to target")
            goal.anchor_value = current_value
        session.add(goal); session.commit(); session.refresh(goal)
    return goal


def raise_goal(session: Session, goal_id: int, new_target: float) -> Goal | None:
    """Record the cleared target, then advance to a harder target in its direction."""
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None:
        return None
    _require(new_target > 0, "target must be positive")
    if goal.target is not None:
        if goal.direction == "under":
            _require(new_target < goal.target, "the next target must be lower")
        else:
            _require(new_target > goal.target, "the next target must be higher")
    if goal.target is not None:
        session.add(GoalMilestone(goal_id=goal.id, value=goal.target))
    goal.target = new_target
    session.add(goal); session.commit(); session.refresh(goal)
    return goal


def set_progress(session: Session, goal_id: int, current=None, add=None) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None:
        return None
    # If the goal is recurring and its period has rolled over, start the new period fresh.
    if goal.period not in (None, "once"):
        start = goal_period_start(goal)
        if goal.period_anchor != start:
            goal.current = 0.0
            goal.period_anchor = start
    if add is not None:
        # Relative adjustments floor at zero (tally semantics); explicit `current`
        # sets stay unclamped so a genuinely negative value can still be entered.
        goal.current = max(0.0, (goal.current or 0.0) + add)
    elif current is not None:
        goal.current = current
    session.add(goal); session.commit(); session.refresh(goal)
    _record_history(session, goal)
    return goal


def reset_streak(session: Session, goal_id: int) -> Goal | None:
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None:
        return None
    since = goal.since or date.today()
    days = max((date.today() - since).days, 0)
    goal.best_days = max(goal.best_days or 0, days)
    goal.since = date.today()
    session.add(goal); session.commit(); session.refresh(goal)
    return goal


def archive_goal(session: Session, goal_id: int) -> bool:
    goal = session.get(Goal, goal_id)
    if not goal or goal.archived_at is not None:
        return False
    goal.archived_at = datetime.utcnow()
    session.add(goal); session.commit()
    return True


def _active_goals_for_group_action(session: Session, goal_ids: list[int]) -> list[Goal]:
    ids = list(dict.fromkeys(goal_ids))
    _require(bool(ids), "choose at least one goal")
    goals = session.exec(
        select(Goal).where(Goal.id.in_(ids), Goal.archived_at.is_(None)).order_by(Goal.id)
    ).all()
    _require(len(goals) == len(ids), "one or more goals are no longer active")
    return goals


def _active_group_count(session: Session, name: str) -> int:
    return len(session.exec(
        select(Goal).where(Goal.group == name, Goal.archived_at.is_(None))
    ).all())


def set_goal_group(session: Session, goal_ids: list[int], name: str) -> list[Goal]:
    clean_name = name.strip()
    _require(bool(clean_name), "group name is required")
    _require(len(clean_name) <= 80, "group name is too long")
    goals = _active_goals_for_group_action(session, goal_ids)
    old_names = {g.group for g in goals if g.group and g.group != clean_name}
    for goal in goals:
        goal.group = clean_name
        session.add(goal)
    session.commit()
    for goal in goals:
        session.refresh(goal)
    for old in old_names:
        if _active_group_count(session, old) > 0:
            continue
        old_settings = session.get(GoalGroupSettings, old)
        if old_settings is None:
            continue
        if session.get(GoalGroupSettings, clean_name) is None:
            session.add(GoalGroupSettings(name=clean_name, icon=old_settings.icon, color=old_settings.color))
        session.delete(old_settings)
    session.commit()
    return goals


def _group_settings_map(session: Session) -> dict[str, "GoalGroupSettings"]:
    return {s.name: s for s in session.exec(select(GoalGroupSettings)).all()}


def get_group_settings(session: Session, name: str) -> GoalGroupSettings | None:
    return session.get(GoalGroupSettings, name.strip())


def set_group_settings(session: Session, name: str, icon: str | None, color: str | None) -> GoalGroupSettings | None:
    # Key settings by the same normalized name that set_goal_group stores on
    # Goal.group, so the read-model cascade (keyed by g.group) always matches.
    name = name.strip()
    goal_customization.validate_icon(icon)
    goal_customization.validate_color(color)
    settings = session.get(GoalGroupSettings, name)
    if icon is None and color is None:
        if settings is not None:
            session.delete(settings); session.commit()
        return None
    if settings is None:
        settings = GoalGroupSettings(name=name)
    settings.icon = icon
    settings.color = color
    session.add(settings); session.commit(); session.refresh(settings)
    return settings


def archive_goal_group(session: Session, goal_ids: list[int]) -> list[int]:
    goals = _active_goals_for_group_action(session, goal_ids)
    affected = {g.group for g in goals if g.group}
    ended_at = datetime.utcnow()
    for goal in goals:
        goal.archived_at = ended_at
        session.add(goal)
    session.commit()
    for name in affected:
        if _active_group_count(session, name) == 0:
            settings = session.get(GoalGroupSettings, name)
            if settings is not None:
                session.delete(settings)
    session.commit()
    return [goal.id for goal in goals]


# Compatibility for existing API and agent callers. "Delete" is intentionally a
# soft archive so no goal history can be lost.
delete_goal = archive_goal
