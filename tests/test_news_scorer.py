from datetime import datetime, timedelta, timezone

from services.news.models import NewsItem
from services.news.scorer import NewsScorer


def test_score_combines_authority_today_and_model_release():
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    news = NewsItem(
        source="OpenAI",
        title="Release",
        url="https://example.com/release",
        published_at=now,
        category="model_release",
    )

    assert NewsScorer(now).score(news) == 70


def test_score_uses_week_and_fallback_weights():
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    news = NewsItem(
        source="Independent",
        title="Story",
        url="https://example.com/story",
        published_at=now - timedelta(days=5),
        category="unknown",
    )

    assert NewsScorer(now).score(news) == 20
