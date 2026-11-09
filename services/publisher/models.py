from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class PublicationReference:
    """All identity needed during I/O; deliberately contains no ORM state."""

    id: int
    post_id: int
    channel_id: int


class PublishResult(BaseModel):
    success: bool
    platform_post_id: str | None = None
    error: str | None = None
    published_at: datetime | None = None
    outcome: Literal["published", "failed", "unknown"] | None = None
    error_code: str | None = None
    gateway_http_status: int | None = None
    retry_after_at: datetime | None = None
