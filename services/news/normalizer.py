import re
from datetime import timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.news.models import NewsItem


class NewsNormalizer:
    """Clean news records and discard URL and near-title duplicates."""

    def __init__(self, title_similarity: float = 0.85) -> None:
        self.title_similarity = title_similarity

    def normalize(self, news: list[NewsItem]) -> list[NewsItem]:
        result: list[NewsItem] = []
        urls: set[str] = set()
        titles: list[str] = []
        for original in news:
            item = original.model_copy(deep=True)
            item.source = self._clean(item.source)
            item.title = self._clean(item.title)
            item.content = self._clean(item.content) or None
            item.url = self._url(item.url)
            item.image_url = self._url(item.image_url) if item.image_url else None
            item.category = self._clean(item.category).lower() or "other"
            if item.published_at:
                if item.published_at.tzinfo is None:
                    item.published_at = item.published_at.replace(tzinfo=timezone.utc)
                else:
                    item.published_at = item.published_at.astimezone(timezone.utc)
            comparable = item.title.casefold()
            if not item.title or not item.url or item.url in urls:
                continue
            if any(SequenceMatcher(None, comparable, title).ratio() >= self.title_similarity for title in titles):
                continue
            urls.add(item.url)
            titles.append(comparable)
            result.append(item)
        return result

    @staticmethod
    def _clean(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @staticmethod
    def _url(value: str) -> str:
        parts = urlsplit(value.strip())
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
            ]
        )
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
