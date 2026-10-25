"""Run one controlled AMP MVP end-to-end cycle.

This module intentionally provides only an explicit, synchronous entry point.  It
must not be scheduled or run concurrently: cross-run idempotency is not yet
provided by the persistence model.
"""

from collections.abc import Callable
from typing import Any

from db.session import SessionLocal
from services.editorial.service import EditorialService
from services.intelligence.content_generation_service import (
    IntelligenceContentGenerationService,
)
from services.intelligence.factory import create_intelligence_content_generation_service
from services.intelligence.service import IntelligenceService
from services.news.service import NewsService
from services.publisher.agent import PublisherAgent
from services.trends.service import TrendService


def _collect_raw_news(news_service: NewsService) -> list[Any]:
    """Collect raw items without running ``NewsService.process`` twice."""
    return [
        item
        for collector in news_service.collectors
        for item in collector.collect()
    ]


def run_mvp_cycle(
    *,
    news_service: NewsService | None = None,
    intelligence_service: IntelligenceService | None = None,
    content_service: IntelligenceContentGenerationService | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    publisher_agent_factory: Callable[[Any], PublisherAgent] = PublisherAgent,
) -> dict[str, Any]:
    """Run one controlled News -> Intelligence -> Content/Media -> Publish cycle.

    Content/media generation is synchronous, so publication starts only after
    ``content_service.generate`` returns.  Media generation failures remain
    represented in the content results; the existing publisher decides whether
    a safe text-only publication is possible.

    Cross-run idempotency is intentionally not implemented here.  Until a
    stable source identity is persisted, this entry point is for explicit,
    non-concurrent controlled runs only.
    """
    news = news_service if news_service is not None else NewsService()
    intelligence = intelligence_service or IntelligenceService(
        news,
        TrendService(),
        EditorialService(),
    )
    content = content_service or create_intelligence_content_generation_service()

    raw_news = _collect_raw_news(news)
    approved = intelligence.analyze(raw_news)
    content_results = content.generate(approved)

    db = session_factory()
    try:
        publication_results = publisher_agent_factory(db).run()
    finally:
        db.close()

    return {
        "collected_count": len(raw_news),
        "approved_count": len(approved),
        "content_results": content_results,
        "publication_results": publication_results,
    }
