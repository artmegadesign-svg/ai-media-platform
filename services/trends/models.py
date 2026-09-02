from pydantic import BaseModel, Field


class TrendSignal(BaseModel):
    """A topic observed in one or more news items."""

    keyword: str
    mentions: int = Field(ge=1)
    growth_score: float = Field(default=0, ge=0, le=100)
    source_count: int = Field(ge=1)
    category: str
