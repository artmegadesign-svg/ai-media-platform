"""Image metadata extraction for the existing official news collectors.

No image bytes, search engines, or third-party article pages are fetched here.
"""

from html.parser import HTMLParser
from urllib.parse import urljoin

from services.news.models import ImageUsage, OfficialImageCandidate, OfficialImagePolicy
from services.news.urls import approved_url


CC0_URLS = {
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "http://creativecommons.org/publicdomain/zero/1.0/",
}
MEDIA_NS = "http://search.yahoo.com/mrss/"


class ReleaseImageParser(HTMLParser):
    """Only primary social images and images inside main/article, not site chrome."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[tuple[str, str]] = []
        self._body_depth = 0

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag in {"article", "main"}:
            self._body_depth += 1
        if tag == "meta" and (
            data.get("property") or data.get("name") or ""
        ).lower() in {
            "og:image",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
        }:
            if data.get("content"):
                self.images.append((data["content"], "release_meta"))
        if tag == "img" and self._body_depth and data.get("src"):
            # Tracking pixels and explicitly tiny decorative images are unsuitable.
            dimensions = [(data.get(key) or "") for key in ("width", "height")]
            if any(value.isdigit() and int(value) < 200 for value in dimensions):
                return
            self.images.append((data["src"], "release_body"))

    def handle_endtag(self, tag):
        if tag in {"article", "main"}:
            self._body_depth = max(0, self._body_depth - 1)


def image_candidates(
    entry,
    page_url: str,
    source: str,
    page_hosts: tuple[str, ...],
    policy: OfficialImagePolicy,
    page_html: str | None,
    *,
    base_url: str | None = None,
) -> list[OfficialImageCandidate]:
    hosts = list(dict.fromkeys([*page_hosts, *policy.image_hosts]))
    found: list[tuple[str, str, str | None]] = []

    def walk(node, inherited_license=None):
        # media:license is scoped to this content/group, never a page-wide license.
        license_node = node.find(f"{{{MEDIA_NS}}}license")
        license_url = license_node.get("href") if license_node is not None else None
        if license_node is not None and not license_url:
            license_url = (license_node.text or "").strip()
        scoped_license = license_url or inherited_license
        for child in node:
            if child.tag == f"{{{MEDIA_NS}}}content" and (
                child.get("medium") == "image"
                or child.get("type", "").startswith("image/")
            ):
                child_license = child.find(f"{{{MEDIA_NS}}}license")
                own_license = (
                    None
                    if child_license is None
                    else (
                        child_license.get("href") or (child_license.text or "").strip()
                    )
                )
                found.append(
                    (child.get("url", ""), "rss_media", own_license or scoped_license)
                )
            elif (
                child.tag.rsplit("}", 1)[-1] in {"enclosure", "link"}
                and (
                    child.tag.rsplit("}", 1)[-1] == "enclosure"
                    or child.get("rel") == "enclosure"
                )
                and child.get("type", "").startswith("image/")
            ):
                found.append(
                    (child.get("url") or child.get("href", ""), "rss_enclosure", None)
                )
            if child.tag == f"{{{MEDIA_NS}}}group":
                walk(child, scoped_license)

    walk(entry)
    if page_html is not None:
        parser = ReleaseImageParser()
        parser.feed(page_html)
        found.extend((url, method, None) for url, method in parser.images)
    candidates = []
    seen = set()
    for reference, method, license_url in found:
        url = urljoin(base_url or page_url, reference)
        if not reference or not approved_url(url, hosts) or url in seen:
            continue
        seen.add(url)
        usage = policy.permissions.get(url)
        if usage is None and license_url in CC0_URLS:
            usage = ImageUsage(
                license_type="CC0-1.0",
                terms_url=license_url.replace("http://", "https://", 1),
                evidence="Explicit media:license for image in official RSS",
                usage_allowed=True,
            )
        candidates.append(
            OfficialImageCandidate(
                url=url,
                page_url=page_url,
                source=source,
                discovery_method=method,
                official_hosts=hosts,
                usage=usage,
            )
        )
    return candidates
