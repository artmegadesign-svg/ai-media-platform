from services.news.collectors.base import RSSNewsCollector


class OpenAINewsCollector(RSSNewsCollector):
    """Collect announcements from OpenAI's official news feed."""

    source = "OpenAI"
    feed_url = "https://openai.com/news/rss.xml"
