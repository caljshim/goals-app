from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session

from app.budget.db import get_session
from app.media.schemas import MediaAssetRead
from app.media.service import (
    MAX_UPLOAD_BYTES,
    MediaError,
    MediaNotFound,
    create_asset,
    get_asset,
    soft_delete_asset,
)


router = APIRouter(prefix="/api/media", tags=["media"])


@router.post("", response_model=MediaAssetRead, status_code=201)
async def upload_image(
    request: Request,
    session: Session = Depends(get_session),
):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Image exceeds the 12 MB upload limit",
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
    if not request.headers.get("content-type", "").lower().startswith("image/"):
        raise HTTPException(status_code=415, detail="Content-Type must be an image")
    raw = await request.body()
    try:
        return create_asset(
            session,
            raw,
            request.headers.get("x-filename"),
        )
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{asset_id}", response_model=MediaAssetRead)
def image_metadata(
    asset_id: str,
    session: Session = Depends(get_session),
):
    try:
        return get_asset(session, asset_id)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{asset_id}/content")
def image_content(
    asset_id: str,
    session: Session = Depends(get_session),
):
    try:
        asset = get_asset(session, asset_id)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=asset.data,
        media_type=asset.media_type,
        headers={
            "Content-Disposition": (
                f"inline; filename*=UTF-8''{quote(asset.filename)}"
            ),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/{asset_id}", status_code=204)
def delete_image(
    asset_id: str,
    session: Session = Depends(get_session),
):
    try:
        soft_delete_asset(session, asset_id)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
