"""Weighted scoring policy for editorial evaluations."""

from services.editorial.models import EditorialEvaluation


class EditorialScorer:
    """Calculate the specified weighted score on a 0-100 scale."""

    def score(self, evaluation: EditorialEvaluation) -> float:
        score = (
            evaluation.trend_score * 0.30
            + evaluation.authority * 0.20
            + evaluation.impact * 0.20
            + evaluation.audience * 0.20
            + evaluation.novelty * 0.10
        )
        return round(min(100.0, max(0.0, score)), 2)
