from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.budget.db import get_session
from app.budget.schemas import MerchantRuleCreate, MerchantRuleRead
from app.budget.services import rules as rules_svc

router = APIRouter(prefix="/api", tags=["rules"])


@router.get("/merchant-rules", response_model=list[MerchantRuleRead])
def list_merchant_rules(session: Session = Depends(get_session)):
    return rules_svc.list_rules(session)


@router.post("/merchant-rules", response_model=MerchantRuleRead)
def create_merchant_rule(body: MerchantRuleCreate, session: Session = Depends(get_session)):
    try:
        rule = rules_svc.set_merchant_rule(session, body.merchant, body.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return MerchantRuleRead(id=rule.id, merchant=rule.merchant, category=rule.category)


@router.delete("/merchant-rules/{rule_id}", status_code=204)
def delete_merchant_rule(rule_id: int, session: Session = Depends(get_session)):
    if not rules_svc.delete_rule(session, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return Response(status_code=204)
