from datetime import datetime, timezone

from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


class EditorialNewsItem(NewsItem):
    authority: float
    impact: float
    audience: float
    novelty: float


def test_real_intelligence_layers_process_supplied_news_without_collecting():
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    service = IntelligenceService(
        NewsService(scorer=NewsScorer(now)),
        TrendService(),
        EditorialService(),
    )
    item = EditorialNewsItem(
        source="OpenAI",
        title="  OpenAI   releases GPT-5 ",
        url="https://OPENAI.com/news/gpt-5/?utm_source=test",
        published_at=now,
        category="model_release",
        authority=100,
        impact=100,
        audience=100,
        novelty=100,
    )

    results = service.analyze([item])

    assert len(results) == 1
    assert results[0].news.title == "OpenAI releases GPT-5"
    assert results[0].news.url == "https://openai.com/news/gpt-5"
    assert results[0].news.score == 70
    assert results[0].publish is True
