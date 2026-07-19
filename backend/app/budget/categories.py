from app.budget.models import Transaction

UNCATEGORIZED = "UNCATEGORIZED"

# Plaid categories that represent money moving between the user's own accounts
# (or to other people) rather than real spending or income. Counting them would
# double-count: a credit-card payment already shows as purchases on the card, and
# each payment appears twice (LOAN_PAYMENTS out of checking, LOAN_DISBURSEMENTS as
# the card credit). Excluded from all spending/income totals.
# NOTE: keep in sync with frontend/src/categories.ts
TRANSFER_CATEGORIES = frozenset({
    "LOAN_PAYMENTS",
    "LOAN_DISBURSEMENTS",
    "TRANSFER_IN",
    "TRANSFER_OUT",
})


# Seed data for the `category` table (see db.seed_default_categories). The DB is
# the source of truth at runtime; this list only populates a fresh database with
# the Plaid spending primaries so the assistant starts with sensible buckets.
# (Income/transfer primaries excluded.)
SPENDING_CATEGORIES = frozenset({
    "BANK_FEES",
    "ENTERTAINMENT",
    "FOOD_AND_DRINK",
    "GENERAL_MERCHANDISE",
    "GENERAL_SERVICES",
    "GOVERNMENT_AND_NON_PROFIT",
    "HOME_IMPROVEMENT",
    "MEDICAL",
    "PERSONAL_CARE",
    "RENT_AND_UTILITIES",
    "TRANSPORTATION",
    "TRAVEL",
})


def normalize_category(name: str | None) -> str:
    """Canonical UPPER_SNAKE_CASE form of a category name."""
    return "_".join((name or "").strip().upper().split())


def merchant_key(txn: Transaction) -> str:
    """Normalized merchant identity a rule keys on: Plaid's cleaned merchant_name when
    present (so "SAFEWAY #1234" and "SAFEWAY #5678" collapse to one), else the raw name."""
    return (txn.merchant_name or txn.name or "").strip().lower()


def effective_category(txn: Transaction, rules: dict[str, str] | None = None) -> str:
    """Resolved category, in precedence order:
    user_category (one-off override) > merchant rule > raw Plaid category > UNCATEGORIZED.
    Rules never apply to transfers/P2P (raw category TRANSFER_*/LOAN_*), keeping the
    Zelle/card-payment handling untouched. `rules` maps merchant_key -> category."""
    if txn.user_category:
        return txn.user_category
    if rules and txn.category not in TRANSFER_CATEGORIES:
        rule = rules.get(merchant_key(txn))
        if rule:
            return rule
    return txn.category or UNCATEGORIZED


def is_transfer(txn: Transaction) -> bool:
    return effective_category(txn) in TRANSFER_CATEGORIES


# Peer-to-peer transfers (Zelle/Venmo with real people) are money that changes what
# the user truly spent: incoming = reimbursement (reduces spending), outgoing =
# paying their share of something (adds to spending). Own-account transfers and
# credit-card payments stay fully excluded.
_P2P_KEYWORDS = ("zelle", "venmo")


def is_p2p(txn: Transaction) -> bool:
    if effective_category(txn) not in {"TRANSFER_IN", "TRANSFER_OUT"}:
        return False
    name = (txn.name or "").lower()
    return any(k in name for k in _P2P_KEYWORDS)


def is_incoming_p2p(txn: Transaction) -> bool:
    """Money coming IN from a person via Zelle/Venmo — a candidate reimbursement.
    Uses the raw Plaid category (not effective) so it stays detectable after the
    user assigns it a spending category or keeps it as a transfer."""
    if txn.category != "TRANSFER_IN":
        return False
    name = (txn.name or "").lower()
    return any(k in name for k in _P2P_KEYWORDS)
