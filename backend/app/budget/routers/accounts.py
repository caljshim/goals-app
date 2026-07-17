from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.budget.db import get_session
from app.budget.models import Account
from app.budget.schemas import AccountRead

router = APIRouter(prefix="/api", tags=["accounts"])


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()
