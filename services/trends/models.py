from datetime import datetime

from pydantic import BaseModel, Field


class TrendSignal(BaseModel):
    """A topic observed in one or more news items."""

    keyword: str
    mentions: int = Field(ge=1)
    growth_score: float = Field(default=0, ge=0, le=100)
    source_count: int = Field(ge=1)
    category: str
    # Membership is explicit: a shared category alone does not link a story.
    news_ids: list[str | int] = Field(default_factory=list)
    latest_published_at: datetime | None = None
