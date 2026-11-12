from services.news.collectors.base import RSSNewsCollector


class OpenAINewsCollector(RSSNewsCollector):
    """Collect announcements from OpenAI's official news feed."""

    source = "OpenAI"
    page_hosts = ("openai.com", "www.openai.com")
    feed_url = "https://openai.com/news/rss.xml"
