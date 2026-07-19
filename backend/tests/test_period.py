from datetime import date, datetime

from app.budget.goal_types import goal_period_start, period_window
from app.budget.models import Goal


def test_daily_is_just_today():
    assert period_window("daily", date(2026, 7, 15)) == (date(2026, 7, 15), date(2026, 7, 15))


def test_weekly_is_sunday_to_saturday():
    # 2026-07-15 is a Wednesday
    assert period_window("weekly", date(2026, 7, 15)) == (date(2026, 7, 12), date(2026, 7, 18))


def test_weekly_on_the_sunday_itself():
    assert period_window("weekly", date(2026, 7, 12)) == (date(2026, 7, 12), date(2026, 7, 18))


def test_monthly_is_first_to_last_of_month():
    assert period_window("monthly", date(2026, 7, 15)) == (date(2026, 7, 1), date(2026, 7, 31))


def test_monthly_handles_december():
    assert period_window("monthly", date(2026, 12, 10)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_once_has_no_window():
    assert period_window("once", date(2026, 7, 15)) == (None, None)


def test_daily_goal_resets_at_chosen_time():
    goal = Goal(name="Read", kind="numeric", period="daily", reset_time="04:00")
    assert goal_period_start(goal, datetime(2026, 7, 15, 3, 59)) == date(2026, 7, 14)
    assert goal_period_start(goal, datetime(2026, 7, 15, 4, 0)) == date(2026, 7, 15)


def test_weekly_goal_resets_on_chosen_day_and_time():
    goal = Goal(name="Train", kind="numeric", period="weekly",
                weekly_reset_day="monday", reset_time="06:00")
    assert goal_period_start(goal, datetime(2026, 7, 13, 5, 59)) == date(2026, 7, 6)
    assert goal_period_start(goal, datetime(2026, 7, 13, 6, 0)) == date(2026, 7, 13)


def test_monthly_goal_reset_day_is_configurable():
    goal = Goal(name="Review", kind="numeric", period="monthly", monthly_reset_day=15)
    assert goal_period_start(goal, datetime(2026, 7, 14, 23, 59)) == date(2026, 6, 15)
    assert goal_period_start(goal, datetime(2026, 7, 15, 0, 0)) == date(2026, 7, 15)


def test_interval_goal_uses_creation_date_as_anchor():
    goal = Goal(name="Mask", kind="numeric", period="interval", interval_days=3,
                created_at=datetime(2026, 7, 1, 12, 0), reset_time="12:00")
    assert goal_period_start(goal, datetime(2026, 7, 8, 11, 59)) == date(2026, 7, 7)
    assert goal_period_start(goal, datetime(2026, 7, 10, 12, 0)) == date(2026, 7, 10)
