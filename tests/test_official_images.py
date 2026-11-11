"""Official source extraction, permission policy, and existing media persistence."""

import json
from urllib.error import URLError

import httpx
import pytest

from services.news.collectors.openai import OpenAINewsCollector
from services.news.collectors.google_ai import GoogleAINewsCollector
from services.news.urls import approved_url
from services.news.models import ImageUsage, OfficialImagePolicy
from services.media.resolver import MediaResolver, MediaStrategy


PAGE = "https://openai.com/news/release"
IMAGE = "https://cdn.official.example/release.jpg"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"


def permission(**overrides):
    return ImageUsage(
        **{
            "usage_allowed": True,
            "license_type": "editorial_permission",
            "terms_url": "https://openai.com/press/permission",
            "evidence": "Permission for this image",
            "attribution_required": False,
            **overrides,
        }
    )


def feed(media="", *, url=PAGE):
    return f"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item>
      <title>Introducing a model</title><link>{url}</link>{media}
      </item></channel></rss>"""


def collect(media="", *, html="", policy=None, error=None, url=PAGE):
    calls = []

    def fetch(target):
        calls.append(target)
        if target.endswith("rss.xml"):
            return feed(media, url=url)
        if error:
            raise error
        return html

    item = OpenAINewsCollector(fetch, image_policy=policy).collect()[0]
    return item, calls


def metadata(item):
    return {
        "url": item.url,
        "source": item.source,
        "official_images": [
            image.model_dump(mode="json") for image in item.official_images
        ],
        "image_discovery_status": item.image_discovery_status,
        "image_discovery_error": item.image_discovery_error,
    }


def decision(item):
    return MediaResolver().resolve(metadata(item))


def policy(**permissions):
    return OfficialImagePolicy(
        image_hosts=["cdn.official.example"], permissions=permissions
    )


def test_rss_image_with_scoped_cc0_license():
    image = "https://openai.com/release.jpg"
    item, calls = collect(f'''<media:content url="{image}" medium="image">
      <media:license href="{CC0}"/></media:content>''')
    result = decision(item)
    assert result.strategy is MediaStrategy.USE_OFFICIAL_IMAGE
    assert result.source_url == image
    assert result.metadata["usage"]["license_type"] == "CC0-1.0"
    assert calls == [OpenAINewsCollector.feed_url, PAGE]  # Never download image bytes.


def test_rss_group_license_and_relative_enclosure():
    item, _ = collect(f'''<media:group><media:license href="{CC0}"/>
        <media:content url="/release.jpg" type="image/jpeg"/></media:group>''')
    assert decision(item).source_url == "https://openai.com/release.jpg"
    item, _ = collect(
        '<enclosure url="/photo.jpg" type="image/jpeg"/>',
        policy=policy(**{"https://openai.com/photo.jpg": permission()}),
    )
    assert decision(item).source_url == "https://openai.com/photo.jpg"


@pytest.mark.parametrize(
    "html",
    [
        f'<meta property="og:image" content="{IMAGE}">',
        f'<meta name="twitter:image" content="{IMAGE}">',
        f'<main><article><img src="{IMAGE}" width="1200" height="600"></article></main>',
    ],
)
def test_release_image_with_reviewed_exact_permission(html):
    item, _ = collect(html=html, policy=policy(**{IMAGE: permission()}))
    assert decision(item).source_url == IMAGE
    assert item.image_discovery_status == "complete"


def test_missing_image_is_complete_fallback():
    item, _ = collect(html="<main>No image</main>")
    assert item.official_images == []
    assert item.image_discovery_status == "complete"
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE
    assert decision(item).metadata["generation_deferred"] is False


@pytest.mark.parametrize(
    "usage",
    [
        None,
        permission(usage_allowed=False),
        permission(attribution_required=True, attribution="Owner"),
    ],
)
def test_official_host_does_not_imply_permission(usage):
    item, _ = collect(
        html=f'<meta property="og:image" content="{IMAGE}">',
        policy=policy(**({IMAGE: usage} if usage else {})),
    )
    assert len(item.official_images) == 1
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE


def test_unapproved_cdn_and_unrelated_permission_are_rejected():
    item, _ = collect(
        html=f'<meta property="og:image" content="{IMAGE}">',
        policy=OfficialImagePolicy(permissions={IMAGE: permission()}),
    )
    assert not item.official_images
    item, _ = collect(
        html=f'<meta property="og:image" content="{IMAGE}?other">',
        policy=policy(**{IMAGE: permission()}),
    )
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE


def test_untrusted_release_is_not_fetched():
    item, calls = collect(url="https://openai.com.attacker.example/release")
    assert calls == [OpenAINewsCollector.feed_url]
    assert item.image_discovery_error == "unapproved_release_url"
    assert not item.official_images


def test_page_license_does_not_grant_image_rights_and_site_chrome_is_ignored():
    item, _ = collect(
        html=f'<link rel="license" href="{CC0}"><header><img src="/logo.jpg"></header>'
        '<main><img src="/tracking.png" width="1"></main>'
    )
    assert not item.official_images
    item, _ = collect(
        html=f'<link rel="license" href="{CC0}"><meta property="og:image" content="/photo.jpg">'
    )
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE


@pytest.mark.parametrize(
    "error",
    [URLError("offline"), httpx.ReadTimeout("timeout"), ValueError("oversized")],
)
def test_temporary_page_failure_is_not_absence(error):
    item, _ = collect(error=error)
    assert item.image_discovery_status == "temporary_error"
    result = decision(item)
    assert result.metadata["generation_deferred"] is True
    assert "offline" not in json.dumps(
        result.metadata
    )  # Only safe error code is stored.


def test_licensed_rss_image_survives_page_outage():
    item, _ = collect(
        f'<media:content url="/photo.jpg" medium="image"><media:license href="{CC0}"/></media:content>',
        error=URLError("offline"),
    )
    assert decision(item).strategy is MediaStrategy.USE_OFFICIAL_IMAGE


@pytest.mark.parametrize(
    "url",
    [
        "http://openai.com/a",
        "https://openai.com.attacker.example/a",
        "https://user@openai.com/a",
        "https://127.0.0.1/a",
        "https://openai.com:8443/a",
        "https://openai.com/\\evil",
        "https://openai.com/a\n",
    ],
)
def test_unsafe_url_rejected(url):
    assert not approved_url(url, ["openai.com", "127.0.0.1"])


def test_redirect_target_is_checked_before_network(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "services.news.collectors.base.httpx.Client", lambda **_: client
    )
    with pytest.raises(ValueError, match="Unapproved"):
        OpenAINewsCollector()._fetch(PAGE)
    assert seen == [PAGE]


def test_google_atom_enclosure_uses_same_path():
    page = "https://blog.google/technology/ai/release"
    image = "https://blog.google/photo.jpg"
    xml = f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release</title>
       <link href="{page}"/><link rel="enclosure" type="image/jpeg" href="{image}"/>
       </entry></feed>'''
    collector = GoogleAINewsCollector(
        lambda url: xml if url == GoogleAINewsCollector.feed_url else "",
        image_policy=OfficialImagePolicy(permissions={image: permission()}),
    )
    item = collector.collect()[0]
    assert decision(item).source_url == image


def test_relative_image_is_resolved_against_validated_redirect_destination(monkeypatch):
    from services.news.collectors.base import SourceDocument

    final = "https://openai.com/new/release/"
    image = "https://openai.com/new/release/image.jpg"

    def fetch(url):
        if url == OpenAINewsCollector.feed_url:
            return feed()
        return SourceDocument('<meta property="og:image" content="image.jpg">', final)

    item = OpenAINewsCollector(
        fetch, image_policy=policy(**{image: permission()})
    ).collect()[0]
    assert decision(item).source_url == image
    assert item.official_images[0].page_url == PAGE


def test_explicit_permission_denial_overrides_rss_license():
    image = "https://openai.com/photo.jpg"
    item, _ = collect(
        f'<media:content url="{image}" medium="image"><media:license href="{CC0}"/></media:content>',
        policy=policy(**{image: permission(usage_allowed=False)}),
    )
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE


def test_normalization_keeps_signed_image_url_and_evidence():
    from services.news.normalizer import NewsNormalizer

    image = "https://openai.com/photo.jpg?utm_signature=secret&amp;token=42"
    raw = image.replace("&amp;", "&")
    item, _ = collect(
        f'<enclosure url="{image}" type="image/jpeg"/>',
        policy=policy(**{raw: permission()}),
    )
    normalized = NewsNormalizer().normalize([item])[0]
    assert normalized.official_images[0].url == raw
    assert normalized.official_images[0].usage == permission()
    assert decision(normalized).source_url == raw


def test_invalid_permission_url_fails_closed():
    item, _ = collect(
        html=f'<meta property="og:image" content="{IMAGE}">',
        policy=policy(**{IMAGE: permission(terms_url="https://[")}),
    )
    assert decision(item).strategy is MediaStrategy.GENERATE_IMAGE


def test_boolean_dimensions_do_not_break_page_extraction():
    item, _ = collect(
        html=f'<main><img src="{IMAGE}" width height></main>',
        policy=policy(**{IMAGE: permission()}),
    )
    assert decision(item).source_url == IMAGE


def test_settings_wires_reviewed_permissions_into_default_collectors(monkeypatch):
    from core.settings import settings
    from services.news.service import NewsService

    monkeypatch.setattr(
        settings, "official_image_policies", {"OpenAI": policy(**{IMAGE: permission()})}
    )
    collector = NewsService().collectors[0]
    collector.fetcher = lambda url: (
        feed()
        if url == collector.feed_url
        else f'<meta property="og:image" content="{IMAGE}">'
    )
    assert decision(collector.collect()[0]).source_url == IMAGE
