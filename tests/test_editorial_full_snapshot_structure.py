"""Short invented examples of structural failures; no production article text."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from services.editorial.evaluator import EditorialEvaluator, select_trend
from services.editorial.service import EditorialService
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


API_TITLE = 'Nebula Choices API: Quick, consistent media scoring'
API_INTRO = 'Introducing Nebula Choices API, powered by the Nebula Choice 2 AI model.'
API_FEATURE = 'Evaluate 20 questions across text, images and audio.'
META = 'Nov 11, 2026\nJules Barker\nPrincipal Scientist, Horizon Labs'
UPDATE_TITLE = 'Orbit Search gets a major upgrade with the Cosmos AI model'
UPDATE_INTRO = 'Orbit Search is bringing AI intelligence to users with the Cosmos AI model.'
UPDATE_FEATURE = 'With enhanced tool calling, Search gives more relevant answers.'


@pytest.fixture
def clock(monkeypatch):
    now = datetime(2026, 11, 16, 10, 25, 19, tzinfo=timezone.utc)
    monkeypatch.setattr('services.trends.scorer._utc_now', lambda: now)
    return now


def replay(clock, title, text, *, age=2, url='https://blog.google/synthetic'):
    original = NewsItem(source='Google', title=title, content=text, url=url,
                        published_at=clock - timedelta(days=age))
    collector = Mock()
    collector.collect.side_effect = AssertionError('No network in regression replay')
    ns = NewsService(collectors=[collector], scorer=NewsScorer(clock))
    news = ns.process([original])
    ts = TrendService()
    trends = ts.analyze(news)
    evaluation = EditorialEvaluator().evaluate(news[0], select_trend(news[0], trends))
    decision = EditorialService().evaluate(news, trends)[0]
    results = IntelligenceService(ns, ts, EditorialService()).analyze([original])
    collector.collect.assert_not_called()
    assert original.content == text and evaluation.novelty == 0
    return news[0], evaluation, decision, results


@pytest.mark.parametrize('availability', [
    'The Choices API is available through the developer console.',
    'Nebula Choices API is available via the developer console.',
    'The Choices API is available in public preview.',
])
def test_named_api_description_and_shortened_name_do_not_hide_real_evidence(clock, availability):
    text = '\n'.join([META, API_INTRO, API_FEATURE, availability])
    news, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert news.category == 'api_release' and evaluation.impact == 80
    assert decision.publish and results
    assert 'Jules Barker' in news.content  # Metadata is preserved, not repurposed.


@pytest.mark.parametrize('foreign', [
    'Nebula Choice 2 AI model is now available and supports streaming.',
    'Nebula Other API is available through a developer console and supports streaming.',
    'rival Choices API is available through a developer console and supports streaming.',
    'Rival Choices API is available through a developer console and supports streaming.',
    'Nebula AI is available today and supports streaming.',
])
def test_neither_shared_brand_nor_rival_short_name_can_supply_availability(clock, foreign):
    _, evaluation, decision, results = replay(clock, API_TITLE, '\n'.join([META, API_INTRO, API_FEATURE, foreign]))
    assert evaluation.impact == 60 and not decision.publish and not results


@pytest.mark.parametrize('availability', [
    'Cosmos is now available globally in Orbit Search.',
    'Search is now available to all users with the Cosmos AI model.',
])
def test_model_rollout_in_named_service_is_a_product_update(clock, availability):
    _, evaluation, decision, results = replay(clock, UPDATE_TITLE, '\n'.join([META, UPDATE_INTRO, availability, UPDATE_FEATURE]))
    assert evaluation.category == 'product_update' and evaluation.impact == 80
    assert decision.publish and results


@pytest.mark.parametrize('foreign', [
    'Cosmos is available globally through an unrelated developer service.',
    'rival Search is now available to all users and supports tool calling.',
    'Rival Search is now available to all users and supports tool calling.',
])
def test_model_or_different_service_availability_is_not_the_main_product_rollout(clock, foreign):
    _, evaluation, decision, results = replay(clock, UPDATE_TITLE, '\n'.join([META, UPDATE_INTRO, foreign, UPDATE_FEATURE]))
    assert evaluation.impact == 60 and not decision.publish and not results


def test_solution_based_on_known_model_is_not_a_new_model_release(clock):
    text = (
        'Anthropic has announced Claude for billing, an AI solution for office workflows.\n'
        'Moving beyond retrieval, it enables coordinated work.\n'
        'Claude for billing can execute multi-step workflows under human review.\n'
        'Initially available in preview to partner teams, it provides a workflow interface.'
    )
    _, evaluation, decision, results = replay(clock, 'Anthropic launches Claude for billing.', text)
    assert evaluation.category == 'tool_release' and evaluation.impact == 80
    assert decision.publish and results


@pytest.mark.parametrize('availability', [
    'The Choices API is available through a waitlist.',
    'The Choices API is available in preview next month.',
    'The Choices API will be available through the console.',
    'The Choices API is coming in the next few weeks.',
])
def test_waitlist_or_future_access_does_not_establish_current_availability(clock, availability):
    _, evaluation, decision, results = replay(clock, API_TITLE, '\n'.join([META, API_INTRO, API_FEATURE, availability]))
    assert evaluation.impact == 60 and not decision.publish and not results


def test_general_model_preorder_is_not_a_solution_preview(clock):
    text = API_INTRO + '\nThe Choices API is available for pre-order and supports tool calling.'
    _, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert evaluation.impact == 60 and not decision.publish and not results


def test_background_statistics_are_not_the_solutions_measured_benefit(clock):
    text = (
        'Anthropic has announced Claude for billing, an AI solution for office workflows.\n'
        'Office teams lose 28 hours to routine paperwork.\n'
        'Initially available in preview, it provides general assistance.'
    )
    _, evaluation, decision, results = replay(clock, 'Anthropic launches Claude for billing.', text)
    assert evaluation.category == 'tool_release' and evaluation.impact == 60
    assert not decision.publish and not results


@pytest.mark.parametrize('role', ['Principal Scientist', 'Product Director', 'Design & Engineering Lead'])
def test_new_byline_forms_do_not_spend_the_six_fact_budget(clock, role):
    text = '\n'.join(['Taylor Moore', role + ', Horizon Labs', API_INTRO, API_FEATURE,
                      'The Choices API is available through a developer console.'])
    _, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert evaluation.impact == 80 and decision.publish and results


@pytest.mark.parametrize('age', [7, 8, 40])
def test_corrected_evidence_still_respects_the_seven_day_gate(clock, age):
    text = '\n'.join([META, API_INTRO, API_FEATURE, 'The Choices API is available through a developer console.'])
    _, evaluation, decision, results = replay(clock, API_TITLE, text, age=age)
    assert evaluation.impact == 80
    assert decision.publish is (age <= 7) and bool(results) is (age <= 7)


def test_mixed_current_and_future_features_do_not_borrow_an_unreleased_capability(clock):
    text = (
        'Orbit Assistant is now available on more devices.\n'
        'The assistant will support tool calling next month.'
    )
    _, evaluation, decision, results = replay(clock, 'Orbit AI Assistant: New features, on more devices', text)
    assert evaluation.category == 'product_update' and evaluation.impact == 60
    assert not decision.publish and not results


def test_available_feature_is_not_discarded_because_a_later_feature_is_future(clock):
    text = '\n'.join([META, API_INTRO, 'The Choices API is available through the console and supports tool calling.',
                      'The Choices API will support offline execution next month.'])
    _, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert evaluation.impact == 80 and decision.publish and results


def test_api_described_as_a_solution_remains_an_api(clock):
    text = ('Introducing Nebula Choices API, an AI solution for media tasks.\n'
            'The Choices API is available through the console and supports tool calling.')
    _, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert evaluation.category == 'api_release' and evaluation.impact == 80
    assert decision.publish and results


def test_calendar_promise_is_not_generic_available_in_access(clock):
    text = API_INTRO + '\nThe Choices API is available in November 2027 and supports streaming.'
    _, evaluation, decision, results = replay(clock, API_TITLE, text)
    assert evaluation.impact == 60 and not decision.publish and not results
