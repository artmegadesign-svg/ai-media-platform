"""Synthetic event evidence, never represented as saved production articles."""

from datetime import timedelta
from unittest.mock import Mock

import pytest

from services.editorial.evaluator import EditorialEvaluator, select_trend
from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.normalizer import event_category
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


CASES = [
    ("model", "OpenAI releases GPT-5", "GPT-5 is available today. The model supports 12 languages.", "model_release", True),
    ("api", "Google introduces Nova AI API", "Nova AI API is available today to developers. The API supports streaming and structured outputs.", "api_release", True),
    ("tool", "Google launches Atlas AI tool", "Atlas AI tool is available today. The tool enables local inference and supports 12 languages.", "tool_release", True),
    ("update", "Google updates Gemini AI search", "Gemini AI search is available today. It supports structured outputs and enables tool calling.", "product_update", True),
    ("research", "Google publishes AI research paper on Nova", "Nova researchers published a paper on AI inference. The paper is available today with a measured 18% reduction in latency against the baseline.", "research", True),
    ("education", "Google launches AI education program", "The program includes research lectures. Google publishes AI research with measured 18% gains and a paper is available today.", "education", False),
    ("corporate", "Google AI customer success story", "Nova AI API is available today. The API supports streaming and structured outputs.", "corporate", False),
    ("rumor", "Google may release Gemini AI model", "Gemini could be released next month.", "rumor", False),
    ("irrelevant", "Google releases a travel report", "The annual trip report mentions Gemini in a footnote.", "general", False),
    ("weak", "Google introduces Nova AI API", "An overview of Nova AI API.", "api_release", False),
]


def item(now, name, title, content, *, days=0, **overrides):
    return NewsItem(**{
        "id": name, "title": title, "content": content,
        "source": "OpenAI" if title.startswith("OpenAI") else "Google",
        "url": f"https://{'openai.com' if title.startswith('OpenAI') else 'blog.google'}/news/{name}",
        "published_at": now - timedelta(days=days), **overrides,
    })


def evaluate(news, now, *, limit=10):
    collector = Mock()
    collector.collect.side_effect = AssertionError("Pipeline must not fetch a source")
    ns = NewsService(collectors=[collector], scorer=NewsScorer(now), limit=limit)
    normalized = ns.process(news)
    ts = TrendService()
    trends = ts.analyze(normalized)
    decisions = EditorialService().evaluate(normalized, trends)
    approved = IntelligenceService(ns, ts, EditorialService()).analyze(news, limit=None)
    collector.collect.assert_not_called()
    return normalized, trends, decisions, approved


@pytest.mark.parametrize("name,title,content,category,allowed", CASES, ids=[c[0] for c in CASES])
def test_single_source_event_policy(name, title, content, category, allowed, fixed_editorial_now):
    now = fixed_editorial_now
    normalized, trends, decisions, approved = evaluate([item(now, name, title, content)], now)
    assert normalized[0].category == category
    factors = EditorialEvaluator().evaluate(normalized[0], select_trend(normalized[0], trends))
    assert factors.novelty == 0
    assert decisions[0].publish is allowed
    assert bool(approved) is allowed
    if allowed:
        assert factors.impact == 80
        assert decisions[0].score >= 70
    else:
        assert decisions[0].score < 70 or factors.blocked_reason


@pytest.mark.parametrize("days", [1, 7, 8, 30, 60, -1])
def test_event_date_has_rolling_seven_day_window(days, fixed_editorial_now):
    now = fixed_editorial_now
    name, title, content, _, _ = CASES[1]
    _, _, decisions, approved = evaluate([item(now, name, title, content, days=days)], now)
    assert decisions[0].publish is (0 <= days <= 7)
    assert bool(approved) is (0 <= days <= 7)
    if not 0 <= days <= 7:
        assert "publication date" in decisions[0].reason


@pytest.mark.parametrize("url", [
    "https://blog.google.evil.example/news", "https://evil.example/news",
    "https://blog.google@evil.example/news", "http://blog.google/news",
    "https://blog.google:444/news", "https://unconfigured.blog.google/news",
])
def test_source_label_cannot_verify_a_forged_or_unapproved_url(url, fixed_editorial_now):
    now = fixed_editorial_now
    name, title, content, _, _ = CASES[1]
    _, _, decisions, approved = evaluate([item(now, name, title, content, url=url)], now)
    assert not approved
    assert not decisions[0].publish
    assert "source URL" in decisions[0].reason


