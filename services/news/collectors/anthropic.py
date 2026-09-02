from services.news.collectors.base import NewsCollector
from services.news.models import NewsItem


class AnthropicNewsCollector(NewsCollector):
    """Extension point for Anthropic's official news page.

    Anthropic does not expose a stable official RSS endpoint, so this collector
    deliberately avoids scraping until an approved feed or API is available.
    """

    source = "Anthropic"
    news_url = "https://www.anthropic.com/news"

    def collect(self) -> list[NewsItem]:
        return []
