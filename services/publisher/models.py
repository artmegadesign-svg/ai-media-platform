from datetime import datetime

from pydantic import BaseModel


class PublishResult(BaseModel):
    success: bool
    platform_post_id: str | None = None
    error: str | None = None
    published_at: datetime | None = None
