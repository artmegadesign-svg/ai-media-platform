from datetime import timedelta

import pytest

from services.trends import TrendService


def test_service_scores_and_sorts_top_trends():
    items = [
        {"title": "OpenAI выпустила GPT-5", "source": "one"},
        {"title": "GPT-5 показывает новые возможности", "source": "two"},
        {"title": "Google опубликовала research", "source": "three"},
    ]
    trends = TrendService().analyze(items)
    assert trends == sorted(
        trends,
        key=lambda trend: (
            -trend.growth_score,
            -trend.mentions,
            trend.keyword.casefold(),
        ),
    )
    assert next(trend for trend in trends if trend.keyword == "GPT-5").mentions == 2


@pytest.mark.parametrize(("age", "expected"), [(None, 53.33), (1, 53.33), (0, 73.33), (-1, 53.33)])
def test_service_uses_actual_publication_date(age, expected, fixed_editorial_now):
    now = fixed_editorial_now
    items = [{
        "id": "n-1", "source": "OpenAI", "title": "OpenAI releases GPT-5",
        "category": "other",
        "published_at": None if age is None else now - timedelta(days=age),
    }]

    signal = next(t for t in TrendService().analyze(items) if t.keyword == "OpenAI")

    assert signal.growth_score == expected
    assert signal.news_ids == ["n-1"]


@pytest.mark.parametrize(("title", "category"), [
    ("OpenAI releases GPT-5", "model_release"),
    ("OpenAI releases an AI tool powered by GPT-5", "tool_release"),
    ("OpenAI releases a research paper about GPT-5", "research"),
    ("OpenAI releases a financial report", "general"),
])
def test_trends_uses_the_same_event_categories_as_news(title, category):
    signals = TrendService().analyze([{"id": "n-1", "title": title, "source": "OpenAI"}])

    assert signals
    assert all(signal.category == category for signal in signals)
