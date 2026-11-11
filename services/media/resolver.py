"""Pure policy for selecting media to prepare for a news post."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from urllib.parse import urlparse

from pydantic import ValidationError

from services.news.urls import approved_url
from services.news.models import OfficialImageCandidate


class MediaStrategy(StrEnum):
    GENERATE_IMAGE = "generate_image"
    USE_OFFICIAL_IMAGE = "use_official_image"
    USE_OFFICIAL_INFOGRAPHIC = "use_official_infographic"
    USE_OFFICIAL_DOCUMENT = "use_official_document"
    USE_OFFICIAL_VIDEO = "use_official_video"


class MediaType(StrEnum):
    IMAGE = "image"
    INFOGRAPHIC = "infographic"
    DOCUMENT = "document"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class MediaDecision:
    strategy: MediaStrategy
    media_type: MediaType
    source: str
    origin: str
    source_url: str | None
    license_type: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MediaResolver:
    """Resolve normalized source metadata without I/O or side effects."""

    _release_types = {
        "image": (MediaStrategy.USE_OFFICIAL_IMAGE, MediaType.IMAGE),
        "release_image": (MediaStrategy.USE_OFFICIAL_IMAGE, MediaType.IMAGE),
        "diagram": (MediaStrategy.USE_OFFICIAL_IMAGE, MediaType.IMAGE),
        "infographic": (
            MediaStrategy.USE_OFFICIAL_INFOGRAPHIC,
            MediaType.INFOGRAPHIC,
        ),
        "document": (MediaStrategy.USE_OFFICIAL_DOCUMENT, MediaType.DOCUMENT),
        "pdf": (MediaStrategy.USE_OFFICIAL_DOCUMENT, MediaType.DOCUMENT),
    }

    def resolve(self, metadata: Mapping[str, Any] | None) -> MediaDecision:
        if not isinstance(metadata, Mapping):
            return self._generated("Source metadata is missing or invalid")

        if "official_images" in metadata:
            return self._resolve_images(metadata)

        material_type = metadata.get("material_type")
        if not isinstance(material_type, str):
            return self._generated("Material type is missing")
        material_type = material_type.lower()

        # Images embedded in ordinary news articles are never import candidates.
        if material_type in {"article_image", "third_party_image"}:
            return self._generated("Third-party article images are prohibited")

        if material_type == "video":
            candidate = (MediaStrategy.USE_OFFICIAL_VIDEO, MediaType.VIDEO)
        else:
            candidate = self._release_types.get(material_type)
            if candidate is None:
                return self._generated("Material type is not an approved official type")
            if metadata.get("news_type") != "official_release":
                return self._generated("Official release status is not confirmed")

        invalid_reason = self._validate_official(metadata)
        if invalid_reason:
            return self._generated(invalid_reason)

        strategy, media_type = candidate
        if media_type is MediaType.IMAGE and not self._usage_allowed(
            metadata.get("usage")
        ):
            return self._generated("Image reuse permission is not confirmed")
        provenance = dict(metadata["provenance"])
        decision_metadata = dict(metadata)
        decision_metadata["provenance"] = provenance
        return MediaDecision(
            strategy=strategy,
            media_type=media_type,
            source="official",
            origin=str(metadata["origin"]),
            source_url=str(metadata["source_url"]),
            license_type=str(metadata["license_type"]),
            reason="Official source and provenance were verified",
            metadata=decision_metadata,
        )

    def _resolve_images(self, metadata: Mapping[str, Any]) -> MediaDecision:
        audit = {
            "official_images": metadata.get("official_images"),
            "image_discovery_status": metadata.get("image_discovery_status"),
            "image_discovery_error": metadata.get("image_discovery_error"),
            "source_page_url": metadata.get("url"),
        }
        candidates = metadata.get("official_images")
        for raw in candidates if isinstance(candidates, list) else []:
            try:
                image = OfficialImageCandidate.model_validate(raw)
            except (ValidationError, TypeError):
                continue
            if (
                image.page_url != metadata.get("url")
                or image.source != metadata.get("source")
                or not approved_url(image.url, image.official_hosts)
                or not self._usage_allowed(
                    image.usage.model_dump() if image.usage else None
                )
            ):
                continue
            return MediaDecision(
                strategy=MediaStrategy.USE_OFFICIAL_IMAGE,
                media_type=MediaType.IMAGE,
                source="official",
                origin=image.source,
                source_url=image.url,
                license_type=image.usage.license_type,
                reason="Official image with explicit reuse permission",
                metadata={
                    **audit,
                    "source_url": image.url,
                    "usage": image.usage.model_dump(),
                    "provenance": {
                        "page_url": image.page_url,
                        "image_url": image.url,
                        "publisher": image.source,
                        "discovery_method": image.discovery_method,
                        "official_hosts": image.official_hosts,
                    },
                },
            )
        # An outage is not evidence of absence. Keep an unexecutable pending plan.
        deferred = metadata.get("image_discovery_status") == "temporary_error"
        return self._generated(
            "Official source temporarily unavailable"
            if deferred
            else "No suitable official image with confirmed reuse permission",
            {**audit, "generation_deferred": deferred},
        )

    @staticmethod
    def _usage_allowed(usage: Any) -> bool:
        # This stage does not change Publisher captions: images requiring a
        # visible credit must wait until attribution delivery is supported.
        if not isinstance(usage, Mapping):
            return False
        terms = usage.get("terms_url")
        try:
            terms_host = urlparse(terms).hostname if isinstance(terms, str) else None
        except ValueError:
            return False
        return (
            usage.get("usage_allowed") is True
            and usage.get("attribution_required") is False
            and all(
                isinstance(usage.get(key), str) and usage[key].strip()
                for key in ("license_type", "terms_url", "evidence")
            )
            and approved_url(terms, [terms_host])
        )

    def _validate_official(self, metadata: Mapping[str, Any]) -> str | None:
        if metadata.get("verified_official_source") is not True:
            return "Official source is not verified"

        required = ("source_url", "origin", "license_type")
        if any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip()
            for key in required
        ):
            return "Official source metadata is incomplete"

        provenance = metadata.get("provenance")
        if not isinstance(provenance, Mapping) or not provenance:
            return "Provenance metadata is missing"

        hostname = urlparse(str(metadata["source_url"])).hostname
        official_domain = metadata.get("official_domain")
        domain_verified = (
            isinstance(official_domain, str)
            and bool(hostname)
            and (
                hostname == official_domain or hostname.endswith(f".{official_domain}")
            )
        )
        publisher = metadata.get("publisher_identifier")
        official_publisher = metadata.get("official_publisher_identifier")
        publisher_verified = (
            isinstance(publisher, str)
            and bool(publisher)
            and publisher == official_publisher
        )
        if not domain_verified and not publisher_verified:
            return "Official domain or publisher identifier is not confirmed"
        return None

    @staticmethod
    def _generated(
        reason: str, metadata: dict[str, Any] | None = None
    ) -> MediaDecision:
        return MediaDecision(
            strategy=MediaStrategy.GENERATE_IMAGE,
            media_type=MediaType.IMAGE,
            source="generated",
            origin="ai_generated",
            source_url=None,
            license_type="generated",
            reason=reason,
            metadata=metadata or {},
        )
