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


def test_spending_limits_are_rejected_as_goals():
    s = make_session()
    with pytest.raises(ValueError, match="Budgets"):
        goals_svc.create_goal(s, {"name": "Eating out", "kind": "spend_cap",
                                  "target": 400.0, "category": "EATING_OUT"})
    with pytest.raises(ValueError, match="Budgets"):
        goals_svc.create_goal(s, {"name": "Eating out", "kind": "financial",
                                  "financial_metric": "category_spend", "target": 400.0,
                                  "category": "EATING_OUT", "period": "monthly"})


def test_create_validates_required_fields():
    s = make_session()
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "x", "kind": "save"})               # missing target
    with pytest.raises(ValueError, match="Budgets"):
        goals_svc.create_goal(s, {"name": "x", "kind": "spend_cap", "target": 100.0})  # missing category
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "x", "kind": "mystery", "target": 1})  # bad kind
    with pytest.raises(ValueError):
        goals_svc.create_goal(s, {"name": "", "kind": "numeric", "target": 1})   # missing name
    with pytest.raises(ValueError, match="starting value"):
        goals_svc.create_goal(s, {"name": "Weight", "kind": "numeric",
                                  "direction": "under", "target": 180})
    with pytest.raises(ValueError, match="greater"):
        goals_svc.create_goal(s, {"name": "Weight", "kind": "numeric",
                                  "direction": "under", "target": 180, "current": 175})


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


def test_linked_financial_goal_records_daily_balance_snapshot():
    s = make_session()
    a = _account(s)
    goals_svc.create_goal(s, {"name": "Emergency", "kind": "save", "target": 5000.0, "account_id": a.id})
    assert [point["value"] for point in goals_svc.list_with_progress(s)[0]["history"]] == [3412.0]

    a.current_balance = 3500.0
    s.add(a); s.commit()
    goals_svc.record_financial_goal_snapshots(s)
    # A later sync on the same day replaces the point rather than adding noise.
    history = goals_svc.list_with_progress(s)[0]["history"]
    assert len(history) == 1 and history[0]["value"] == 3500.0


def test_flexible_financial_balance_goal_uses_selected_accounts():
    s = make_session()
    account = _account(s)
    goals_svc.create_goal(s, {
        "name": "Cash reserve", "kind": "financial", "financial_metric": "account_balance",
        "financial_rule": "reach", "target": 5000.0, "account_ids": [account.id],
    })
    goal = goals_svc.list_with_progress(s)[0]
    assert goal["account_ids"] == [account.id]
    assert goal["current_value"] == 3412.0 and goal["pct"] == 68.2
    assert goal["history"][0]["value"] == 3412.0


def test_flexible_financial_reduce_to_anchors_live_debt_value():
    s = make_session()
    card = _account(s, plaid_account_id="card-1", name="Card", type="credit", current_balance=1200.0)
    created = goals_svc.create_goal(s, {
        "name": "Pay down card", "kind": "financial", "financial_metric": "debt_balance",
        "financial_rule": "reduce_to", "target": 1000.0, "account_ids": [card.id],
    })
    assert created.anchor_value == 1200.0
    first = goals_svc.list_with_progress(s)[0]
    assert first["pct"] == 0.0 and first["status"] == "active"
    card.current_balance = 1100.0
    s.add(card); s.commit()
    updated = goals_svc.list_with_progress(s)[0]
    assert updated["pct"] == 50.0


def test_flexible_financial_goal_validates_sources():
    s = make_session()
    with pytest.raises(ValueError, match="source account"):
        goals_svc.create_goal(s, {"name": "Cash", "kind": "financial",
                                  "financial_metric": "account_balance", "target": 1000})


def test_manual_financial_goal_replaces_manual_savings_workflow():
    s = make_session()
    created = goals_svc.create_goal(s, {
        "name": "Vacation fund", "kind": "financial", "financial_source": "manual",
        "financial_metric": "account_balance", "financial_rule": "reach",
        "target": 2000.0, "current": 350.0, "step": 50.0,
    })

    goal = goals_svc.list_with_progress(s)[0]
    assert goal["id"] == created.id
    assert goal["financial_source"] == "manual" and goal["account_ids"] == []
    assert goal["current_value"] == 350.0 and goal["linked_label"] == "Manual"
    assert [point["value"] for point in goal["history"]] == [350.0]

    goals_svc.set_progress(s, created.id, add=50.0)
    updated = goals_svc.list_with_progress(s)[0]
    assert updated["current_value"] == 400.0
    assert [point["value"] for point in updated["history"]] == [350.0, 400.0]


def test_manual_financial_reduce_to_uses_entered_start_as_anchor():
    s = make_session()
    created = goals_svc.create_goal(s, {
        "name": "Cash spending", "kind": "financial", "financial_source": "manual",
        "financial_metric": "account_balance", "financial_rule": "reduce_to",
        "target": 500.0, "current": 800.0,
    })
    assert created.anchor_value == 800.0
    goals_svc.set_progress(s, created.id, current=650.0)
    assert goals_svc.list_with_progress(s)[0]["pct"] == 50.0


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


def test_delete_goal_archives_without_erasing_history():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "x", "kind": "numeric", "target": 10.0, "current": 1.0})
    goals_svc.set_progress(s, g.id, current=4.0)
    assert goals_svc.delete_goal(s, g.id) is True
    assert goals_svc.list_with_progress(s) == []
    archived = goals_svc.list_with_progress(s, archived=True)
    assert len(archived) == 1 and archived[0]["name"] == "x"
    assert [point["value"] for point in archived[0]["history"]] == [1.0, 4.0]
    assert archived[0]["archived_at"] is not None
    assert goals_svc.delete_goal(s, 999) is False


def test_under_goal_advances_to_a_lower_target():
    s = make_session()
    g = goals_svc.create_goal(s, {"name": "Weight", "kind": "numeric", "direction": "under",
                                  "target": 200.0, "current": 225.0})
    assert g.anchor_value == 225.0
    goals_svc.set_progress(s, g.id, current=195.0)
    goals_svc.raise_goal(s, g.id, 190.0)
    active = goals_svc.list_with_progress(s)[0]
    assert active["target"] == 190.0
    assert active["anchor_value"] == 225.0
    assert [m["value"] for m in active["milestones"]] == [200.0]
    with pytest.raises(ValueError, match="lower"):
        goals_svc.raise_goal(s, g.id, 205.0)
