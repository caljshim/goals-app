from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.budget.db import get_session
from app.budget.models import Budget
from app.budget.schemas import BudgetCreate, BudgetRead, BudgetUpdate

router = APIRouter(prefix="/api", tags=["budgets"])


@router.get("/budgets", response_model=list[BudgetRead])
def list_budgets(session: Session = Depends(get_session)):
    return session.exec(select(Budget)).all()


@router.post("/budgets", response_model=BudgetRead, status_code=201)
def create_budget(body: BudgetCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(Budget).where(Budget.category == body.category)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Budget for this category already exists")
    budget = Budget(**body.model_dump())
    session.add(budget); session.commit(); session.refresh(budget)
    return budget


@router.patch("/budgets/{budget_id}", response_model=BudgetRead)
def update_budget(budget_id: int, body: BudgetUpdate, session: Session = Depends(get_session)):
    budget = session.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    budget.monthly_limit = body.monthly_limit
    session.add(budget); session.commit(); session.refresh(budget)
    return budget


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int, session: Session = Depends(get_session)):
    budget = session.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    session.delete(budget); session.commit()
    return Response(status_code=204)
