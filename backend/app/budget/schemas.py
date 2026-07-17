from datetime import date
from typing import Optional

from pydantic import BaseModel


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


class TransactionCreate(BaseModel):
    account_id: int
    date: date
    name: str
    amount: float
    merchant_name: Optional[str] = None
    user_category: Optional[str] = None


class TransactionUpdate(BaseModel):
    user_category: Optional[str] = None


class BudgetRead(BaseModel):
    id: int
    category: str
    monthly_limit: float


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float


class BudgetUpdate(BaseModel):
    monthly_limit: float


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
