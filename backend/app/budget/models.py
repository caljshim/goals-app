from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PlaidItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plaid_item_id: str = Field(index=True, unique=True)
    access_token: str
    institution_name: Optional[str] = None
    sync_cursor: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plaid_account_id: str = Field(index=True, unique=True)
    item_id: int = Field(foreign_key="plaiditem.id")
    name: str
    official_name: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    mask: Optional[str] = None
    current_balance: Optional[float] = None
    available_balance: Optional[float] = None
    currency: str = "USD"


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plaid_transaction_id: Optional[str] = Field(default=None, index=True, unique=True)
    account_id: int = Field(foreign_key="account.id")
    date: date
    name: str
    merchant_name: Optional[str] = None
    amount: float
    category: Optional[str] = None
    user_category: Optional[str] = None
    pending: bool = False
    # For an incoming P2P (Zelle/Venmo) reimbursement: the expense it pays back.
    # Nulling it out unlinks. Reductions net against the linked expense's month.
    reimburses_transaction_id: Optional[int] = Field(
        default=None, foreign_key="transaction.id", index=True
    )


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True, unique=True)
    monthly_limit: float


class MerchantRule(SQLModel, table=True):
    """Maps a normalized merchant (see categories.merchant_key) to a custom category,
    applied to all that merchant's transactions unless a per-transaction user_category
    override wins. Lets a one-time recategorization stick for future syncs."""
    id: Optional[int] = Field(default=None, primary_key=True)
    merchant: str = Field(index=True, unique=True)
    category: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)


class Goal(SQLModel, table=True):
    """A user-defined goal. `kind` selects the behavior (see budget.goal_types);
    the type-specific fields below are nullable and only some apply per kind:
      save      -> target + (account_id link | manual current) [+ deadline]
      spend_cap -> target + category (this month's spend)
      numeric   -> target + manual current [+ deadline]
      streak    -> since (reset date) + best_days [+ target milestone days]
    Progress is computed at read time so linked goals reflect live data."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str = Field(index=True)  # save | spend_cap | numeric | streak
    target: Optional[float] = None
    account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    category: Optional[str] = None
    current: Optional[float] = None
    since: Optional[date] = None
    best_days: int = 0
    deadline: Optional[date] = None
    # For numeric goals: "reach" (hit target, default) or "under" (stay at/below target).
    direction: str = Field(default="reach")
    step: float = 1.0  # increment for the −/+ tally buttons on manual goals
    group: Optional[str] = Field(default=None, index=True)  # user-named group, e.g. "1000 CLUB"
    # Cadence: once | daily | weekly | monthly. period_anchor is the period-start date
    # the manual `current` value belongs to, so it auto-resets when the period rolls over.
    period: str = Field(default="once")
    period_anchor: Optional[date] = None
    weekly_day: Optional[str] = None  # preferred day: monday | ... | sunday
    reset_time: str = Field(default="00:00")
    weekly_reset_day: str = Field(default="sunday")
    monthly_reset_day: int = Field(default=1)
    interval_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GoalHistory(SQLModel, table=True):
    """One recorded value of a manual goal at a point in time — the trajectory behind
    the sparkline and pace stats. Written on create and on each manual progress change."""
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    value: float
    at: datetime = Field(default_factory=datetime.utcnow)


class GoalCheckin(SQLModel, table=True):
    """Completion of one dated occurrence of a recurring goal."""
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    scheduled_for: date = Field(index=True)
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class GoalMilestone(SQLModel, table=True):
    """A target the user cleared and then raised past — the "levels beaten" history."""
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    value: float
    at: datetime = Field(default_factory=datetime.utcnow)
