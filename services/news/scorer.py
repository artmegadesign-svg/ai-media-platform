from datetime import datetime, timezone

from services.news.models import NewsItem


class NewsScorer:
    """Deterministic, configurable relevance score for a news record."""

    SOURCE_SCORES = {"openai": 20, "anthropic": 20, "google": 20, "google ai": 20}
    CATEGORY_SCORES = {"model_release": 30, "research": 20, "other": 5}

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now

    def score(self, news: NewsItem) -> int:
        now = self.now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        total = self.SOURCE_SCORES.get(news.source.casefold(), 5)
        published = news.published_at
        if published:
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            age = (now.astimezone(timezone.utc).date() - published.astimezone(timezone.utc).date()).days
            if age == 0:
                total += 20
            elif 0 < age <= 7:
                total += 10
        total += self.CATEGORY_SCORES.get(news.category.casefold(), self.CATEGORY_SCORES["other"])
        return min(100, max(0, total))
