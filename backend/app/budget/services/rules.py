"""Merchant category rules: a one-time recategorization that sticks for future syncs.

A rule maps a normalized merchant (categories.merchant_key) to a custom category and is
applied at read time by categories.effective_category, below a per-transaction
user_category override. Transfers/P2P are never ruled (kept for the Zelle/card logic)."""
from collections import Counter, defaultdict

from sqlmodel import Session, select

from app.budget.categories import (
    TRANSFER_CATEGORIES,
    merchant_key,
    normalize_category,
)
from app.budget.models import Category, MerchantRule, Transaction


def load_rules(session: Session) -> dict[str, str]:
    """merchant_key -> category for every rule, ready to pass to effective_category."""
    return {r.merchant: r.category for r in session.exec(select(MerchantRule)).all()}


def list_rules(session: Session) -> list[dict]:
    rows = session.exec(select(MerchantRule).order_by(MerchantRule.merchant)).all()
    return [{"id": r.id, "merchant": r.merchant, "category": r.category} for r in rows]


def _ensure_category(session: Session, name: str) -> None:
    if name and not session.exec(select(Category).where(Category.name == name)).first():
        session.add(Category(name=name))


def set_merchant_rule(session: Session, merchant: str, category: str) -> MerchantRule:
    """Upsert a rule and clear any stale one-off overrides on that merchant's
    (non-transfer) transactions so the rule governs uniformly. Raises ValueError on
    an empty merchant or a transfer category (those aren't real spending buckets)."""
    m = (merchant or "").strip().lower()
    cat = normalize_category(category)
    if not m:
        raise ValueError("merchant is required")
    if not cat:
        raise ValueError("category is required")
    if cat in TRANSFER_CATEGORIES:
        raise ValueError("a rule category cannot be a transfer category")

    rule = session.exec(select(MerchantRule).where(MerchantRule.merchant == m)).first()
    if rule:
        rule.category = cat
    else:
        rule = MerchantRule(merchant=m, category=cat)
    session.add(rule)

    for t in session.exec(select(Transaction)).all():
        if t.category not in TRANSFER_CATEGORIES and t.user_category is not None and merchant_key(t) == m:
            t.user_category = None
            session.add(t)

    _ensure_category(session, cat)
    session.commit()
    session.refresh(rule)
    return rule


def delete_rule(session: Session, rule_id: int) -> bool:
    rule = session.get(MerchantRule, rule_id)
    if not rule:
        return False
    session.delete(rule)
    session.commit()
    return True


def bootstrap_rules(session: Session) -> dict:
    """Turn existing manual categorizations into rules: for each non-transfer merchant,
    the majority user_category among its transactions becomes a rule. Merchants the user
    never categorized are left alone (no signal)."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for t in session.exec(select(Transaction)).all():
        if t.category in TRANSFER_CATEGORIES or not t.user_category:
            continue
        key = merchant_key(t)
        if key:
            votes[key][t.user_category] += 1

    created = []
    for key, counter in votes.items():
        category = counter.most_common(1)[0][0]
        set_merchant_rule(session, key, category)
        created.append({"merchant": key, "category": category})
    return {"created": created, "count": len(created)}
