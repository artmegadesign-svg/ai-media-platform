from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.pipeline.content_pipeline import ContentPipeline
from services.ai_engine.services.generator_service import GeneratorService
from services.intelligence.content_generation_service import IntelligenceContentGenerationService


def valid():
    return 'Factual headline\n\n' + 'Confirmed source evidence. ' * 30


def pipeline(ru, en):
    p = ContentPipeline.__new__(ContentPipeline)
    p.strategy = SimpleNamespace(analyze=lambda topic: {'topic': topic})
    p.writer = SimpleNamespace(generate_ru=Mock(side_effect=ru))
    p.translator = SimpleNamespace(ru_to_en=Mock(side_effect=en))
    p.quality = QualityAgent()
    p.storage = Mock()
    p.storage.find_by_source_key.return_value = None
    p.storage.save.return_value = {'post_created': False, 'status': 'saved'}
    return p


@pytest.mark.parametrize('ru,en,counts', [
    ([valid()], [valid()], (1, 1)),
    (['Short', valid()], [valid()], (2, 1)),
    ([valid()], ['Short', valid()], (1, 2)),
    (['Short', valid()], ['Short', valid()], (2, 2)),
])
def test_independent_bounded_recovery(ru, en, counts):
    p = pipeline(ru, en)
    assert p.generate_full_content('Title')['status'] == 'saved'
    assert (p.writer.generate_ru.call_count, p.translator.ru_to_en.call_count) == counts
    p.storage.save.assert_called_once()
    if counts[1] == 2:
        first, second = [c.args[0] for c in p.translator.ru_to_en.call_args_list]
        assert second.startswith(first)
        assert 'Previous visible length:' in second


@pytest.mark.parametrize('bad', ['', valid() + '\nIf you want, I can help.'])
def test_nonrepairable_ru_never_translates(bad):
    p = pipeline([bad], [])
    result = p.generate_full_content('Title')
    assert result['status'] == 'rejected' and result['en'] == ''
    p.translator.ru_to_en.assert_not_called()
    p.storage.save.assert_not_called()


def test_exhausted_ru_stops_before_translation():
    p = pipeline(['Short', 'Still short'], [])
    assert p.generate_full_content('Title')['status'] == 'rejected'
    assert p.writer.generate_ru.call_count == 2
    p.translator.ru_to_en.assert_not_called()
    p.storage.save.assert_not_called()


def test_existing_evidence_reaches_writer_through_all_layers():
    p = pipeline([valid()], [valid()])
    generator = GeneratorService.__new__(GeneratorService)
    generator.pipeline = p
    news = SimpleNamespace(title='Original title', url='https://example.com/news',
                           content='Confirmed facts from source', id='source-1')
    result = SimpleNamespace(publish=True, news=news)
    IntelligenceContentGenerationService(generator).generate([result])
    prompt = p.writer.generate_ru.call_args.args[0]
    assert news.content in prompt and news.url in prompt and news.title in prompt
    assert p.storage.save.call_args.args[0] == news.title
    assert p.storage.save.call_args.kwargs['source_url'] == news.url


def test_exhausted_en_never_regenerates_ru_or_saves():
    p = pipeline([valid()], ['Short', 'Still short'])
    result = p.generate_full_content('Title')
    assert result['status'] == 'rejected'
    assert result['ru'] == valid().strip()
    assert all(issue.startswith('EN: ') for issue in result['issues'])
    assert p.writer.generate_ru.call_count == 1
    assert p.translator.ru_to_en.call_count == 2
    p.storage.save.assert_not_called()


@pytest.mark.parametrize('check', [None, {'approved': False, 'issues': ['Unknown issue']},
    {'approved': False, 'issues': [
        'Content too short (minimum 700 visible characters)', 'Factual error']}])
def test_empty_unknown_and_mixed_quality_fail_without_retry(check):
    p = pipeline([valid()], [])
    p.quality = SimpleNamespace(check=lambda text: check)
    assert p.generate_full_content('Title')['status'] == 'rejected'
    assert p.writer.generate_ru.call_count == 1
    p.translator.ru_to_en.assert_not_called()
    p.storage.save.assert_not_called()
