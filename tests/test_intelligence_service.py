from dataclasses import dataclass

from services.editorial.models import EditorialDecision
from services.intelligence.service import IntelligenceService


@dataclass(frozen=True)
class NewsItem:
    id: str


@dataclass(frozen=True)
class TrendSignal:
    news_id: str
    score: float


def _decision(news_id: str, publish: bool, score: float) -> EditorialDecision:
    return EditorialDecision(news_id, publish, "high", "news", "evaluated", score)


class FakeNewsService:
    def __init__(self, news, calls):
        self.news = news
        self.calls = calls

    def process(self, items):
        self.calls.append(("news", list(items)))
        return self.news


class FakeTrendService:
    def __init__(self, trends, calls):
        self.trends = trends
        self.calls = calls

    def analyze(self, news):
        self.calls.append(("trends", news))
        return self.trends


class FakeEditorialService:
    def __init__(self, decisions, calls):
        self.decisions = decisions
        self.calls = calls

    def evaluate(self, news, trends):
        self.calls.append(("editorial", news, trends))
        return self.decisions


def _service(news, trends, decisions, calls=None):
    calls = [] if calls is None else calls
    return IntelligenceService(
        FakeNewsService(news, calls),
        FakeTrendService(trends, calls),
        FakeEditorialService(decisions, calls),
    )


def test_pipeline_order_mapping_filter_sort_and_limit():
    calls = []
    news = [NewsItem("low"), NewsItem("top"), NewsItem("middle"), NewsItem("rejected")]
    trends = [TrendSignal("top", 50), TrendSignal("low", 90)]
    decisions = [
        _decision("low", True, 71),
        _decision("rejected", False, 99),
        _decision("middle", True, 80),
        _decision("top", True, 95),
    ]

    results = _service(news, trends, decisions, calls).analyze(["raw"], limit=2)

    assert [call[0] for call in calls] == ["news", "trends", "editorial"]
    assert [result.news.id for result in results] == ["top", "middle"]
    assert results[0].trend == TrendSignal("top", 50)
    assert results[1].trend is None
    assert all(result.publish for result in results)


def test_limit_none_returns_every_approved_result_after_sorting():
    news = [NewsItem("a"), NewsItem("b")]
    decisions = [_decision("a", True, 70), _decision("b", True, 90)]

    results = _service(news, [], decisions).analyze([], limit=None)

    assert [result.news.id for result in results] == ["b", "a"]


def test_empty_news_stops_before_downstream_services():
    calls = []

    assert _service([], [], [], calls).analyze([]) == []
    assert [call[0] for call in calls] == ["news"]


def test_empty_editorial_results_return_empty_shortlist():
    calls = []

    assert _service([NewsItem("a")], [], [], calls).analyze([]) == []
    assert [call[0] for call in calls] == ["news", "trends", "editorial"]


def test_no_approved_news_returns_empty_shortlist():
    result = _service(
        [NewsItem("a")], [], [_decision("a", False, 99)]
    ).analyze([])

    assert result == []
