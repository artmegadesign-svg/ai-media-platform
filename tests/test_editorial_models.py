import pytest

from services.editorial.models import EditorialDecision


def test_editorial_decision_rejects_score_outside_scale():
    with pytest.raises(ValueError, match="between 0 and 100"):
        EditorialDecision(1, False, "low", "news", "invalid", 101)


def test_editorial_decision_accepts_scale_boundaries():
    assert EditorialDecision(1, False, "low", "news", "zero", 0).score == 0
    assert EditorialDecision(2, True, "high", "news", "full", 100).score == 100
