from dataclasses import dataclass

import pytest

from services.editorial.evaluator import EditorialEvaluator
from services.news.models import NewsItem as StandardNewsItem
from services.trends.models import TrendSignal


@dataclass
class NewsItem:
    id: str
    category: str
    impact: float
    authority: float
    audience: float
    novelty: float


def test_evaluator_extracts_news_and_trend_factors():
    news = NewsItem("n-1", "research", 80, 90, 70, 60)

    result = EditorialEvaluator().evaluate(news, {"score": 75})

    assert result.news_id == "n-1"
    assert result.category == "research"
    assert result.trend_score == 75
    assert (result.authority, result.impact, result.audience, result.novelty) == (
        90,
        80,
        70,
        60,
    )


def test_evaluator_clamps_factors_to_score_scale():
    news = {"id": 1, "impact": 120, "authority": -5, "audience": 50, "novelty": 10}
    result = EditorialEvaluator().evaluate(news, {"growth": 200})

    assert result.impact == 100
    assert result.authority == 0
    assert result.trend_score == 100


def _standard_news(**overrides):
    return StandardNewsItem(**{
        "source": "OpenAI", "title": "OpenAI releases GPT-5",
        "url": "https://openai.com/news/gpt-5", **overrides,
    })


def test_standard_news_factors_use_evidence_and_real_growth_score():
    news = _standard_news()
    trend = TrendSignal(
        keyword="OpenAI", mentions=1, source_count=1,
        category="model_release", growth_score=73.33, news_ids=[news.id],
    )

    result = EditorialEvaluator().evaluate(news, trend)

    assert result.category == "model_release"
    assert result.trend_score == 73.33
    assert (result.authority, result.impact, result.audience, result.novelty) == (100, 80, 80, 0)


@pytest.mark.parametrize("url", [
    "https://openai.com.example.org/story",
    "https://notopenai.com/story",
    "https://openai.com@evil.example/story",
    "http://openai.com/story",
    "https://[invalid/story",
])
def test_source_label_cannot_spoof_official_authority(url):
    result = EditorialEvaluator().evaluate(_standard_news(url=url))

    assert result.authority == 0


def test_brand_alone_does_not_establish_ai_relevance_or_impact():
    result = EditorialEvaluator().evaluate(_standard_news(
        source="Google", title="Google releases a travel report",
        url="https://blog.google/travel",
    ))

    assert result.authority == 100
    assert (result.impact, result.audience, result.novelty) == (0, 0, 0)


@pytest.mark.parametrize("value", [0, 25])
def test_explicit_factors_override_all_fallbacks_including_zero(value):
    news = _standard_news().model_dump() | {
        "authority": value, "impact": value, "audience": value, "novelty": value,
    }
    result = EditorialEvaluator().evaluate(news)

    assert (result.authority, result.impact, result.audience, result.novelty) == (value,) * 4


def test_none_uses_alias_and_nested_explicit_zero_is_preserved():
    news = {
        "id": "n-1", "source": {"authority": 0}, "authority": None,
        "impact": None, "impact_score": 25,
    }
    result = EditorialEvaluator().evaluate(news, {"growth_score": 0, "score": 100})

    assert result.authority == 0
    assert result.impact == 25
    assert result.trend_score == 0


def test_missing_evidence_does_not_receive_high_defaults_or_reuse_news_score():
    result = EditorialEvaluator().evaluate({"id": "n-1", "score": 100})

    assert (result.authority, result.impact, result.audience, result.novelty) == (0,) * 4
    assert result.trend_score == 0


@pytest.mark.parametrize(("title", "category", "impact", "audience"), [
    ("OpenAI releases GPT-5", "model_release", 80, 80),
    ("OpenAI launches an AI tool powered by GPT-5", "tool_release", 60, 80),
    ("OpenAI releases a research paper about GPT-5", "research", 60, 80),
    ("OpenAI releases a financial report", "general", 0, 0),
    ("OpenAI releases a travel report mentioning GPT-5", "general", 0, 80),
    ("OpenAI plans to release GPT-5", "general", 0, 80),
])
def test_event_evidence_controls_fallback_impact(title, category, impact, audience):
    result = EditorialEvaluator().evaluate(_standard_news(title=title))

    assert result.category == category
    assert result.impact == impact
    assert result.audience == audience
    assert result.novelty == 0


def test_explicit_model_category_alone_cannot_create_missing_impact():
    news = _standard_news(title="An update about GPT-5", category="model_release")

    result = EditorialEvaluator().evaluate(news)

    assert result.category == "model_release"
    assert result.impact == 0


@pytest.mark.parametrize(("title", "category", "impact"), [
    ("OpenAI releases GPT-5.1 research paper", "research", 60),
    ("OpenAI releases GPT-4.5 research paper", "research", 60),
    ("OpenAI releases GPT-5.1", "model_release", 80),
    ("OpenAI releases GPT-4.5", "model_release", 80),
    ("OpenAI releases GPT-5 SDK", "tool_release", 60),
    ("OpenAI releases GPT-5 API", "tool_release", 60),
    ("OpenAI releases GPT-5.1 SDK", "tool_release", 60),
    ("Google launches Gemini SDK", "tool_release", 60),
    ("Google launches Gemini 2.5 SDK", "tool_release", 60),
    ("Anthropic releases Claude Code", "tool_release", 60),
    ("OpenAI releases an AI application powered by GPT-5", "tool_release", 60),
    ("OpenAI releases GPT-5.1 through its API", "model_release", 80),
])
def test_corrected_event_types_produce_the_existing_impact_values(title, category, impact):
    result = EditorialEvaluator().evaluate(_standard_news(title=title))

    assert result.category == category
    assert result.impact == impact
