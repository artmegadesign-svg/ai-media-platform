from services.news.collectors.base import RSSNewsCollector


class GoogleAINewsCollector(RSSNewsCollector):
    """Collect AI stories from Google's official technology blog feed."""

    source = "Google"
    feed_url = "https://blog.google/technology/ai/rss/"
