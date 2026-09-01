from collections.abc import Iterable

from services.trends.analyzer import TrendAnalyzer
from services.trends.models import TrendSignal
from services.trends.scorer import TrendScorer


class TrendService:
    """Independent NewsItem -> trend analysis interface."""

    def __init__(
        self, analyzer: TrendAnalyzer | None = None, scorer: TrendScorer | None = None
    ):
        self.analyzer = analyzer or TrendAnalyzer()
        self.scorer = scorer or TrendScorer()

    def analyze(self, news_items: Iterable[object]) -> list[TrendSignal]:
        signals = (
            self.scorer.score(signal) for signal in self.analyzer.analyze(news_items)
        )
        return sorted(
            signals,
            key=lambda signal: (
                -signal.growth_score,
                -signal.mentions,
                signal.keyword.casefold(),
            ),
        )
