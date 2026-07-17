from datetime import date

from app.budget.categories import UNCATEGORIZED, effective_category
from app.budget.models import Transaction


def _txn(category=None, user_category=None):
    return Transaction(
        account_id=1, date=date(2026, 7, 1), name="x", amount=1.0,
        category=category, user_category=user_category,
    )


def test_user_category_wins():
    assert effective_category(_txn(category="FOOD_AND_DRINK", user_category="DINING")) == "DINING"


def test_falls_back_to_plaid_category():
    assert effective_category(_txn(category="FOOD_AND_DRINK")) == "FOOD_AND_DRINK"


def test_uncategorized_when_both_missing():
    assert effective_category(_txn()) == UNCATEGORIZED
