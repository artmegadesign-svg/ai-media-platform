"""Independent collection and ranking layer for official AI news."""

from services.news.models import NewsItem
from services.news.normalizer import NewsNormalizer
from services.news.scorer import NewsScorer
from services.news.service import NewsService

__all__ = ["NewsItem", "NewsNormalizer", "NewsScorer", "NewsService"]
