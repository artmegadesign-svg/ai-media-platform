from dataclasses import dataclass

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
