from dataclasses import dataclass

from services.editorial.evaluator import EditorialEvaluator


@dataclass
class NewsItem:
    id: str
    category: str
    impact: float
    authority: float
    audience: float
    novelty: float


def test_evaluator_extracts_news_and_trend_factors():
    news = NewsItem("n-1", "research", 80, 90, 70, 60)

    result = EditorialEvaluator().evaluate(news, {"score": 75})

    assert result.news_id == "n-1"
    assert result.category == "research"
    assert result.trend_score == 75
    assert (result.authority, result.impact, result.audience, result.novelty) == (
        90,
        80,
        70,
        60,
    )


def test_evaluator_clamps_factors_to_score_scale():
    news = {"id": 1, "impact": 120, "authority": -5, "audience": 50, "novelty": 10}
    result = EditorialEvaluator().evaluate(news, {"growth": 200})

    assert result.impact == 100
    assert result.authority == 0
    assert result.trend_score == 100
