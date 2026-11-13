from html import unescape
from html.parser import HTMLParser
from unittest.mock import patch

import httpx
import pytest

import test_quality_issues_persistence as quality_fixtures
from core.settings import settings
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.media_asset import MediaAsset
from models.metric import Metric
from models.post import Post
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.pipeline.content_pipeline import ContentPipeline
from services.ai_engine.prompts.writer_prompt import get_writer_system_prompt
from services.ai_engine.services.ai_service import AIService
from services.ai_engine.services.post_service import PostService
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService
from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.factory import PublisherFactory
from services.publisher.media import PublicationMedia
from services.publisher.models import PublicationReference
from services.publisher.publisher_service import PublisherService

quality_sessions = quality_fixtures.quality_sessions


@pytest.fixture
def sessions(quality_sessions, monkeypatch):
    monkeypatch.setattr(settings, 'ai_gateway_internal_token', 'test-only')
    with quality_sessions() as db:
        for channel in db.query(Channel):
            channel.gateway_channel_id = f'audit-{channel.language_code}'
        db.commit()
    return quality_sessions


def news(language='ru'):
    if language == 'ru':
        return ('Компания представила новую модель\n\n'
                + 'Компания выпустила модель и сообщила условия её использования. ' * 12)
    return ('Company releases a new model\n\n'
            + 'The company released a model and described its available features. ' * 12)


def legacy(text):
    headline, body = text.split('\n\n', 1)
    return f'## HOOK\n**{headline}**\n\n## INSIGHT\n{body}\n\n## VALUE\n\n## CONCLUSION'


def stub_llm(monkeypatch, ru, en):
    calls = []

    def chat(self, system, user):
        calls.append((system, user))
        return en if 'news translator' in system else ru

    monkeypatch.setattr(AIService, 'chat', chat)
    return calls


class TextFromHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        assert tag == 'b' and not attrs
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, text):
        self.parts.append(text)


def decoded(payload):
    parser = TextFromHTML()
    parser.feed(payload)
    parser.close()
    assert not parser.stack
    return ''.join(parser.parts)


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_clean_news_quality_contract(language):
    text = news(language)
    assert 700 <= QualityAgent.visible_length(text) <= 900
    assert QualityAgent().check(text) == {'score': 100, 'approved': True, 'issues': []}


@pytest.mark.parametrize('length,approved', [(699, False), (700, True), (900, True), (901, False)])
def test_visible_length_boundaries(length, approved):
    prefix = 'Headline\n\n'
    text = prefix + 'x' * (length - len('Headline '))
    assert QualityAgent.visible_length(text) == length
    assert QualityAgent().check(text)['approved'] is approved


@pytest.mark.parametrize('phrase', [
    'Если хотите, могу предложить подробный разбор.',
    'Если вы хотите, подготовлю ещё один вариант.',
    'При необходимости могу помочь.', 'Буду рад помочь.',
    'If you would like, I can provide more details.', 'I can also write another post.',
    'Let me know if you need anything else.', 'Would you like a summary?',
    'Here is the translation:',
])
def test_assistant_prose_is_rejected_without_silent_deletion(phrase):
    raw = news() + '\n\n' + phrase
    prepared = ContentPipeline.prepare_text(raw)
    assert phrase in prepared
    result = QualityAgent().check(prepared)
    assert not result['approved'] and 'AI assistant phrase' in result['issues']


def test_cleanup_preserves_inline_facts_quotes_names_dates_and_urls():
    raw = ('```markdown\n## HOOK\n**TopicModel v2: 12 ноября 2026**\n\n'
           'INSIGHT: Цена — 12 евро; API доступен на https://example.com/v2?a=1&b=2.\n\n'
           'VALUE: Представитель сказал: «Если хотите, могу предложить демо».\n\n'
           'CONCLUSION:\n```')
    prepared = ContentPipeline.prepare_text(raw)
    assert prepared == ('TopicModel v2: 12 ноября 2026\n\n'
                        'Цена — 12 евро; API доступен на https://example.com/v2?a=1&b=2.\n\n'
                        'Представитель сказал: «Если хотите, могу предложить демо».')
    assert QualityAgent.surface_issues(prepared) == []
    assert ContentPipeline.prepare_text(prepared) == prepared


