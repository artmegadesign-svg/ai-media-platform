from services.editorial.models import EditorialDecision
from services.intelligence.models import IntelligenceResult


def test_result_proxies_editorial_publish_and_score():
    decision = EditorialDecision("n1", True, "high", "breaking", "ready", 91.5)

    result = IntelligenceResult(news={"id": "n1"}, trend=None, editorial=decision)

    assert result.news == {"id": "n1"}
    assert result.trend is None
    assert result.publish is True
    assert result.score == 91.5
    assert "score" not in result.model_fields_set
