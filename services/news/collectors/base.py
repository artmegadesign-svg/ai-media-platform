from abc import ABC, abstractmethod
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen
from xml.etree import ElementTree

from services.news.models import NewsItem


class NewsCollector(ABC):
    """Replaceable interface implemented by every news source."""

    @abstractmethod
    def collect(self) -> list[NewsItem]:
        """Return news currently available from the source."""


class RSSNewsCollector(NewsCollector):
    """Small RSS/Atom collector with no scraping or provider-specific coupling."""

    source: str
    feed_url: str

    def __init__(self, fetcher: Callable[[str], str] | None = None) -> None:
        self.fetcher = fetcher or self._fetch

    def collect(self) -> list[NewsItem]:
        try:
            return self._parse(self.fetcher(self.feed_url))
        except (OSError, URLError, ElementTree.ParseError, ValueError):
            # A temporarily unavailable external source must not stop other collectors.
            return []

    @staticmethod
    def _fetch(url: str) -> str:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - fixed official URLs
            return response.read().decode("utf-8")

    def _parse(self, xml: str) -> list[NewsItem]:
        root = ElementTree.fromstring(xml)
        entries = root.findall(".//item")
        if not entries:
            entries = root.findall(".//{*}entry")
        return [item for entry in entries if (item := self._item(entry)) is not None]

    def _item(self, entry: ElementTree.Element) -> NewsItem | None:
        title = self._text(entry, "title")
        url = self._text(entry, "link")
        if not url:
            link = entry.find("{*}link")
            url = link.get("href", "") if link is not None else ""
        if not title or not url:
            return None
        published = self._text(entry, "pubDate", "published", "updated")
        return NewsItem(
            source=self.source,
            title=title,
            url=url,
            content=self._text(entry, "description", "summary", "content") or None,
            published_at=self._date(published),
        )

    @staticmethod
    def _text(entry: ElementTree.Element, *names: str) -> str:
        for name in names:
            element = entry.find(name)
            if element is None:
                element = entry.find(f"{{*}}{name}")
            if element is not None and element.text:
                return element.text.strip()
        return ""

    @staticmethod
    def _date(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
