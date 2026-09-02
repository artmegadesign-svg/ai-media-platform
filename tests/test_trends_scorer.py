from datetime import date, timedelta

from services.trends import TrendScorer, TrendSignal


def test_multiple_fresh_authoritative_sources_score_higher():
    scorer = TrendScorer()
    high = TrendSignal(
        keyword="OpenAI", mentions=3, source_count=3, category="model_release"
    )
    low = TrendSignal(
        keyword="commentary", mentions=1, source_count=1, category="opinion"
    )
    assert scorer.score(high).growth_score == 100
    assert scorer.score(low, date.today() - timedelta(days=1)).growth_score < 20
