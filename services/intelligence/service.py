"""Orchestrate the independent news, trends, and editorial layers."""

from collections.abc import Iterable
from typing import Any, Protocol

from services.editorial.models import EditorialDecision
from services.intelligence.models import IntelligenceResult


class NewsServiceProtocol(Protocol):
    def process(self, items: Iterable[object]) -> list[object]: ...


class TrendServiceProtocol(Protocol):
    def analyze(self, news: list[object]) -> list[object]: ...


class EditorialServiceProtocol(Protocol):
    def evaluate(
        self, news: Iterable[object], trends: Iterable[object]
    ) -> list[EditorialDecision]: ...


def _identifier(item: object, *names: str) -> object | None:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return None


class IntelligenceService:
    """Build an approved shortlist; publishing is intentionally out of scope."""

    def __init__(
        self,
        news_service: NewsServiceProtocol,
        trend_service: TrendServiceProtocol,
        editorial_service: EditorialServiceProtocol,
    ) -> None:
        self.news_service = news_service
        self.trend_service = trend_service
        self.editorial_service = editorial_service

    def analyze(
        self, items: Iterable[object], limit: int | None = 10
    ) -> list[IntelligenceResult]:
        """Run all intelligence stages and return approved results by score."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative or None")

        news = list(self.news_service.process(items))
        if not news:
            return []

        trends = list(self.trend_service.analyze(news))
        decisions = list(self.editorial_service.evaluate(news, trends))
        if not decisions:
            return []

        news_by_id = self._index(news, "news_id", "id")
        trends_by_id = self._index(trends, "news_id")
        results = [
            IntelligenceResult(
                news=news_by_id[decision.news_id],
                trend=trends_by_id.get(decision.news_id),
                editorial=decision,
            )
            for decision in decisions
            if decision.publish and decision.news_id in news_by_id
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return results if limit is None else results[:limit]

    @staticmethod
    def _index(items: Iterable[Any], *id_fields: str) -> dict[object, Any]:
        indexed: dict[object, Any] = {}
        for item in items:
            identifier = _identifier(item, *id_fields)
            if identifier is not None:
                indexed[identifier] = item
        return indexed
