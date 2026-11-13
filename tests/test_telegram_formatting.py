from html.parser import HTMLParser

import httpx
import pytest

from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.media import PublicationMedia
from services.publisher.models import PublicationReference


class SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        assert tag in {'b', 'i', 'code', 'a'}
        assert attrs == [] or (tag == 'a' and len(attrs) == 1 and attrs[0][0] == 'href')
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, data):
        self.text.append(data)


def visible(html):
    parser = SafeHTML()
    parser.feed(html)
    parser.close()
    assert parser.stack == []
    return ''.join(parser.text)


@pytest.mark.parametrize('text,expected', [
    ('Заголовок\nТекст новости.', '<b>Заголовок</b>\n\nТекст новости.'),
    ('**Заголовок**\n**Факт** и *важность*; __bold__ и _italic_.',
     '<b>Заголовок</b>\n\n<b>Факт</b> и <i>важность</i>; <b>bold</b> и <i>italic</i>.'),
    ('Новость\n`a < b & c`', '<b>Новость</b>\n\n<code>a &lt; b &amp; c</code>'),
    ('## HOOK\r\n**Заголовок**\r\n## INSIGHT\r\nФакт.\r\nVALUE: Значение.\r\n## CONCLUSION',
     '<b>Заголовок</b>\n\nФакт.\nЗначение.'),
    ('# Новость\n## Почему это важно\nФакты.',
     '<b>Новость</b>\n\n<b>Почему это важно</b>\nФакты.'),
    ('Новость\n<script>alert(1)</script> & <b>текст</b> &amp;',
     '<b>Новость</b>\n\n&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;текст&lt;/b&gt; &amp;amp;'),
])
def test_safe_rendering(text, expected):
    html = TelegramPublisher.render_html(text)
    assert html == expected
    visible(html)


def test_links_escape_attributes_and_keep_url_in_plain_fallback():
    text = 'News\n[source](https://example.com/?a=1&b="value")'
    plain, html = TelegramPublisher._render_parts(text, None)
    assert 'href="https://example.com/?a=1&amp;b=&quot;value&quot;"' in html
    assert 'https://example.com/?a=1&b="value"' in plain
    assert visible(html) == 'News\n\nsource'


@pytest.mark.parametrize('text', [
    'News\n[x](javascript:alert(1))', 'News\n```code```',
    'News\n**unclosed', '## HOOK\n## INSIGHT',
    'News\nЕсли хотите, могу предложить помощь.',
])
def test_unsupported_or_unsuitable_content_fails_before_network(text):
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: requests.append(r))) as client:
        publisher = TelegramPublisher('https://gateway.example', 'test', 'channel', text, client=client)
        result = publisher.publish(PublicationReference(1, 1, 1))
    assert result.outcome == 'failed'
    assert requests == []


@pytest.mark.parametrize('text,expected_mode', [('**' + 'Я' * 1024 + '**', None), ('**' + '🙂' * 512 + '**', 'HTML')], ids=['cyrillic', 'emoji'])
def test_exact_plain_caption_fallback_has_no_markdown(text, expected_mode):
    media = PublicationMedia(1, 'image', 'https://cdn.example/a.png')
    caption, mode = TelegramPublisher.prepare_publication(text, media)
    assert mode == expected_mode
    if mode == 'HTML':
        caption = visible(caption)
    assert '*' not in caption
    assert len(caption.encode('utf-16-le')) // 2 == 1024
    with pytest.raises(ValueError, match='1024'):
        TelegramPublisher.prepare_publication(text + 'я', media)


def test_formatted_caption_keeps_credit_and_facts_when_wire_html_overflows():
    media = PublicationMedia(1, 'image', 'https://cdn.example/a.png', credit='Источник & автор')
    text = 'Новость\n**' + '&' * 400 + '**'
    caption, mode = TelegramPublisher.prepare_publication(text, media)
    assert mode is None
    assert caption == 'Новость\n\n' + '&' * 400 + '\n\nИсточник & автор'
