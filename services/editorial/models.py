"""Value objects produced by the editorial intelligence layer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditorialDecision:
    """The publication recommendation for one news item."""

    news_id: object
    publish: bool
    priority: str
    format: str
    reason: str
    score: float

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class EditorialEvaluation:
    """Normalized editorial factors, each expressed on a 0-100 scale."""

    news_id: object
    category: str
    trend_score: float
    authority: float
    impact: float
    audience: float
    novelty: float
