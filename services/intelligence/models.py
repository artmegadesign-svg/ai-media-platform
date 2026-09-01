"""Result models for the news intelligence orchestrator."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from services.editorial.models import EditorialDecision


class IntelligenceResult(BaseModel):
    """A normalized news item and the intelligence attached to it."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    news: Any
    trend: Any | None
    editorial: EditorialDecision

    @property
    def publish(self) -> bool:
        """Proxy the editorial publication decision."""
        return self.editorial.publish

    @property
    def score(self) -> float:
        """Proxy the editorial score without storing a duplicate value."""
        return self.editorial.score
