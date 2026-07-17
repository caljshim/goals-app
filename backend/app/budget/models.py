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


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True, unique=True)
    monthly_limit: float


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
