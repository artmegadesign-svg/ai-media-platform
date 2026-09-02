from datetime import datetime, timezone

from services.news.collectors.base import NewsCollector
from services.news.models import NewsItem
from services.news.scorer import NewsScorer
from services.news.service import NewsService


class StubCollector(NewsCollector):
    def collect(self) -> list[NewsItem]:
        now = datetime(2026, 8, 25, tzinfo=timezone.utc)
        return [
            NewsItem(source="Other", title="Minor", url="https://example.com/minor"),
            NewsItem(
                source="Anthropic",
                title="Model",
                url="https://example.com/model",
                category="model_release",
                published_at=now,
            ),
        ]


def test_service_scores_sorts_and_limits_collected_news():
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    service = NewsService(collectors=[StubCollector()], scorer=NewsScorer(now), limit=1)

    result = service.collect_news()

    assert len(result) == 1
    assert result[0].title == "Model"
    assert result[0].score == 70
