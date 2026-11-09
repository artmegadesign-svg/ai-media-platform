from datetime import date, datetime, timezone

from services.trends.models import TrendSignal


def _utc_now() -> datetime:
    """Internal clock seam for deterministic freshness tests."""
    return datetime.now(timezone.utc)


class TrendScorer:
    """Assign a transparent 0-100 trend score."""

    _CATEGORY_SCORES = {
        "model_release": 30,
        "research": 20,
        "general": 10,
        "opinion": 5,
    }
    _AUTHORITIES = ("openai", "anthropic", "google", "meta", "xai")

    def score(
        self, signal: TrendSignal, published_at: date | datetime | None = None
    ) -> TrendSignal:
        source_score = min(signal.source_count, 3) / 3 * 40
        now = _utc_now()
        if published_at is None:
            published_at = signal.latest_published_at
        not_future = True
        if isinstance(published_at, datetime):
            published_at = (
                published_at.replace(tzinfo=timezone.utc)
                if published_at.tzinfo is None else published_at
            )
            item_date = published_at.astimezone(timezone.utc).date()
            not_future = published_at <= now
        else:
            item_date = published_at
        # Missing, historical and future dates are not evidence of freshness.
        freshness_score = (
            20
            if item_date == now.date() and not_future
            else 0
        )
        authority_score = 10 if signal.keyword.casefold() in self._AUTHORITIES else 0
        category_score = self._CATEGORY_SCORES.get(signal.category, 10)
        return signal.model_copy(
            update={
                "growth_score": round(
                    min(
                        100,
                        source_score
                        + freshness_score
                        + authority_score
                        + category_score,
                    ),
                    2,
                )
            }
        )
