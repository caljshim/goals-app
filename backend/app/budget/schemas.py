from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccountRead(BaseModel):
    id: int
    plaid_account_id: str
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
    date: date
    name: str
    merchant_name: Optional[str] = None
    amount: float
    category: Optional[str] = None
    user_category: Optional[str] = None
    effective_category: str
    pending: bool
    is_manual: bool
    reimburses_transaction_id: Optional[int] = None


class TransactionCreate(BaseModel):
    account_id: int
    date: date
    name: str
    amount: float
    merchant_name: Optional[str] = None
    user_category: Optional[str] = None


class TransactionUpdate(BaseModel):
    user_category: Optional[str] = None


class ReimburseUpdate(BaseModel):
    # The expense this incoming transaction reimburses; null unlinks it.
    target_id: Optional[int] = None


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


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float


class BudgetUpdate(BaseModel):
    monthly_limit: float


class GoalCreate(BaseModel):
    name: str
    kind: str  # save | spend_cap | numeric | streak
    target: Optional[float] = None
    account_id: Optional[int] = None
    category: Optional[str] = None
    current: Optional[float] = None
    since: Optional[date] = None
    deadline: Optional[date] = None
    period: Optional[str] = None  # once | daily | weekly | monthly
    weekly_day: Optional[str] = None
    weekly_days: Optional[list[str]] = None
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
    category: Optional[str] = None
    deadline: Optional[date] = None
    group: Optional[str] = None
    period: Optional[str] = None
    weekly_day: Optional[str] = None
    weekly_days: Optional[list[str]] = None
    reset_time: Optional[str] = None
    weekly_reset_day: Optional[str] = None
    monthly_reset_day: Optional[int] = None
    interval_days: Optional[int] = None
    direction: Optional[str] = None
    step: Optional[float] = None


class GoalProgressUpdate(BaseModel):
    current: Optional[float] = None  # set the manual value
    add: Optional[float] = None      # or add to it (a contribution)


class GoalCheckinUpdate(BaseModel):
    scheduled_for: date
    completed: bool = True
    allow_overdue: bool = False


class GoalTaskRead(BaseModel):
    goal_id: int
    name: str
    period: str
    scheduled_for: date
    completed: bool
    missed: bool


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
    history: list[GoalHistoryRead] = []
    milestones: list[GoalHistoryRead] = []
    target: Optional[float] = None
    account_id: Optional[int] = None
    category: Optional[str] = None
    current: Optional[float] = None
    since: Optional[date] = None
    deadline: Optional[date] = None
    period: str = "once"
    weekly_day: Optional[str] = None
    weekly_days: list[str] = []
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


class ExchangeRequest(BaseModel):
    public_token: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    actions: list[str] = []
    refresh: bool = False
    ui_actions: list[dict] = Field(default_factory=list)
