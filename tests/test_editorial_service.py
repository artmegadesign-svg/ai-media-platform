from services.editorial.service import EditorialService


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
