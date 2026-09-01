from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """A provider-independent representation of a news story."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    title: str
    url: str
    content: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    category: str = "other"
    score: int = Field(default=0, ge=0, le=100)
