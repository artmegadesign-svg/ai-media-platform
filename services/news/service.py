from collections.abc import Iterable

from services.news.collectors import (
    AnthropicNewsCollector,
    GoogleAINewsCollector,
    NewsCollector,
    OpenAINewsCollector,
)
from services.news.models import NewsItem
from services.news.normalizer import NewsNormalizer
from services.news.scorer import NewsScorer


class NewsService:
    """Orchestrate collection, normalization, scoring, and ranking."""

    def __init__(
        self,
        collectors: list[NewsCollector] | None = None,
        normalizer: NewsNormalizer | None = None,
        scorer: NewsScorer | None = None,
        limit: int = 10,
    ) -> None:
        self.collectors = collectors or [
            OpenAINewsCollector(), AnthropicNewsCollector(), GoogleAINewsCollector()
        ]
        self.normalizer = normalizer or NewsNormalizer()
        self.scorer = scorer or NewsScorer()
        self.limit = limit

    def collect_news(self) -> list[NewsItem]:
        collected = [item for collector in self.collectors for item in collector.collect()]
        return self.process(collected)

    def process(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        """Normalize, score, and rank news items supplied by a caller."""
        news = self.normalizer.normalize(list(items))
        for item in news:
            item.score = self.scorer.score(item)
        return sorted(news, key=lambda item: item.score, reverse=True)[: self.limit]
