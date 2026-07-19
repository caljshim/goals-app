from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.goal_types import period_window
from app.budget.models import Account, PlaidItem, Transaction
from app.budget.services import goals as goals_svc


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _account(s, **kw):
    item = PlaidItem(plaid_item_id="i1", access_token="t"); s.add(item); s.commit(); s.refresh(item)
    d = dict(plaid_account_id="a1", item_id=item.id, name="Ally Savings",
             type="depository", current_balance=3412.0)
    d.update(kw)
    a = Account(**d); s.add(a); s.commit(); s.refresh(a)
    return a


def test_create_and_list_save_goal_with_live_balance():
    s = make_session()
    a = _account(s)
    goals_svc.create_goal(s, {"name": "Emergency", "kind": "save", "target": 5000.0, "account_id": a.id})
    out = goals_svc.list_with_progress(s)
    assert len(out) == 1
    g = out[0]
    assert g["name"] == "Emergency" and g["kind"] == "save"
    assert g["current_value"] == 3412.0 and g["pct"] == 68.2
    assert g["linked_label"] == "Ally Savings"


def test_spend_cap_reads_this_months_category_spend():
    s = make_session()
    s.add(Transaction(account_id=1, date=date.today(), name="Chipotle", amount=310.0,
                      category="FOOD_AND_DRINK", user_category="EATING_OUT"))
    s.commit()
    goals_svc.create_goal(s, {"name": "Eating out", "kind": "spend_cap", "target": 400.0, "category": "EATING_OUT"})
    g = goals_svc.list_with_progress(s)[0]
    assert g["current_value"] == 310.0 and g["status"] == "under"


def test_create_validates_required_fields():
    s = make_session()
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "x", "kind": "save"})               # missing target
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "x", "kind": "spend_cap", "target": 100.0})  # missing category
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "x", "kind": "mystery", "target": 1})  # bad kind
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "", "kind": "numeric", "target": 1})   # missing name


def test_streak_defaults_since_to_today():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Sober", "kind": "streak", "target": 30.0})
    assert g.since == date.today()


def test_set_progress_add_then_set():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Trip", "kind": "save", "target": 2000.0, "current": 900.0})
    goals_svc.set_progress(s, g.id, add=200.0)
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 1100.0
    goals_svc.set_progress(s, g.id, current=1500.0)
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 1500.0


def test_reset_streak_records_best_and_restarts():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Sober", "kind": "streak", "since": date(2026, 6, 1), "target": 30.0})
    expected_best = max((date.today() - date(2026, 6, 1)).days, 0)
    goals_svc.reset_streak(s, g.id)
    s.refresh(g)
    assert g.since == date.today()
    assert g.best_days == expected_best


def test_spend_cap_weekly_uses_this_weeks_spend():
    s = make_session()
    today = date.today()
    wk_start, _ = period_window("weekly", today)
    s.add(Transaction(account_id=1, date=today, name="Chipotle", amount=30.0,
                      category="FOOD_AND_DRINK", user_category="EATING_OUT"))                 # this week
    s.add(Transaction(account_id=1, date=wk_start - timedelta(days=1), name="Old", amount=99.0,
                      category="FOOD_AND_DRINK", user_category="EATING_OUT"))                  # last week
    s.commit()
    goals_svc.create_goal(s, {"name": "Eat wk", "kind": "spend_cap", "target": 100.0,
                              "category": "EATING_OUT", "period": "weekly"})
    g = goals_svc.list_with_progress(s)[0]
    assert g["current_value"] == 30.0 and g["period"] == "weekly"


def test_spend_cap_defaults_to_monthly_period():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Eat", "kind": "spend_cap", "target": 400.0, "category": "EATING_OUT"})
    assert g.period == "monthly"


def test_recurring_manual_resets_when_period_rolls_over():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Save wk", "kind": "numeric", "target": 100.0,
                                  "current": 40.0, "period": "weekly"})
    # simulate the period having rolled over: push the anchor back a week
    g.period_anchor = g.period_anchor - timedelta(days=7)
    s.add(g); s.commit()
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 0.0   # stale period reads 0
    goals_svc.set_progress(s, g.id, add=25.0)                            # fresh contribution resets
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 25.0


def test_history_records_initial_value_and_each_manual_change():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Bench", "kind": "numeric", "target": 225.0, "current": 185.0})
    goals_svc.set_progress(s, g.id, current=195.0)
    goals_svc.set_progress(s, g.id, add=5.0)
    out = goals_svc.list_with_progress(s)[0]
    assert [h["value"] for h in out["history"]] == [185.0, 195.0, 200.0]


def test_history_not_recorded_for_linked_or_derived_goals():
    s = make_session()
    a = _account(s)
    goals_svc.create_goal(s, {"name": "Emergency", "kind": "save", "target": 5000.0, "account_id": a.id})
    assert goals_svc.list_with_progress(s)[0]["history"] == []


def test_group_round_trips_in_read():
    s = make_session()
    goals_svc.create_goal(s, {"name": "Bench", "kind": "numeric", "target": 225.0,
                              "current": 185.0, "group": "1000 CLUB"})
    assert goals_svc.list_with_progress(s)[0]["group"] == "1000 CLUB"


def test_update_changing_period_to_weekly_reanchors_current():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Church", "kind": "numeric", "target": 1.0, "current": 0.0, "period": "once"})
    goals_svc.update_goal(s, g.id, {"period": "weekly"})
    s.refresh(g)
    assert g.period == "weekly"
    assert g.period_anchor == period_window("weekly", date.today())[0]
    goals_svc.set_progress(s, g.id, current=1.0)
    assert goals_svc.list_with_progress(s)[0]["current_value"] == 1.0  # counts this week, not stale


def test_raise_goal_logs_milestone_and_sets_new_target():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Bench", "kind": "numeric", "target": 315.0, "current": 315.0})
    goals_svc.raise_goal(s, g.id, 335.0)
    out = goals_svc.list_with_progress(s)[0]
    assert out["target"] == 335.0
    assert [m["value"] for m in out["milestones"]] == [315.0]


def test_update_goal_can_edit_name_target_and_group():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Bench", "kind": "numeric", "target": 315.0, "current": 275.0})
    goals_svc.update_goal(s, g.id, {"name": "Bench press", "target": 320.0, "group": "1000 CLUB"})
    out = goals_svc.list_with_progress(s)[0]
    assert out["name"] == "Bench press" and out["target"] == 320.0 and out["group"] == "1000 CLUB"


def test_delete_goal():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "x", "kind": "numeric", "target": 10.0, "current": 1.0})
    assert goals_svc.delete_goal(s, g.id) is True
    assert goals_svc.list_with_progress(s) == []
    assert goals_svc.delete_goal(s, 999) is False
