"""Normalize news and trend data into editorial factors."""

from collections.abc import Mapping
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from services.editorial.models import EditorialEvaluation
from services.news.normalizer import classify_category, has_ai_context


def _value(item: object | None, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, Mapping) and item.get(name) is not None:
            return item[name]
        if item is not None and getattr(item, name, None) is not None:
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
    return min(100.0, max(0.0, number)) if isfinite(number) else 0.0


def trend_score(trend: object | None) -> float:
    """Read the real trend contract and retain legacy input aliases."""
    return _factor(_value(trend, "growth_score", "trend_score", "score", "growth", default=0))


def select_trend(news: object, trends: list[object]) -> object | None:
    """Select one strongest member signal, shared by Editorial and Intelligence."""
    news_id = _value(news, "news_id", "id")

    def matches(trend: object) -> bool:
        member_id = _value(trend, "news_id")
        if member_id is not None:
            return news_id is not None and member_id == news_id
        member_ids = _value(trend, "news_ids")
        if member_ids is not None:
            return news_id is not None and news_id in member_ids
        # Retain explicit legacy topic links, never category-only links.
        topic = _value(news, "topic")
        return topic is not None and topic == _value(trend, "topic")

    return max((trend for trend in trends if matches(trend)), key=trend_score, default=None)


_OFFICIAL_DOMAINS = {
    "openai": "openai.com",
    "anthropic": "anthropic.com",
    "google": "blog.google",
    "google ai": "blog.google",
}
_IMPACT_BY_CATEGORY = {"model_release": 80, "research": 60, "tool_release": 60}


def _source_authority(news: object) -> float:
    """Only a matching official source and HTTPS domain establish authority."""
    source = _value(news, "source", default="")
    domain = _OFFICIAL_DOMAINS.get(str(source).strip().casefold())
    try:
        url = urlsplit(str(_value(news, "url", default="")))
        host = (url.hostname or "").casefold()
    except ValueError:
        return 0.0
    if (
        domain and url.scheme == "https" and not url.username and not url.password
        and (host == domain or host.endswith(f".{domain}"))
    ):
        return 100.0
    return 0.0


class EditorialEvaluator:
    """Extract the five editorial factors from a NewsItem and TrendSignal."""

    def evaluate(self, news: object, trend: object | None = None) -> EditorialEvaluation:
        news_id = _value(news, "news_id", "id")
        if news_id is None:
            raise ValueError("news must provide id or news_id")

        source = _value(news, "source")
        authority = _value(news, "authority", "authority_score")
        if authority is None:
            authority = _value(source, "authority", "authority_score")
        if authority is None:
            authority = _source_authority(news)

        text = f"{_value(news, 'title', default='')} {_value(news, 'content', default='')}"
        category = classify_category(text, _value(news, "category", "type", "news_type"))
        relevant = has_ai_context(text)
        audience = _value(news, "audience", "audience_score")
        if audience is None:
            audience = 80 if relevant else 0
        impact = _value(news, "impact", "impact_score")
        if impact is None:
            # An explicit category is preserved, but cannot invent evidence for
            # an otherwise missing impact factor.
            evidence_category = classify_category(text)
            impact = (
                _IMPACT_BY_CATEGORY.get(category, 0)
                if relevant and evidence_category == category else 0
            )

        return EditorialEvaluation(
            news_id=news_id,
            category=category,
            trend_score=trend_score(trend),
            authority=_factor(authority),
            impact=_factor(impact),
            audience=_factor(audience),
            # Publication date is not evidence of novelty.
            novelty=_factor(_value(news, "novelty", "novelty_score", default=0)),
        )
