from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary, Text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MediaAsset(SQLModel, table=True):
    __tablename__ = "media_asset"

    id: str = Field(primary_key=True)
    filename: str
    media_type: str
    byte_size: int
    width: int
    height: int
    sha256: str = Field(index=True)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, index=True)
    deleted_at: Optional[datetime] = None
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
