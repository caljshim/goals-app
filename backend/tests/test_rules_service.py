from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.models import Transaction
from app.budget.services import rules as rules_svc


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _add(s, **kw):
    d = dict(account_id=1, date=date(2026, 7, 1), name="x", amount=1.0)
    d.update(kw)
    t = Transaction(**d)
    s.add(t); s.commit(); s.refresh(t)
    return t


def test_set_merchant_rule_upserts_and_clears_stale_overrides():
    s = make_session()
    t1 = _add(s, merchant_name="Safeway", name="SAFEWAY #1", category="FOOD_AND_DRINK", user_category="EATING_OUT")
    _add(s, merchant_name="Safeway", name="SAFEWAY #2", category="FOOD_AND_DRINK")

    rules_svc.set_merchant_rule(s, "Safeway", "groceries")  # note: un-normalized inputs
    assert rules_svc.load_rules(s) == {"safeway": "GROCERIES"}
    s.refresh(t1)
    assert t1.user_category is None  # stale one-off cleared so the rule governs uniformly

    rules_svc.set_merchant_rule(s, "safeway", "GENERAL_MERCHANDISE")  # upsert
    assert rules_svc.load_rules(s)["safeway"] == "GENERAL_MERCHANDISE"


def test_set_merchant_rule_rejects_bad_input():
    s = make_session()
    with pytest.raises(ValueError):
        rules_svc.set_merchant_rule(s, "Safeway", "TRANSFER_OUT")  # transfer category
    with pytest.raises(ValueError):
        rules_svc.set_merchant_rule(s, "", "GROCERIES")            # empty merchant


def test_bootstrap_creates_majority_rules_and_skips_transfers():
    s = make_session()
    _add(s, merchant_name="Chipotle", category="FOOD_AND_DRINK", user_category="EATING_OUT")
    _add(s, merchant_name="Chipotle", category="FOOD_AND_DRINK", user_category="EATING_OUT")
    _add(s, merchant_name="Chipotle", category="FOOD_AND_DRINK", user_category="GROCERIES")  # minority
    _add(s, merchant_name="Safeway", category="FOOD_AND_DRINK", user_category="GROCERIES")
    _add(s, merchant_name="Costco", category="GENERAL_MERCHANDISE")  # no user signal → no rule
    _add(s, merchant_name=None, name="Zelle payment to Ryan", category="TRANSFER_OUT", user_category="ENTERTAINMENT")

    out = rules_svc.bootstrap_rules(s)
    r = rules_svc.load_rules(s)
    assert r["chipotle"] == "EATING_OUT"          # majority wins
    assert r["safeway"] == "GROCERIES"
    assert "costco" not in r                       # no user categorization → skipped
    assert "zelle payment to ryan" not in r        # transfers never become rules
    assert out["count"] == 2


def test_build_summary_attributes_spend_to_the_ruled_category():
    from app.budget.models import Budget
    from app.budget.services.summary import build_summary
    s = make_session()
    _add(s, merchant_name="Chipotle", date=date(2026, 7, 2), amount=20.0, category="FOOD_AND_DRINK")
    s.add(Budget(category="EATING_OUT", monthly_limit=200.0)); s.commit()
    rules_svc.set_merchant_rule(s, "Chipotle", "EATING_OUT")

    out = build_summary(s, "2026-07")
    cats = {c["category"]: c["total"] for c in out["spending_by_category"]}
    assert cats.get("EATING_OUT") == 20.0
    assert "FOOD_AND_DRINK" not in cats
    bp = next(b for b in out["budget_progress"] if b["category"] == "EATING_OUT")
    assert bp["spent"] == 20.0


def test_overview_applies_merchant_rules():
    from app.budget.services import assistant
    s = make_session()
    months = assistant._prev_complete_months(1)
    y, m = int(months[0][:4]), int(months[0][5:7])
    _add(s, merchant_name="Chipotle", date=date(y, m, 10), amount=20.0, category="FOOD_AND_DRINK")
    rules_svc.set_merchant_rule(s, "Chipotle", "EATING_OUT")

    data, _ = assistant._overview(s)
    cats = {c["category"] for c in data["avg_monthly_by_category"]}
    assert "EATING_OUT" in cats
    assert "FOOD_AND_DRINK" not in cats


def test_list_and_delete_rule():
    s = make_session()
    rules_svc.set_merchant_rule(s, "Safeway", "GROCERIES")
    listed = rules_svc.list_rules(s)
    assert listed[0]["merchant"] == "safeway" and listed[0]["category"] == "GROCERIES"
    assert rules_svc.delete_rule(s, listed[0]["id"]) is True
    assert rules_svc.load_rules(s) == {}
    assert rules_svc.delete_rule(s, 9999) is False
