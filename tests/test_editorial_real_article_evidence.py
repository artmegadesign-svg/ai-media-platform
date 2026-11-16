"""Verbatim observed prefixes and separately labelled synthetic continuations."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.editorial.evaluator import EditorialEvaluator, select_trend
from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.normalizer import evidence_sentences, event_category
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


EXCERPTS = json.loads((Path(__file__).parent / 'fixtures/editorial/observed_google_excerpts.json').read_text())
TITLE = 'Acme AI Search gets a major upgrade with the Orion AI model'
API_TITLE = 'Google introduces the Acme Decisions AI API'
# Invented test facts, not quotations or observations from either real page.
API_FACTS = 'Acme Decisions AI API is available today. The API supports streaming and structured outputs.'
UPDATE_FACTS = 'Acme AI Search is bringing new AI intelligence to users with the Orion AI model. This upgrade is now available to everyone. It supports structured outputs and tool calling.'
META = ['Nov 12, 2026', 'Robby Stein', 'VP of Product, Google Search']


def replay(title, content, now, *, url='https://blog.google/test', published=None):
    original = NewsItem(source='Google', title=title, content=content, url=url,
                        published_at=published or now - timedelta(days=2))
    collector = Mock()
    collector.collect.side_effect = AssertionError('No HTTP collection in replay')
    news_service = NewsService(collectors=[collector], scorer=NewsScorer(now))
    news = news_service.process([original])
    trend_service = TrendService()
    trends = trend_service.analyze(news)
    evaluation = EditorialEvaluator().evaluate(news[0], select_trend(news[0], trends))
    decision = EditorialService().evaluate(news, trends)[0]
    results = IntelligenceService(news_service, trend_service, EditorialService()).analyze([original])
    collector.collect.assert_not_called()
    assert original.content == content  # No mutation or deletion of source evidence.
    assert evaluation.novelty == 0
    return news[0], evaluation, decision, results


@pytest.mark.parametrize('key,category,score', [('api', 'api_release', 63.33), ('search', 'product_update', 63.33)])
def test_exact_observed_prefixes_do_not_invent_availability(key, category, score, monkeypatch):
    now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    monkeypatch.setattr('services.trends.scorer._utc_now', lambda: now)
    example = EXCERPTS[key]
    text = '\n\n'.join(example['blocks'])
    news, factors, decision, results = replay(example['diagnostic_title'], text, now,
                                             url=example['url'], published=datetime.fromisoformat(example['published_at']))
    assert factors.category == category
    assert factors.impact == 60 and decision.score == score
    assert not decision.publish and not results
    for block in example['blocks']:
        assert block in news.content
    selected = evidence_sentences(news.content)
    assert example['blocks'][0] not in selected
    assert len(selected) == 2


@pytest.mark.parametrize('metadata', [['Nov 12, 2026'], META, ['Min Choi', 'Product Manager, Google DeepMind']])
def test_confirmed_api_after_metadata_uses_facts_and_preserves_content(metadata, fixed_editorial_now):
    content = '\n'.join([*metadata, API_FACTS])
    news, factors, decision, results = replay(API_TITLE, content, fixed_editorial_now)
    assert factors.impact == 80 and decision.score == 71.33 and results
    assert all(block in news.content for block in metadata)
    assert evidence_sentences(news.content) == evidence_sentences(API_FACTS)


def test_metadata_between_facts_does_not_use_the_fact_budget(fixed_editorial_now):
    first, second = API_FACTS.split('. ')
    text = '\n'.join([first + '.', *META, second])
    _, factors, decision, results = replay(API_TITLE, text, fixed_editorial_now)
    assert factors.impact == 80 and decision.publish and results


def test_general_product_upgrade_after_byline_is_confirmed_without_a_model_release(fixed_editorial_now):
    text = '\n'.join([*META, UPDATE_FACTS])
    _, factors, decision, results = replay(TITLE, text, fixed_editorial_now)
    assert factors.category == 'product_update' and factors.impact == 80
    assert decision.score == 71.33 and results


@pytest.mark.parametrize('title,text,category', [
    ('Acme releases a new AI model', '', 'model_release'),
    ('Acme brings the Orion AI model into its browser', '', 'product_update'),
    ('Acme AI browser gets a major upgrade', '', 'product_update'),
    ('Acme AI browser receives a significant upgrade', '', 'product_update'),
    ('Acme AI browser may get a major upgrade', '', 'rumor'),
])
def test_model_release_and_product_integration_are_different_events(title, text, category):
    assert event_category(title, text) == category


@pytest.mark.parametrize('content', [
    '\n'.join(META),
    '\n'.join([*META, 'Acme Decisions AI API overview.']),
    '\n'.join([*META, 'Acme Decisions AI API is available today. The API will support streaming next year.']),
    '\n'.join([*META, 'Acme Decisions AI API overview. Author biography: Ada released another AI API. The API is available today and supports streaming.']),
    '\n'.join([*META, 'Acme Decisions AI API overview. Other AI API is available today. The API supports streaming.']),
    '\n'.join([*META, 'Acme Decisions AI API overview. Acme Different AI API is available today. The API supports streaming.']),
])
def test_metadata_does_not_justify_weak_future_biographical_or_unrelated_evidence(content, fixed_editorial_now):
    _, factors, decision, results = replay(API_TITLE, content, fixed_editorial_now)
    assert factors.impact == 60 and decision.score < 70 and not results


@pytest.mark.parametrize('title', ['Acme AI customer success story', 'Acme may launch an AI tool', 'Acme AI education course'])
def test_unwanted_primary_event_still_fails_after_metadata(title, fixed_editorial_now):
    _, _, decision, results = replay(title, '\n'.join([*META, API_FACTS]), fixed_editorial_now)
    assert not decision.publish and not results


@pytest.mark.parametrize('days,allowed', [(7, True), (8, False), (40, False)])
def test_seven_day_gate_remains_independent_of_metadata_and_evidence(days, allowed, fixed_editorial_now):
    _, factors, decision, results = replay(API_TITLE, '\n'.join([*META, API_FACTS]), fixed_editorial_now,
                                           published=fixed_editorial_now - timedelta(days=days))
    assert factors.impact == 80
    assert decision.publish is allowed and bool(results) is allowed


def test_fixed_raw_scan_budget_is_not_extended_by_metadata_or_text_length(fixed_editorial_now):
    for prefix in ['\n'.join(['Nov 12, 2026'] * 16), 'Unrelated preamble ' * 300]:
        _, factors, decision, results = replay(API_TITLE, prefix + '\n' + API_FACTS, fixed_editorial_now)
        assert factors.impact == 60 and not decision.publish and not results


def test_dates_names_and_roles_inside_event_sentences_remain_facts(fixed_editorial_now):
    text = ('Acme Decisions AI API is available today, Nov 12, 2026, as announced by Product Manager Min Choi. '
            'The API supports streaming and structured outputs.')
    news, factors, decision, results = replay(API_TITLE, text, fixed_editorial_now)
    assert news.content == text and factors.impact == 80 and decision.publish and results


@pytest.mark.parametrize('key', ['api', 'search'])
def test_observed_prefix_with_explicitly_synthetic_current_facts_can_pass(key, monkeypatch):
    now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    monkeypatch.setattr('services.trends.scorer._utc_now', lambda: now)
    example = EXCERPTS[key]
    # Invented continuations test evidence selection only. They are NOT from the URLs.
    supplement = ('The Gemini Decisions API is available today.' if key == 'api' else
                  'This upgrade is now available to everyone. It supports structured outputs and tool calling.')
    text = '\n'.join([*example['blocks'], supplement])
    _, factors, decision, results = replay(example['diagnostic_title'], text, now,
                                           url=example['url'], published=datetime.fromisoformat(example['published_at']))
    assert factors.impact == 80 and decision.score == 71.33 and results
