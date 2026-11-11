from services.news.collectors.base import RSSNewsCollector


class GoogleAINewsCollector(RSSNewsCollector):
    """Collect AI stories from Google's official technology blog feed."""

    source = "Google"
    page_hosts = ("blog.google", "www.blog.google")
    feed_url = "https://blog.google/technology/ai/rss/"
