"""Normalize news and trend data into editorial factors."""

from collections.abc import Mapping
from math import isfinite
from typing import Any
from datetime import datetime, timedelta, timezone

from services.editorial.models import EditorialEvaluation
from services.news.normalizer import classify_category, event_category, event_impact, has_ai_context
from services.news.urls import approved_url
from services.trends import scorer as trend_scoring
from services.trends.models import TrendSignal


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

    title = _value(news, "title")
    category = classify_category(
        str(title or ""), _value(news, "category"),
        content=str(_value(news, "content", default="") or ""),
    )
    return max(
        (trend for trend in trends if matches(trend)),
        key=lambda trend: (_bounded_trend(news, trend, category), trend_score(trend))
        if title is not None else (trend_score(trend),),
        default=None,
    )


_OFFICIAL_DOMAINS = {
    "openai": "openai.com",
    "anthropic": "anthropic.com",
    "google": "blog.google",
    "google ai": "blog.google",
}


def _source_authority(news: object) -> float:
    """Source label and an exact approved HTTPS host must agree."""
    source = _value(news, "source", default="")
    domain = _OFFICIAL_DOMAINS.get(str(source).strip().casefold())
    return 100.0 if domain and approved_url(
        str(_value(news, "url", default="")), (domain, f"www.{domain}"),
    ) else 0.0


def _publication_date(news: object) -> datetime | None:
    published = _value(news, "published_at")
    if not isinstance(published, datetime):
        return None
    return published.replace(tzinfo=timezone.utc) if published.tzinfo is None else published.astimezone(timezone.utc)


def _blocked_reason(news: object, category: str, evidence: str) -> str | None:
    # Factor-only adapters retain their explicit contract. Real news records,
    # including mappings and NewsItem subclasses, always undergo the gates.
    if _value(news, "title") is None:
        return None
    if _source_authority(news) == 0:
        return "unverified official source URL"
    published = _publication_date(news)
    now = trend_scoring._utc_now()
    if published is None or not timedelta(0) <= now - published <= timedelta(days=7):
        return "publication date missing, future or older than 7 days"
    if category not in {"model_release", "api_release", "tool_release", "product_update", "research"} or evidence != category:
        return "no confirmed primary AI event"
    return None


def _bounded_trend(news: object, trend: object | None, category: str) -> float:
    actual = trend_score(trend)
    if _value(news, "title") is None or trend is None:
        return actual
    # A brand cluster may contain different events. It cannot supply this
    # article with another member's freshness, source count or category bonus.
    own = TrendSignal(
        keyword=str(_value(trend, "keyword", default="")), mentions=1,
        source_count=1, category=category, latest_published_at=_publication_date(news),
    )
    return min(actual, trend_scoring.TrendScorer().score(own).growth_score)


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

        title = str(_value(news, "title", default="") or "")
        content = str(_value(news, "content", default="") or "")
        category = classify_category(title, _value(news, "category", "type", "news_type"), content=content)
        evidence_category = event_category(title, content)
        relevant = has_ai_context(f"{title} {content}")
        audience = _value(news, "audience", "audience_score")
        if audience is None:
            audience = 80 if relevant else 0
        impact = _value(news, "impact", "impact_score")
        if impact is None:
            impact = event_impact(title, content, category) if relevant else 0

        return EditorialEvaluation(
            news_id=news_id,
            category=category,
            trend_score=_bounded_trend(news, trend, category),
            authority=_factor(authority),
            impact=_factor(impact),
            audience=_factor(audience),
            # Publication date is not evidence of novelty.
            novelty=_factor(_value(news, "novelty", "novelty_score", default=0)),
            blocked_reason=_blocked_reason(news, category, evidence_category),
        )
