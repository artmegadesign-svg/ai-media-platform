"""Reproduce scoring boundaries; fixtures are synthetic, not production evidence."""

from datetime import timedelta

import pytest

from services.editorial.evaluator import EditorialEvaluator, select_trend
from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.collectors.openai import OpenAINewsCollector
from services.news.models import NewsItem
from services.news.normalizer import NewsNormalizer
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


@pytest.mark.parametrize(("title", "age", "url", "category", "score", "approved"), [
    ("OpenAI releases GPT-5", 0, "https://openai.com/event", "model_release", 74, True),
    ("OpenAI introduces a new AI API", 0, "https://openai.com/event", "tool_release", 64, False),
    ("OpenAI launches an AI tool", 0, "https://openai.com/event", "tool_release", 64, False),
    ("OpenAI publishes AI research with benchmark results", 0,
     "https://openai.com/event", "research", 67, False),
    ("OpenAI celebrates customer success with AI", 0,
     "https://openai.com/event", "general", 52, False),
    ("OpenAI releases a travel report", 0, "https://openai.com/event", "general", 36, False),
    ("OpenAI releases GPT-5", 30, "https://openai.com/event", "model_release", 68, False),
    ("OpenAI may release GPT-5 next month", 0,
     "https://openai.com/event", "general", 52, False),
    ("OpenAI releases GPT-5", 0,
     "https://openai.com.evil.example/event", "model_release", 54, False),
    ("An update about GPT-5", 0, "https://openai.com/event", "general", 49, False),
])
def test_current_single_source_scoring_boundaries(
    title, age, url, category, score, approved, fixed_editorial_now,
):
    now = fixed_editorial_now
    item = NewsItem(
        source="OpenAI", title=title, url=url, published_at=now - timedelta(days=age),
    )
    news_service = NewsService(scorer=NewsScorer(now))
    news = news_service.process([item])
    trends = TrendService().analyze(news)
    evaluation = EditorialEvaluator().evaluate(news[0], select_trend(news[0], trends))
    decision = EditorialService().evaluate(news, trends)[0]

    assert evaluation.category == category
    assert evaluation.novelty == 0
    assert decision.score == score
    assert decision.publish is approved
    results = IntelligenceService(news_service, TrendService(), EditorialService()).analyze([item])
    assert bool(results) is approved


def test_loaded_release_page_facts_do_not_reach_editorial(fixed_editorial_now):
    xml = f"""<rss><channel><item>
    <title>An update about GPT-5</title><link>https://openai.com/event</link>
    <description>Learn more.</description>
    <pubDate>{fixed_editorial_now.isoformat()}</pubDate>
    </item></channel></rss>"""
    page = "<html><body>OpenAI releases GPT-5. Available today in the API.</body></html>"
    requests = []

    def fetch(url):
        requests.append(url)
        return xml if url == OpenAINewsCollector.feed_url else page

    item = OpenAINewsCollector(fetcher=fetch).collect()[0]
    assert requests == [OpenAINewsCollector.feed_url, "https://openai.com/event"]
    assert item.content == "Learn more."
    assert item.image_discovery_status == "complete"
    normalized = NewsNormalizer().normalize([item])[0]
    evaluation = EditorialEvaluator().evaluate(normalized)
    assert evaluation.category == "general"
    assert evaluation.impact == 0


@pytest.mark.parametrize("category", ["general", "other"])
def test_default_general_category_blocks_reclassification(category):
    item = NewsItem(
        source="OpenAI", title="OpenAI releases GPT-5",
        url="https://openai.com/event", category=category,
    )
    evaluation = EditorialEvaluator().evaluate(NewsNormalizer().normalize([item])[0])
    assert evaluation.category == ("general" if category == "general" else "model_release")
    assert evaluation.impact == (0 if category == "general" else 80)
