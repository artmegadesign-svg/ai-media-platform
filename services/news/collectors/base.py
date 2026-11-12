from abc import ABC, abstractmethod
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable, NamedTuple
from urllib.parse import urljoin
from urllib.error import URLError
import httpx
from xml.etree import ElementTree

from services.news.models import NewsItem, OfficialImagePolicy
from services.news.collectors.images import image_candidates
from services.news.urls import approved_url


class SourceDocument(NamedTuple):
    text: str
    url: str


class NewsCollector(ABC):
    """Replaceable interface implemented by every news source."""

    @abstractmethod
    def collect(self) -> list[NewsItem]:
        """Return news currently available from the source."""


class RSSNewsCollector(NewsCollector):
    """Small RSS/Atom collector with no scraping or provider-specific coupling."""

    source: str
    feed_url: str

    page_hosts: tuple[str, ...] = ()

    def __init__(
        self,
        fetcher: Callable[[str], str | SourceDocument] | None = None,
        *,
        image_policy: OfficialImagePolicy | None = None,
    ) -> None:
        self.fetcher = fetcher or self._fetch
        self.image_policy = image_policy or OfficialImagePolicy()

    def collect(self) -> list[NewsItem]:
        try:
            document = self.fetcher(self.feed_url)
            return self._parse(
                document.text if isinstance(document, SourceDocument) else document
            )
        except (OSError, URLError, httpx.HTTPError, ElementTree.ParseError, ValueError):
            # A temporarily unavailable external source must not stop other collectors.
            return []

    def _fetch(self, url: str) -> SourceDocument:
        # Validate every redirect before requesting it; never follow an arbitrary
        # feed link to a private address or an unrelated publication.
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            for _ in range(4):
                if not approved_url(url, self.page_hosts):
                    raise ValueError("Unapproved official source URL")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise ValueError("Official source document is too large")
                    return SourceDocument(data.decode("utf-8"), str(response.url))
        raise ValueError("Too many official source redirects")

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
        item = NewsItem(
            source=self.source,
            title=title,
            url=url,
            content=self._text(entry, "description", "summary", "content") or None,
            published_at=self._date(published),
        )
        if not approved_url(url, self.page_hosts):
            # Preserve news, but never fetch an untrusted entry or trust its media.
            item.image_discovery_status = "complete"
            item.image_discovery_error = "unapproved_release_url"
            return item
        # Extract RSS candidates first, so valid licensed media survives a page outage.
        item.official_images = image_candidates(
            entry,
            url,
            self.source,
            self.page_hosts,
            self.image_policy,
            None,
        )
        try:
            page = self.fetcher(url)
            base_url = page.url if isinstance(page, SourceDocument) else url
            if not approved_url(base_url, self.page_hosts):
                raise ValueError("Unapproved final release URL")
            item.official_images = image_candidates(
                entry,
                url,
                self.source,
                self.page_hosts,
                self.image_policy,
                page.text if isinstance(page, SourceDocument) else page,
                base_url=base_url,
            )
            item.image_discovery_status = "complete"
        except (OSError, URLError, httpx.HTTPError, ValueError):
            item.image_discovery_status = "temporary_error"
            item.image_discovery_error = "release_page_unavailable"
        return item

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
