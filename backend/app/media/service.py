import base64
import hashlib
import io
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlmodel import Session, select

from app.media.models import MediaAsset, utc_now


MAX_UPLOAD_BYTES = 12_000_000
MAX_NORMALIZED_BYTES = 5_000_000
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 2_000
MAX_CHAT_IMAGES = 4
MAX_CHAT_IMAGE_BYTES = 12_000_000
SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


class MediaError(Exception):
    pass


class MediaNotFound(MediaError):
    pass


def _clean_filename(value: str | None) -> str:
    filename = Path(value or "upload").name.strip()
    if not filename:
        filename = "upload"
    return filename[:240]


def normalize_image(raw: bytes) -> tuple[bytes, int, int]:
    if not raw:
        raise MediaError("Image is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise MediaError("Image exceeds the 12 MB upload limit")

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.format not in SUPPORTED_FORMATS:
                    raise MediaError(
                        "Image must be JPEG, PNG, GIF, or WebP"
                    )
                opened.seek(0)
                image = ImageOps.exif_transpose(opened)
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise MediaError("Image could not be safely decoded") from exc

    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")
    image.thumbnail(
        (MAX_IMAGE_EDGE, MAX_IMAGE_EDGE),
        Image.Resampling.LANCZOS,
    )

    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=88,
        optimize=True,
        exif=b"",
        icc_profile=None,
    )
    normalized = output.getvalue()
    if len(normalized) > MAX_NORMALIZED_BYTES:
        raise MediaError("Normalized image exceeds the 5 MB limit")
    return normalized, image.width, image.height


def create_asset(
    session: Session,
    raw: bytes,
    filename: str | None,
) -> MediaAsset:
    normalized, width, height = normalize_image(raw)
    asset = MediaAsset(
        id=str(uuid4()),
        filename=_clean_filename(filename),
        media_type="image/jpeg",
        byte_size=len(normalized),
        width=width,
        height=height,
        sha256=hashlib.sha256(normalized).hexdigest(),
        data=normalized,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def get_asset(session: Session, asset_id: str) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise MediaNotFound("Image not found")
    return asset


def load_assets(
    session: Session,
    asset_ids: list[str],
) -> list[MediaAsset]:
    if len(asset_ids) > MAX_CHAT_IMAGES:
        raise MediaError(
            f"A chat request can contain at most {MAX_CHAT_IMAGES} images"
        )
    if len(asset_ids) != len(set(asset_ids)):
        raise MediaError("Duplicate image IDs are not allowed")
    if not asset_ids:
        return []
    assets = {
        asset.id: asset
        for asset in session.exec(
            select(MediaAsset).where(
                MediaAsset.id.in_(asset_ids),
                MediaAsset.deleted_at.is_(None),
            )
        ).all()
    }
    missing = [asset_id for asset_id in asset_ids if asset_id not in assets]
    if missing:
        raise MediaNotFound("One or more images were not found")
    ordered = [assets[asset_id] for asset_id in asset_ids]
    if sum(asset.byte_size for asset in ordered) > MAX_CHAT_IMAGE_BYTES:
        raise MediaError("Chat images exceed the 12 MB combined limit")
    return ordered


def image_content_block(asset: MediaAsset) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": asset.media_type,
            "data": base64.b64encode(asset.data).decode("ascii"),
        },
    }


def soft_delete_asset(session: Session, asset_id: str) -> None:
    asset = get_asset(session, asset_id)
    asset.deleted_at = utc_now()
    asset.data = b""
    asset.byte_size = 0
    session.add(asset)
    session.commit()
