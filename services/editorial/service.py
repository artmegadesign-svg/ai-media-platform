"""Orchestration for independent editorial recommendations."""

from collections.abc import Iterable

from services.editorial.evaluator import EditorialEvaluator, select_trend
from services.editorial.models import EditorialDecision
from services.editorial.scorer import EditorialScorer


class EditorialService:
    """Evaluate news against trend signals without changing upstream layers."""

    _formats = {
        "model_release": "breaking",
        "research": "analysis",
        "funding": "news",
        "tool_release": "guide",
    }

    def __init__(
        self,
        evaluator: EditorialEvaluator | None = None,
        scorer: EditorialScorer | None = None,
    ) -> None:
        self.evaluator = evaluator or EditorialEvaluator()
        self.scorer = scorer or EditorialScorer()

    def evaluate(
        self, news: Iterable[object], trends: Iterable[object]
    ) -> list[EditorialDecision]:
        trend_items = list(trends)
        decisions = [self._decision(item, trend_items) for item in news]
        return sorted(decisions, key=lambda decision: decision.score, reverse=True)

    def _decision(
        self, news: object, trends: list[object]
    ) -> EditorialDecision:
        trend = self._matching_trend(news, trends)
        evaluation = self.evaluator.evaluate(news, trend)
        score = self.scorer.score(evaluation)
        publish = score >= 70
        priority = "high" if score >= 85 else "normal" if publish else "low"
        reason = (
            f"Editorial score {score:.2f} meets publication threshold"
            if publish
            else f"Editorial score {score:.2f} is below publication threshold"
        )
        return EditorialDecision(
            news_id=evaluation.news_id,
            publish=publish,
            priority=priority,
            format=self._formats.get(evaluation.category, "news"),
            reason=reason,
            score=score,
        )

    @staticmethod
    def _matching_trend(news: object, trends: list[object]) -> object | None:
        return select_trend(news, trends)
