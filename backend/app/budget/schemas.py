from datetime import date as date_type, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccountRead(BaseModel):
    id: int
    item_id: int
    plaid_account_id: str
    persistent_account_id: Optional[str] = None
    name: str
    official_name: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    mask: Optional[str] = None
    current_balance: Optional[float] = None
    available_balance: Optional[float] = None
    currency: str


class TransactionRead(BaseModel):
    id: int
    account_id: int
    date: date_type
    name: str
    merchant_name: Optional[str] = None
    amount: float
    category: Optional[str] = None
    user_category: Optional[str] = None
    effective_category: str
    pending: bool
    is_manual: bool
    reimburses_transaction_id: Optional[int] = None
    # Spending category reduced by this incoming reimbursement, whether it was
    # linked to one exact expense or assigned directly to the category.
    reimbursement_category: Optional[str] = None
    # True/false for spending transactions; null for income and transfers where a
    # monthly spending budget does not apply.
    is_budgeted: Optional[bool] = None


class TransactionCreate(BaseModel):
    account_id: int
    date: date_type
    name: str
    amount: float
    merchant_name: Optional[str] = None
    user_category: Optional[str] = None


class TransactionUpdate(BaseModel):
    user_category: Optional[str] = None
    account_id: Optional[int] = None
    date: Optional[date_type] = None
    name: Optional[str] = None
    amount: Optional[float] = None


class BulkTransactionCategoryUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=500)
    user_category: str = Field(min_length=1, max_length=120)


class ReimburseUpdate(BaseModel):
    # The expense this incoming transaction reimburses; null unlinks it.
    target_id: Optional[int] = None


class BulkReimburseUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=500)
    target_id: int


class MerchantCategoryUpdate(BaseModel):
    # Category to apply to this transaction's whole merchant (creates/updates a rule).
    category: str


class MerchantRuleCreate(BaseModel):
    merchant: str
    category: str


class MerchantRuleRead(BaseModel):
    id: int
    merchant: str
    category: str


class BudgetRead(BaseModel):
    id: int
    category: str
    monthly_limit: float
    period: str = "monthly"


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float
    period: str = "monthly"


class BudgetUpdate(BaseModel):
    monthly_limit: float
    period: Optional[str] = None
    category: Optional[str] = None


class GoalCreate(BaseModel):
    name: str
    kind: str  # save | spend_cap | numeric | streak
    target: Optional[float] = None
    account_id: Optional[int] = None
    account_ids: list[int] = []
    category: Optional[str] = None
    financial_metric: Optional[str] = None
    financial_rule: Optional[str] = None
    financial_source: Optional[str] = None
    current: Optional[float] = None
    since: Optional[date_type] = None
    deadline: Optional[date_type] = None
    period: Optional[str] = None  # once | daily | weekly | monthly
    weekly_day: Optional[str] = None
    weekly_days: Optional[list[str]] = None
    reminder_time: Optional[str] = None
    repeat_until_completed: bool = False
    nudge_interval_minutes: Optional[int] = None
    reset_time: Optional[str] = None
    weekly_reset_day: Optional[str] = None
    monthly_reset_day: Optional[int] = None
    interval_days: Optional[int] = None
    direction: Optional[str] = None  # numeric goals: reach | under
    step: Optional[float] = None  # increment for the −/+ tally buttons
    group: Optional[str] = None  # user-named group, e.g. "1000 CLUB"


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    target: Optional[float] = None
    account_id: Optional[int] = None
    account_ids: Optional[list[int]] = None
    category: Optional[str] = None
    financial_metric: Optional[str] = None
    financial_rule: Optional[str] = None
    financial_source: Optional[str] = None
    deadline: Optional[date_type] = None
    group: Optional[str] = None
    period: Optional[str] = None
    weekly_day: Optional[str] = None
    weekly_days: Optional[list[str]] = None
    reminder_time: Optional[str] = None
    repeat_until_completed: Optional[bool] = None
    nudge_interval_minutes: Optional[int] = None
    reset_time: Optional[str] = None
    weekly_reset_day: Optional[str] = None
    monthly_reset_day: Optional[int] = None
    interval_days: Optional[int] = None
    direction: Optional[str] = None
    step: Optional[float] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class GoalGroupUpdate(BaseModel):
    goal_ids: list[int]
    name: str