def test_mixed_batch_cannot_promote_old_or_different_events(fixed_editorial_now):
    now = fixed_editorial_now
    current = [item(now, *case[:3]) for case in CASES]
    stale = item(now, "old-model", "Google releases Gemini 2", "Gemini 2 is available today.", days=60)
    no_date = item(now, "no-date", "Anthropic launches an AI language model", "A model announcement.",
                   source="Anthropic", url="https://anthropic.com/no-date", published_at=None)
    first, _, _, alone = evaluate([current[1]], now)
    ns, trends, decisions, approved = evaluate([stale, no_date, *current], now, limit=50)
    by_id = {decision.news_id: decision for decision in decisions}
    assert {result.news.id for result in approved} == {c[0] for c in CASES if c[4]}
    assert by_id["api"].score == alone[0].score
    assert not by_id["old-model"].publish and not by_id["no-date"].publish
    api = next(news for news in ns if news.id == first[0].id)
    factors = EditorialEvaluator().evaluate(api, select_trend(api, trends))
    # The brand cluster contains a model release, but API cannot inherit its category.
    assert factors.trend_score == 53.33
    # Even explicitly supplied high factors cannot bypass gates on real news records.
    forged = stale.model_dump() | {"impact": 100, "novelty": 100, "authority": 100, "audience": 100}
    rejected = EditorialService().evaluate([forged], trends)[0]
    assert not rejected.publish and rejected.priority == "low"


def test_stale_models_do_not_crowd_current_api_out_of_news_top_ten(fixed_editorial_now):
    now = fixed_editorial_now
    old = [item(now, f"old-{i}", f"Google releases an AI model {chr(65 + i) * 40}", "An old release.", days=40)
           for i in range(20)]
    current = item(now, *CASES[1][:3])
    normalized, _, _, approved = evaluate([*old, current], now, limit=10)
    assert len(normalized) == 10  # Distinct old titles survive the unchanged deduplication.
    assert normalized[0].id == "api"
    assert [result.news.id for result in approved] == ["api"]


@pytest.mark.parametrize("title,content,category", [
    ("Google introduces Gemini Decisions API", "Gemini Decisions API is available today.", "api_release"),
    ("Google AI Updates October 2026", "We discuss research from last month.", "general"),
    ("Google Search / Gemini 4 Hydrogen", "Learn more about search.", "general"),
    ("Google Labs Tabletop", "A company update.", "general"),
    ("Google introduces Aurora AI API", "Aurora AI API is available today.", "api_release"),
    ("Google launches AI learning course", "The author conducts research into Gemini.", "education"),
    ("Google releases Gemini 4", "The author previously published AI research.", "model_release"),
    ("Google launches AI tool", "Google publishes an unrelated research paper.", "tool_release"),
    ("Google releases Gemini 4", "Gemini 4 may launch next month.", "rumor"),
])
def test_headline_event_and_limited_lead_control_classification(title, content, category):
    # Production-inspired names with invented content are diagnostic fixtures only.
    assert event_category(title, content) == category


def test_unrelated_or_late_facts_cannot_increase_an_api_impact(fixed_editorial_now):
    now = fixed_editorial_now
    title = CASES[1][1]
    for content in [
        "Other AI API is available today. The API supports streaming and structured outputs.",
        "Nova AI API has a new announcement. Another tool is available today and supports streaming.",
        "Nova AI API overview. Background follows. Author biography follows. Nova AI API is available today and supports streaming.",
    ]:
        _, _, decisions, approved = evaluate([item(now, "api", title, content)], now)
        assert decisions[0].score < 70
        assert not approved


@pytest.mark.parametrize("title,content,category", [
    ("Google releases Gemini 4 based on AI research", "", "model_release"),
    ("Google launches an AI tool based on research", "", "tool_release"),
    ("Google launches Gemini 4 in search", "", "product_update"),
    ("Google announces Nova AI API", "", "api_release"),
    ("Nova AI API is now available", "", "api_release"),
    ("Google AI research roundup", "Google published a paper on AI.", "general"),
    ("Google releases Gemini 4", "Originally released last year, Gemini 4 supports 12 languages.", "general"),
])
def test_event_object_is_separated_from_background_and_retrospectives(title, content, category):
    assert event_category(title, content) == category


def test_model_announcement_without_available_capabilities_is_not_auto_published(fixed_editorial_now):
    now = fixed_editorial_now
    _, _, decisions, approved = evaluate([
        item(now, "announcement", "Google announces Gemini 4", "Gemini 4 has been announced.")
    ], now)
    assert decisions[0].score < 70
    assert not approved


def test_research_in_biography_is_not_a_primary_publication_event():
    assert event_category(
        "Google AI updates", "The author previously published AI research. The author biography lists papers."
    ) == "general"


def test_future_capability_is_not_evidence_of_current_significance(fixed_editorial_now):
    now = fixed_editorial_now
    _, _, decisions, approved = evaluate([item(
        now, "api", CASES[1][1],
        "Nova AI API is available today. The API will support streaming and structured outputs next year.",
    )], now)
    assert decisions[0].score < 70
    assert not approved


@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2611.12345", "https://doi.org/10.1234/example"])
def test_research_artifact_url_survives_sentence_parsing(url, fixed_editorial_now):
    now = fixed_editorial_now
    research = item(
        now, "research", "Google publishes AI research paper on Nova",
        f"Nova researchers published an AI paper at {url}. The paper improves latency by 18% against the baseline.",
    )
    _, _, decisions, approved = evaluate([research], now)
    assert decisions[0].score >= 70 and approved
