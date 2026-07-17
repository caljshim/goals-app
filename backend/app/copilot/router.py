from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.budget.db import get_session
from app.budget.schemas import ChatRequest, ChatResponse
from app.copilot.agent import run_copilot

router = APIRouter(prefix="/api", tags=["copilot"])


@router.post("/assistant/chat", response_model=ChatResponse)
def assistant_chat(body: ChatRequest, session: Session = Depends(get_session)):
    if not body.messages:
        raise HTTPException(status_code=422, detail="messages must not be empty")
    try:
        return run_copilot(session, [m.model_dump() for m in body.messages])
    except RuntimeError as exc:  # missing API key / config
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — Anthropic/API failures
        raise HTTPException(status_code=502, detail=f"Assistant error: {exc}")