@pytest.mark.parametrize('text', [
    'HOOK: meaningful fact', '## INSIGHT', '**raw emphasis**', '*raw italic*',
    '[source](https://example.com)', '```code```', '<b>raw HTML</b>', '- a list item',
])
def test_raw_surface_is_detected(text):
    assert QualityAgent.surface_issues(text)


def test_writer_and_translator_prompts_use_short_plain_news_without_changing_facts(monkeypatch):
    calls = stub_llm(monkeypatch, news(), news('en'))
    assert AIWriterService().generate_ru('TopicModel version 2 at https://example.com') == news()
    assert 'TopicModel version 2 at https://example.com' in calls[0][1]
    assert '700–900' in get_writer_system_prompt()
    assert 'plain text' in get_writer_system_prompt().lower()
    assert AITranslatorService().ru_to_en(news()) == news('en')
    assert news() in calls[1][1]
    assert 'Keep structure:' not in calls[1][1]


@pytest.mark.parametrize('bad_language', ['ru', 'en'])
@pytest.mark.parametrize('kind', ['empty', 'short', 'long', 'assistant', 'markup'])
def test_bad_ru_or_en_rejects_before_persistence_without_retry(sessions, monkeypatch, bad_language, kind):
    invalid = {'empty': ' ', 'short': 'Short news', 'long': news() + ' too long' * 100,
               'assistant': news() + '\n\nЕсли хотите, могу предложить ещё вариант.',
               'markup': news() + '\n\n[raw](https://example.com)'}[kind]
    calls = stub_llm(monkeypatch, invalid if bad_language == 'ru' else news(),
                     invalid if bad_language == 'en' else news('en'))
    result = ContentPipeline().generate_full_content('TopicModel')
    assert result['status'] == 'rejected'
    assert any(issue.startswith(bad_language.upper() + ': ') for issue in result['quality_issues'])
    assert len(calls) == 2
    with sessions() as db:
        assert all(db.query(model).count() == 0 for model in (
            Post, ContentVariant, ChannelContent, MediaAsset, Metric,
        ))


@pytest.mark.parametrize('with_image', [False, True])
def test_writer_to_outbound_payload_both_languages_once(sessions, monkeypatch, with_image):
    import json

    ru, en = news().strip(), news('en').strip()
    calls = stub_llm(monkeypatch, legacy(ru), legacy(en))
    saved = ContentPipeline().generate_full_content('TopicModel', source_url='https://example.com/news')
    assert saved['status'] == 'published'
    assert saved['ru'] == ru and saved['en'] == en
    assert len(calls) == 2 and ru in calls[1][1]
    with sessions() as db:
        assert {(v.language_code, v.content) for v in db.query(ContentVariant)} == {('ru', ru), ('en', en)}
        if with_image:
            db.add(MediaAsset(post_id=saved['id'], type='image', source='generated', origin='test',
                              license_type='generated', url='https://cdn.example/image.png',
                              metadata_={'generation_status': 'ready', 'language_code': None}))
            db.commit()
    outbound = []

    def handler(request):
        assert sessions.kw['bind'].pool.checkedout() == 0
        payload = json.loads(request.content)
        outbound.append(payload)
        assert payload['parse_mode'] == 'HTML'
        expected = ru if payload['gateway_channel_id'] == 'audit-ru' else en
        assert decoded(payload['text']) == expected
        assert payload['text'].startswith('<b>')
        assert not QualityAgent.surface_issues(decoded(payload['text']))
        assert len(payload['text']) <= (1024 if with_image else 4096)
        assert ('media' in payload) is with_image
        return httpx.Response(200, json={'status': 'published', 'provider': 'telegram',
                                        'channel_id': payload['gateway_channel_id'],
                                        'external_message_id': len(outbound)})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        class Adapter(TelegramPublisher):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, client=client)

        factory = PublisherFactory()
        factory.telegram_publisher_class = Adapter
        publisher = PublisherService(session_factory=sessions, factory=factory)
        results = publisher.publish_pending_for_posts([saved['id']])
        assert len(results) == 2 and all(result.success for result in results)
        assert publisher.publish_pending_for_posts([saved['id']]) == []
        assert ContentPipeline().generate_full_content('Updated headline', source_url='https://example.com/news')['status'] == 'duplicate'
    assert len(outbound) == 2 and len(calls) == 2


