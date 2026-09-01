from datetime import datetime

from services.news.models import NewsItem
from services.news.normalizer import NewsNormalizer


def _news(title: str, url: str) -> NewsItem:
    return NewsItem(
        source=" OpenAI ", title=title, url=url, published_at=datetime(2026, 8, 25)
    )


def test_normalizer_removes_duplicate_canonical_urls():
    news = [
        _news("First", "https://OPENAI.com/news/first/?utm_source=test"),
        _news("Different", "https://openai.com/news/first"),
    ]

    result = NewsNormalizer().normalize(news)

    assert len(result) == 1
    assert result[0].url == "https://openai.com/news/first"
    assert result[0].published_at.tzinfo is not None


def test_normalizer_removes_similar_titles_and_cleans_text():
    news = [
        _news("  Announcing   our newest model ", "https://example.com/one"),
        _news("Announcing our newest model!", "https://example.com/two"),
    ]

    result = NewsNormalizer(title_similarity=0.8).normalize(news)

    assert len(result) == 1
    assert result[0].title == "Announcing our newest model"
