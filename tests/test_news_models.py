from services.news.models import NewsItem


def test_news_item_is_created_with_safe_defaults():
    item = NewsItem(source="OpenAI", title="A release", url="https://openai.com/news/a")

    assert item.id
    assert item.category == "other"
    assert item.score == 0


def test_rss_collector_returns_news():
    from services.news.collectors.openai import OpenAINewsCollector

    xml = """<rss><channel><item><title>New model</title>
    <link>https://openai.com/news/model</link>
    <pubDate>Tue, 25 Aug 2026 10:00:00 GMT</pubDate>
    </item></channel></rss>"""
    result = OpenAINewsCollector(lambda url: xml).collect()

    assert len(result) == 1
    assert result[0].source == "OpenAI"
    assert result[0].title == "New model"
