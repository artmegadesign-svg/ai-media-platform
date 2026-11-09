from datetime import timedelta, timezone

import pytest

from services.trends import TrendScorer, TrendSignal


def test_multiple_fresh_authoritative_sources_score_higher(fixed_editorial_now):
    scorer = TrendScorer()
    high = TrendSignal(
        keyword="OpenAI", mentions=3, source_count=3, category="model_release"
    )
    low = TrendSignal(
        keyword="commentary", mentions=1, source_count=1, category="opinion"
    )
    today = fixed_editorial_now.date()
    assert scorer.score(high, today).growth_score == 100
    assert scorer.score(low, today - timedelta(days=1)).growth_score < 20


@pytest.mark.parametrize("age", [None, 1, -1])
def test_unknown_old_and_future_dates_receive_no_freshness_bonus(age, fixed_editorial_now):
    signal = TrendSignal(
        keyword="OpenAI", mentions=3, source_count=3, category="model_release"
    )
    published = None if age is None else fixed_editorial_now - timedelta(days=age)

    assert TrendScorer().score(signal, published).growth_score == 80


def test_naive_dates_are_utc_and_future_time_is_not_fresh(fixed_editorial_now):
    now = fixed_editorial_now
    signal = TrendSignal(
        keyword="OpenAI", mentions=3, source_count=3, category="model_release",
        latest_published_at=now.replace(tzinfo=None),
    )
    assert TrendScorer().score(signal).growth_score == 100
    assert TrendScorer().score(signal, now + timedelta(seconds=30)).growth_score == 80


def test_publication_before_midnight_uses_utc_day_even_with_local_offset(fixed_editorial_now):
    signal = TrendSignal(
        keyword="OpenAI", mentions=3, source_count=3, category="model_release"
    )
    midnight = fixed_editorial_now.replace(hour=0, minute=0, second=0)
    published = (midnight - timedelta(seconds=1)).astimezone(timezone(timedelta(hours=3)))

    assert TrendScorer().score(signal, published).growth_score == 80
