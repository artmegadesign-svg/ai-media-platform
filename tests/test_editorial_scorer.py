from services.editorial.models import EditorialEvaluation
from services.editorial.scorer import EditorialScorer


def test_scorer_applies_editorial_weights():
    evaluation = EditorialEvaluation(
        news_id=1,
        category="research",
        trend_score=90,
        authority=80,
        impact=70,
        audience=60,
        novelty=50,
    )

    assert EditorialScorer().score(evaluation) == 74
