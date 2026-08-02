from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class PlaidItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plaid_item_id: str = Field(index=True, unique=True)
    access_token: str
    institution_name: Optional[str] = None
    sync_cursor: Optional[str] = None
    # Version of the one-time authoritative transaction reconciliation applied
    # to this Item. Existing databases start at 0 and repair on their next sync.
    reconciliation_version: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plaid_account_id: str = Field(index=True, unique=True)
    # Plaid's cross-Item account identity. Unlike account_id, this survives a
    # user accidentally creating a fresh Item for the same depository account.
    persistent_account_id: Optional[str] = Field(default=None, index=True, unique=True)
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
        default=None,
        foreign_key="transaction.id",
        ondelete="SET NULL",
        index=True,
    )


class Budget(SQLModel, table=True):
    """A category spending guardrail for one reset window.

    The Python field keeps its legacy name so existing callers remain compatible;
    `period` makes the amount daily, weekly, or monthly.
    """
    __tablename__ = "budgetrule"
    __table_args__ = (UniqueConstraint("category", "period", name="uq_budgetrule_category_period"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    monthly_limit: float
    period: str = Field(default="monthly", index=True)


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
      save      -> legacy target + (account_id link | manual current) [+ deadline]
      financial -> target + bank-derived value or manual current
      spend_cap -> legacy spending goal, migrated to Budget
      numeric   -> target + manual current [+ deadline]
      streak    -> since (reset date) + best_days [+ target milestone days]
    Progress is computed at read time so linked goals reflect live data."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str = Field(index=True)  # save (legacy) | spend_cap | financial | numeric | streak
    target: Optional[float] = None
    account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    category: Optional[str] = None
    current: Optional[float] = None
    # Immutable baseline for a numeric "under" goal. Progress runs from this
    # starting value toward the lower target instead of assuming zero.
    anchor_value: Optional[float] = None
    financial_metric: Optional[str] = None
    financial_rule: Optional[str] = None
    financial_source: Optional[str] = None  # accounts | manual
    since: Optional[date] = None
    best_days: int = 0
    deadline: Optional[date] = None
    # For numeric goals: "reach" (hit target, default) or "under" (stay at/below target).
    direction: str = Field(default="reach")
    step: float = 1.0  # increment for the −/+ tally buttons on manual goals
    group: Optional[str] = Field(default=None, index=True)  # user-named group, e.g. "1000 CLUB"
    icon: Optional[str] = None   # customization token; None -> derive from kind
    color: Optional[str] = None  # customization token; None -> group cascade / default
    # Cadence: once | daily | weekly | monthly. period_anchor is the period-start date
    # the manual `current` value belongs to, so it auto-resets when the period rolls over.
    period: str = Field(default="once")
    period_anchor: Optional[date] = None
    weekly_day: Optional[str] = None  # preferred day: monday | ... | sunday
    reminder_time: Optional[str] = None  # optional local due time, HH:MM
    repeat_until_completed: bool = Field(default=False)
    important: bool = Field(default=False)
    nudge_interval_minutes: Optional[int] = None
    reset_time: str = Field(default="00:00")
    weekly_reset_day: str = Field(default="sunday")
    monthly_reset_day: int = Field(default=1)
    interval_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Goals are never physically deleted. Archiving removes them from active views
    # while preserving their target, progress history, milestones, and check-ins.
    archived_at: Optional[datetime] = Field(default=None, index=True)


class GoalGroupSettings(SQLModel, table=True):
    """Per-group appearance (icon/color tokens), keyed by the group name shared
    across a set of goals. Created lazily only when a group is customized;
    absence means defaults."""
    name: str = Field(primary_key=True)
    icon: Optional[str] = None
    color: Optional[str] = None


class GoalHistory(SQLModel, table=True):
    """One recorded goal value at a point in time — manual progress entries plus
    daily snapshots for bank-derived financial goals."""
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    value: float
    at: datetime = Field(default_factory=datetime.utcnow)


class GoalAccountLink(SQLModel, table=True):
    """Many-to-many source accounts for a flexible financial goal."""
    goal_id: int = Field(foreign_key="goal.id", primary_key=True)
    account_id: int = Field(foreign_key="account.id", primary_key=True)


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


class Reminder(SQLModel, table=True):
    """A one-time scheduled task. Recurring work stays in Goal and goal deadlines
    stay attached to Goal; the schedule API also merges calendar events at read time."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    scheduled_for: date = Field(index=True)
    reminder_time: Optional[str] = None  # local wall-clock time, HH:MM
    notes: Optional[str] = None
    # Persistent reminders keep producing notification nudges until completed.
    repeat_until_completed: bool = False
    important: bool = Field(default=False)
    # none | daily | weekly — recurring reminders re-ring on that cadence.
    repeat_rule: str = Field(default="none")
    nudge_interval_minutes: Optional[int] = None
    completed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CalendarEvent(SQLModel, table=True):
    """A one-time calendar entry. Events describe where the user plans to be;
    reminders remain actionable tasks with completion and nudge semantics."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    scheduled_for: date = Field(index=True)
    start_time: Optional[str] = None  # local wall-clock time, HH:MM; None is all-day
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentJob(SQLModel, table=True):
    """Persisted status for a potentially slow Audel action.

    The HTTP request only creates the job. A background worker owns the model
    call and database mutation, while clients can leave/reopen the app and
    continue polling this row.
    """
    id: str = Field(primary_key=True)
    kind: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    stage: str = Field(default="Queued")
    total: int = 0
    completed: int = 0
    result_json: Optional[str] = None
    error: Optional[str] = None
    idempotency_key: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
