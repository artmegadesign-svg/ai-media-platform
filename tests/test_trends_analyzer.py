from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services.news.models import NewsItem as StandardNewsItem
from services.trends import TrendAnalyzer


@dataclass
class NewsItem:
    title: str
    source: str
    category: str = "model_release"


def test_analyzer_extracts_repeated_topic_and_counts_mentions():
    signals = TrendAnalyzer().analyze(
        [
            NewsItem("OpenAI выпустила GPT-5", "one"),
            NewsItem("GPT-5 показывает новые возможности", "two"),
        ]
    )
    gpt = next(signal for signal in signals if signal.keyword == "GPT-5")
    assert gpt.mentions == 2
    assert gpt.source_count == 2


def test_standard_news_tracks_exact_membership_dates_and_deduplicates_ids():
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    first = StandardNewsItem(
        id="first", title="OpenAI releases GPT-5", source="OpenAI",
        url="https://openai.com/first", published_at=now - timedelta(days=1),
    )
    second = StandardNewsItem(
        id="second", title="GPT-5 research", source="Other",
        url="https://example.com/second", published_at=now.replace(tzinfo=None),
    )
    unrelated = StandardNewsItem(
        id="third", title="Google releases Gemini", source="Google",
        url="https://blog.google/third", published_at=now,
    )

    signals = TrendAnalyzer().analyze([first, first, second, unrelated])
    gpt = next(signal for signal in signals if signal.keyword == "GPT-5")
    openai = next(signal for signal in signals if signal.keyword == "OpenAI")

    assert gpt.news_ids == ["first", "second"]
    assert gpt.mentions == 2
    assert gpt.source_count == 2
    assert gpt.latest_published_at == now
    assert gpt.category == "model_release"
    assert openai.news_ids == ["first"]
    assert "third" not in gpt.news_ids
