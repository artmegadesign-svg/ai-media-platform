from datetime import timedelta

import pytest

from services.editorial.evaluator import EditorialEvaluator
from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.collectors.openai import OpenAINewsCollector
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


class EditorialNewsItem(NewsItem):
    authority: float
    impact: float
    audience: float
    novelty: float


def test_real_intelligence_layers_process_supplied_news_without_collecting(fixed_editorial_now):
    now = fixed_editorial_now
    service = IntelligenceService(
        NewsService(scorer=NewsScorer(now)),
        TrendService(),
        EditorialService(),
    )
    item = EditorialNewsItem(
        source="OpenAI",
        title="  OpenAI   releases GPT-5 ",
        url="https://OPENAI.com/news/gpt-5/?utm_source=test",
        published_at=now,
        category="model_release",
        authority=100,
        impact=100,
        audience=100,
        novelty=100,
    )

    results = service.analyze([item])

    assert len(results) == 1
    assert results[0].news.title == "OpenAI releases GPT-5"
    assert results[0].news.url == "https://openai.com/news/gpt-5"
    assert results[0].news.score == 70
    assert results[0].publish is True


def test_standard_rss_news_passes_real_pipeline_and_returns_the_used_trend(fixed_editorial_now):
    now = fixed_editorial_now
    xml = f"""<rss><channel><item>
    <title>OpenAI releases GPT-5</title>
    <link>https://openai.com/news/gpt-5/?utm_source=test</link>
    <pubDate>{now.isoformat()}</pubDate>
    </item></channel></rss>"""
    collector = OpenAINewsCollector(fetcher=lambda _: xml)
    news_service = NewsService(collectors=[collector], scorer=NewsScorer(now))
    service = IntelligenceService(news_service, TrendService(), EditorialService())
    items = collector.collect()

    results = service.analyze(items)

    assert type(items[0]) is NewsItem
    assert items[0].category == "other"
    assert len(results) == 1
    result = results[0]
    assert result.news.category == "model_release"
    assert result.news.url == "https://openai.com/news/gpt-5"
    assert result.trend is not None
    assert result.news.id in result.trend.news_ids
    assert result.trend.keyword == "OpenAI"
    assert result.trend.growth_score == 73.33
    assert result.editorial.score == 74
    assert result.editorial.publish is True
    assert result.editorial.priority == "normal"
    evaluation = EditorialEvaluator().evaluate(result.news, result.trend)
    assert evaluation.novelty == 0


@pytest.mark.parametrize(("source", "title", "url", "age"), [
    ("Google", "Google releases travel report", "https://blog.google/travel", 0),
    ("Unknown", "OpenAI releases GPT-5", "https://example.com/release", 0),
    ("OpenAI", "OpenAI releases GPT-5", "https://openai.com.evil.example/release", 0),
    ("OpenAI", "OpenAI releases GPT-5", "https://openai.com/release", None),
    ("OpenAI", "OpenAI releases GPT-5", "https://openai.com/release", 30),
    ("OpenAI", "OpenAI releases GPT-5", "https://openai.com/release", -1),
    ("OpenAI", "OpenAI opinion on GPT-5", "https://openai.com/opinion", 0),
    ("OpenAI", "OpenAI releases financial report", "https://openai.com/report", 0),
    ("OpenAI", "OpenAI releases a travel report about GPT-5", "https://openai.com/travel", 0),
    ("OpenAI", "OpenAI plans to release GPT-5", "https://openai.com/plans", 0),
])
def test_standard_unsuitable_news_is_rejected(source, title, url, age, fixed_editorial_now):
    now = fixed_editorial_now
    item = NewsItem(
        source=source, title=title, url=url,
        published_at=None if age is None else now - timedelta(days=age),
    )

    service = IntelligenceService(
        NewsService(scorer=NewsScorer(now)), TrendService(), EditorialService()
    )

    assert service.analyze([item]) == []


def test_shared_category_does_not_attach_other_story_trend_to_intelligence_result():
    first = EditorialNewsItem(
        id="first", source="OpenAI", title="OpenAI releases GPT-5",
        url="https://openai.com/first", category="model_release",
        authority=100, impact=100, audience=100, novelty=100,
    )
    second = first.model_copy(update={
        "id": "second", "source": "Google", "title": "Google launches Gemini",
        "url": "https://blog.google/second",
    })

    results = IntelligenceService(NewsService(), TrendService(), EditorialService()).analyze(
        [first, second]
    )

    assert len(results) == 2
    for result in results:
        assert result.trend.news_ids == [result.news.id]
        assert EditorialService().evaluate([result.news], [result.trend])[0] == result.editorial
