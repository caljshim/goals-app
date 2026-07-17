import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.budget.db import get_session
from app.budget.services.summary import build_summary

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/summary")
def dashboard_summary(month: str, session: Session = Depends(get_session)):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=422, detail="month must be in YYYY-MM format")
    return build_summary(session, month)