@pytest.mark.parametrize('raw', ['```unsupported```', 'Если хотите, могу предложить помощь.'])
def test_final_guard_blocks_raw_content_without_rewriting_or_repeating(sessions, raw):
    saved = PostService().save('Legacy', raw, raw)
    publisher = PublisherService(session_factory=sessions)
    with patch('httpx.post', side_effect=AssertionError('No HTTP for raw content')):
        results = publisher.publish_pending_for_posts([saved['id']])
        assert all(not result.success and result.outcome == 'failed' for result in results)
        assert publisher.publish_pending_for_posts([saved['id']]) == []
    with sessions() as db:
        assert db.get(Post, saved['id']).ru_content == raw
        assert db.query(Metric).filter_by(event_type='publication_succeeded').count() == 0
        assert {r.status for r in db.query(ChannelContent)} == {'failed'}


@pytest.mark.parametrize('limit', [1024, 4096])
def test_html_escaping_preserves_the_complete_plain_text(limit):
    text = 'Цена < 100 & рост > 2%\n\nAPI https://example.com/?a=1&b=2 и «цитата». 🙂'
    html = TelegramPublisher.render_html(text, limit)
    assert html == ('<b>Цена &lt; 100 &amp; рост &gt; 2%</b>\n\n'
                    'API https://example.com/?a=1&amp;b=2 и «цитата». 🙂')
    assert decoded(html) == text
    assert unescape(html).count('<b>') == 1


@pytest.mark.parametrize('limit', [1024, 4096])
def test_serialized_html_boundary_and_overflow(limit):
    text = 'x' * (limit - len('<b></b>'))
    assert len(TelegramPublisher.render_html(text, limit)) == limit
    with pytest.raises(ValueError, match='budget'):
        TelegramPublisher.render_html(text + 'x', limit)
    with pytest.raises(ValueError, match='budget'):
        TelegramPublisher.render_html('&' * (limit // 5), limit)
    with pytest.raises(ValueError, match='budget'):
        TelegramPublisher.render_html('🙂' * (limit // 2 + 1), limit)


def test_overlong_caption_fails_locally_without_cutting_or_sending():
    text = news() + '\n\n' + '&' * 1100
    outbound = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: outbound.append(r))) as client:
        publisher = TelegramPublisher('https://gateway.example', 'test-only', 'audit', text,
                                      media=PublicationMedia(1, 'image', 'https://cdn.example/a.png'), client=client)
        result = publisher.publish(PublicationReference(1, 1, 1))
    assert result.error_code == 'publication_not_ready' and result.outcome == 'failed'
    assert outbound == [] and publisher.text == text


def test_legacy_markdown_to_gateway_preserves_post_media_and_once_only_status(sessions):
    import json

    raw = '## HOOK\n**Заголовок**\n## INSIGHT\n**Факт** & подробности.\n## CONCLUSION'
    saved = PostService().save('Legacy', raw, raw)
    with sessions() as db:
        db.add(MediaAsset(post_id=saved['id'], type='image', source='generated', origin='test',
                          license_type='generated', url='https://cdn.example/legacy.png',
                          metadata_={'generation_status': 'ready', 'language_code': None}))
        db.commit()
    outbound = []

    def handler(request):
        payload = json.loads(request.content)
        outbound.append((payload, request.headers['Idempotency-Key']))
        assert payload['text'] == '<b>Заголовок</b>\n\n<b>Факт</b> &amp; подробности.'
        assert payload['media'] == {'type': 'image', 'url': 'https://cdn.example/legacy.png'}
        return httpx.Response(200, json={'status': 'published', 'provider': 'telegram',
                                        'channel_id': payload['gateway_channel_id'],
                                        'external_message_id': len(outbound)})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        class Adapter(TelegramPublisher):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, client=client)

        factory = PublisherFactory()
        factory.telegram_publisher_class = Adapter
        service = PublisherService(session_factory=sessions, factory=factory)
        assert all(r.success for r in service.publish_pending_for_posts([saved['id']]))
        assert service.publish_pending_for_posts([saved['id']]) == []
    assert len(outbound) == 2
    assert len({key for _, key in outbound}) == 2
    with sessions() as db:
        assert db.get(Post, saved['id']).ru_content == raw
        assert {row.status for row in db.query(ChannelContent)} == {'published'}
