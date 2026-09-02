from datetime import date, datetime, timezone

from services.trends.models import TrendSignal


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
        if isinstance(published_at, datetime):
            item_date = published_at.astimezone(timezone.utc).date()
        else:
            item_date = published_at
        # NewsService normally supplies the current batch, so an omitted timestamp
        # is treated as fresh. Callers can provide a date for historical analysis.
        freshness_score = (
            20
            if item_date is None or item_date >= datetime.now(timezone.utc).date()
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