class GoalGroupEnd(BaseModel):
    goal_ids: list[int]


class GoalGroupSettingsUpdate(BaseModel):
    icon: Optional[str] = None
    color: Optional[str] = None


class GoalGroupSettingsRead(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None


class GoalProgressUpdate(BaseModel):
    current: Optional[float] = None  # set the manual value
    add: Optional[float] = None      # or add to it (a contribution)


class GoalCheckinUpdate(BaseModel):
    scheduled_for: date_type
    completed: bool = True
    allow_overdue: bool = False


class GoalTaskRead(BaseModel):
    goal_id: int
    name: str
    period: str
    scheduled_for: date_type
    completed: bool
    missed: bool
    reminder_time: Optional[str] = None


class ReminderCreate(BaseModel):
    title: str
    scheduled_for: date_type
    reminder_time: Optional[str] = None
    notes: Optional[str] = None
    repeat_until_completed: bool = False
    nudge_interval_minutes: Optional[int] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    scheduled_for: Optional[date_type] = None
    reminder_time: Optional[str] = None
    notes: Optional[str] = None
    completed: Optional[bool] = None
    repeat_until_completed: Optional[bool] = None
    nudge_interval_minutes: Optional[int] = None


class ReminderRead(BaseModel):
    id: int
    title: str
    scheduled_for: date_type
    reminder_time: Optional[str] = None
    notes: Optional[str] = None
    completed: bool
    repeat_until_completed: bool = False
    nudge_interval_minutes: Optional[int] = None
    created_at: datetime


class CalendarEventCreate(BaseModel):
    title: str
    scheduled_for: date_type
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    scheduled_for: Optional[date_type] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class CalendarEventRead(BaseModel):
    id: int
    title: str
    scheduled_for: date_type
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class ScheduleItemRead(BaseModel):
    id: str
    source: str  # event | reminder | routine | goal_deadline
    source_id: int
    title: str
    scheduled_for: date_type
    reminder_time: Optional[str] = None
    completed: bool
    missed: bool
    notes: Optional[str] = None
    period: Optional[str] = None
    repeat_until_completed: bool = False
    nudge_interval_minutes: Optional[int] = None
    end_time: Optional[str] = None
    location: Optional[str] = None


class GoalHistoryRead(BaseModel):
    value: float
    at: datetime


class GoalRaise(BaseModel):
    target: float


class GoalRead(BaseModel):
    id: int
    name: str
    kind: str
    group: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    resolved_icon: str = "target"
    resolved_color: str = "pine"
    group_icon: Optional[str] = None
    group_color: Optional[str] = None
    history: list[GoalHistoryRead] = []
    milestones: list[GoalHistoryRead] = []
    target: Optional[float] = None
    account_id: Optional[int] = None
    account_ids: list[int] = []
    category: Optional[str] = None
    financial_metric: Optional[str] = None
    financial_rule: Optional[str] = None
    financial_source: Optional[str] = None
    current: Optional[float] = None
    anchor_value: Optional[float] = None
    since: Optional[date_type] = None
    deadline: Optional[date_type] = None
    period: str = "once"
    weekly_day: Optional[str] = None
    weekly_days: list[str] = []
    reminder_time: Optional[str] = None
    repeat_until_completed: bool = False
    nudge_interval_minutes: Optional[int] = None
    reset_time: str = "00:00"
    weekly_reset_day: str = "sunday"
    monthly_reset_day: int = 1
    interval_days: Optional[int] = None
    direction: str = "reach"
    step: float = 1.0
    # computed at read time by the goal type
    current_value: float
    pct: Optional[float] = None
    status: str
    unit: str
    linked_label: Optional[str] = None
    days: Optional[int] = None
    best_days: Optional[int] = None
    weekly_streak: int = 0
    archived_at: Optional[datetime] = None


class ExchangeRequest(BaseModel):
    public_token: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    timezone: str | None = None


class ChatResponse(BaseModel):
    reply: str
    actions: list[str] = []
    refresh: bool = False
    ui_actions: list[dict] = Field(default_factory=list)
