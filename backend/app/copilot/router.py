from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.budget.db import get_session
from app.budget.schemas import ChatRequest, ChatResponse
from app.copilot.agent import run_copilot
from app.media.service import (
    MediaError,
    MediaNotFound,
    image_content_block,
    load_assets,
)

router = APIRouter(prefix="/api", tags=["copilot"])


def _multimodal_messages(body: ChatRequest, session: Session) -> list[dict]:
    asset_ids: list[str] = []
    for message in body.messages:
        if message.attachment_ids and message.role != "user":
            raise HTTPException(
                status_code=422,
                detail="Only user messages can contain image attachments",
            )
        asset_ids.extend(message.attachment_ids)
    unique_ids = list(dict.fromkeys(asset_ids))
    try:
        assets = {
            asset.id: asset
            for asset in load_assets(session, unique_ids)
        }
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    messages: list[dict] = []
    for message in body.messages:
        if not message.attachment_ids:
            messages.append(
                {"role": message.role, "content": message.content}
            )
            continue
        content = [
            image_content_block(assets[asset_id])
            for asset_id in message.attachment_ids
        ]
        content.append(
            {
                "type": "text",
                "text": message.content.strip()
                or "Please analyze the attached image.",
            }
        )
        messages.append({"role": message.role, "content": content})
    return messages


@router.post("/assistant/chat", response_model=ChatResponse)
def assistant_chat(body: ChatRequest, session: Session = Depends(get_session)):
    if not body.messages:
        raise HTTPException(status_code=422, detail="messages must not be empty")
    messages = _multimodal_messages(body, session)
    try:
        return run_copilot(
            session,
            messages,
            timezone_name=body.timezone,
        )
    except RuntimeError as exc:  # missing API key / config
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — Anthropic/API failures
        raise HTTPException(status_code=502, detail=f"Assistant error: {exc}")
