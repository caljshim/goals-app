from datetime import date

from app.budget.goal_types import GoalContext, goal_progress
from app.budget.models import Goal


def ctx(**kw):
    base = dict(account_balances={}, account_names={}, category_spend_by_period={}, today=date(2026, 7, 15))
    base.update(kw)
    return GoalContext(**base)


def test_save_goal_linked_account_uses_live_balance():
    g = Goal(name="Emergency", kind="save", target=5000.0, account_id=1)
    p = goal_progress(g, ctx(account_balances={1: 3412.0}, account_names={1: "Ally Savings"}))
    assert p["current_value"] == 3412.0 and p["pct"] == 68.2 and p["status"] == "active"
    assert p["unit"] == "$" and p["linked_label"] == "Ally Savings"


def test_save_goal_manual_once():
    g = Goal(name="Trip", kind="save", target=2000.0, current=900.0)  # period defaults to once
    p = goal_progress(g, ctx())
    assert p["current_value"] == 900.0 and p["pct"] == 45.0 and p["linked_label"] is None


def test_save_goal_reached_status():
    assert goal_progress(Goal(name="Trip", kind="save", target=2000.0, current=2100.0), ctx())["status"] == "reached"


def test_spend_cap_monthly_by_default():
    g = Goal(name="Eat", kind="spend_cap", target=400.0, category="EATING_OUT", period="monthly")
    under = goal_progress(g, ctx(category_spend_by_period={"monthly": {"EATING_OUT": 310.0}}))
    assert under["current_value"] == 310.0 and under["status"] == "under"
    over = goal_progress(g, ctx(category_spend_by_period={"monthly": {"EATING_OUT": 450.0}}))
    assert over["status"] == "over" and over["linked_label"] == "EATING_OUT"


def test_spend_cap_weekly_reads_the_weekly_window():
    g = Goal(name="Eat", kind="spend_cap", target=100.0, category="EATING_OUT", period="weekly")
    p = goal_progress(g, ctx(category_spend_by_period={
        "weekly": {"EATING_OUT": 60.0}, "monthly": {"EATING_OUT": 999.0}}))
    assert p["current_value"] == 60.0  # weekly window, not monthly


def test_numeric_manual_once():
    p = goal_progress(Goal(name="Net worth", kind="numeric", target=50000.0, current=28000.0), ctx())
    assert p["current_value"] == 28000.0 and p["pct"] == 56.0 and p["unit"] == ""


def test_numeric_reach_is_the_default_direction():
    assert goal_progress(Goal(name="Net worth", kind="numeric", target=100.0, current=80.0), ctx())["status"] == "active"
    assert goal_progress(Goal(name="Net worth", kind="numeric", target=100.0, current=120.0), ctx())["status"] == "reached"


def test_numeric_under_direction_flips_status():
    under = Goal(name="Subs", kind="numeric", target=100.0, current=80.0, direction="under")
    p = goal_progress(under, ctx())
    assert p["status"] == "under" and p["pct"] == 80.0
    over = Goal(name="Subs", kind="numeric", target=100.0, current=120.0, direction="under")
    assert goal_progress(over, ctx())["status"] == "over"


def test_recurring_manual_resets_when_period_anchor_is_stale():
    stale = Goal(name="Weekly save", kind="numeric", target=100.0, current=50.0,
                 period="weekly", period_anchor=date(2026, 7, 5))    # a past week
    assert goal_progress(stale, ctx(today=date(2026, 7, 15)))["current_value"] == 0.0

    current = Goal(name="Weekly save", kind="numeric", target=100.0, current=50.0,
                   period="weekly", period_anchor=date(2026, 7, 12))  # this week's Sunday
    assert goal_progress(current, ctx(today=date(2026, 7, 15)))["current_value"] == 50.0


def test_streak_counts_days_since_and_tracks_best():
    g = Goal(name="Smoke-free", kind="streak", target=90.0, since=date(2026, 6, 6), best_days=20)
    p = goal_progress(g, ctx(today=date(2026, 7, 17)))
    assert p["days"] == 41 and p["current_value"] == 41 and p["best_days"] == 41
    assert p["unit"] == "days" and p["status"] == "active"


def test_streak_milestone_reached():
    g = Goal(name="Sober", kind="streak", target=30.0, since=date(2026, 6, 1), best_days=0)
    assert goal_progress(g, ctx(today=date(2026, 7, 17)))["status"] == "milestone"


def test_unknown_kind_raises():
    import pytest
    with pytest.raises(Exception):
        goal_progress(Goal(name="?", kind="mystery"), ctx())
