import pytest
from pydantic import ValidationError

from services.trends import TrendSignal


def test_trend_signal_validates_score_range():
    with pytest.raises(ValidationError):
        TrendSignal(
            keyword="GPT-5",
            mentions=2,
            growth_score=101,
            source_count=2,
            category="model_release",
        )
