import pytest

from services.editorial.service import EditorialService
from services.trends.models import TrendSignal


def _news(news_id: int, category: str, factor: int) -> dict[str, object]:
    return {
        "id": news_id,
        "category": category,
        "impact": factor,
        "authority": factor,
        "audience": factor,
        "novelty": factor,
    }


def test_service_applies_threshold_format_and_descending_sort():
    news = [
        _news(1, "tool_release", 69),
        _news(2, "model_release", 100),
        _news(3, "research", 70),
        _news(4, "funding", 80),
    ]
    trends = [
        {"news_id": 1, "score": 69},
        {"news_id": 2, "score": 100},
        {"news_id": 3, "score": 70},
        {"news_id": 4, "score": 80},
    ]

    decisions = EditorialService().evaluate(news, trends)

    assert [decision.news_id for decision in decisions] == [2, 4, 3, 1]
    assert [decision.format for decision in decisions] == [
        "breaking",
        "news",
        "analysis",
        "guide",
    ]
    assert [decision.publish for decision in decisions] == [True, True, True, False]
    assert decisions[2].score == 70


def test_service_uses_strongest_matching_topic_trend():
    news = [_news(1, "research", 60) | {"topic": "agents"}]
    trends = [
        {"topic": "agents", "score": 20},
        {"topic": "agents", "score": 90},
    ]

    assert EditorialService().evaluate(news, trends)[0].score == 69


def test_membership_prevents_category_only_matches_and_selects_highest_growth_score():
    news = _news("n-1", "research", 60)
    unrelated = TrendSignal(
        keyword="Gemini", mentions=1, source_count=1, category="research",
        news_ids=["n-2"], growth_score=100,
    )
    weak = unrelated.model_copy(update={"news_ids": ["n-1"], "growth_score": 20})
    strong = unrelated.model_copy(update={"news_ids": ["n-1"], "growth_score": 90})
    unlinked = unrelated.model_copy(update={"news_ids": []})

    service = EditorialService()

    assert service._matching_trend(news, [unrelated, weak, strong, unlinked]) is strong
    assert service.evaluate([news], [unrelated, weak, strong, unlinked])[0].score == 69
    assert service._matching_trend(news, [unrelated, unlinked]) is None
    assert service._matching_trend(news, [{"category": "research", "score": 100}]) is None


@pytest.mark.parametrize(("score", "published", "priority"), [
    (69.99, False, "low"), (70, True, "normal"),
    (84.99, True, "normal"), (85, True, "high"),
])
def test_publication_and_priority_thresholds_are_unchanged(score, published, priority):
    decision = EditorialService().evaluate(
        [_news("n-1", "research", score)], [{"news_id": "n-1", "growth_score": score}]
    )[0]

    assert decision.score == score
    assert decision.publish is published
    assert decision.priority == priority
