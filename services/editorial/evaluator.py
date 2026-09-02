"""Normalize news and trend data into editorial factors."""

from collections.abc import Mapping
from typing import Any

from services.editorial.models import EditorialEvaluation


def _value(item: object | None, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        if item is not None and hasattr(item, name):
            return getattr(item, name)
    return default


def _factor(value: object) -> float:
    """Return a safe factor on the common 0-100 scale."""
    if isinstance(value, bool):
        return 100.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, number))


class EditorialEvaluator:
    """Extract the five editorial factors from a NewsItem and TrendSignal."""

    def evaluate(self, news: object, trend: object | None = None) -> EditorialEvaluation:
        news_id = _value(news, "news_id", "id")
        if news_id is None:
            raise ValueError("news must provide id or news_id")

        source = _value(news, "source")
        authority = _value(news, "authority", "authority_score")
        if authority is None:
            authority = _value(source, "authority", "authority_score", default=0)

        return EditorialEvaluation(
            news_id=news_id,
            category=str(_value(news, "category", "type", "news_type", default="news")),
            trend_score=_factor(
                _value(trend, "trend_score", "score", "growth", default=0)
            ),
            authority=_factor(authority),
            impact=_factor(_value(news, "impact", "impact_score", default=0)),
            audience=_factor(
                _value(news, "audience", "audience_score", default=0)
            ),
            novelty=_factor(_value(news, "novelty", "novelty_score", default=0)),
        )
