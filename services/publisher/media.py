"""Media preparation for the existing publisher flow."""

from dataclasses import dataclass

from models.media_asset import MediaAsset
from services.media.resolver import MediaResolver


@dataclass(frozen=True, slots=True)
class PublicationMedia:
    """Provider-neutral media selected for a single channel publication."""

    asset_id: int
    type: str
    url: str
    credit: str | None = None


def select_publication_media(
    assets: list[MediaAsset], language_code: str
) -> PublicationMedia | None:
    """Select the oldest usable image, preferring an exact language match.

    Generated assets must have completed generation. Official references must
    have completed planning. Within each language priority, ``created_at`` and
    then the database id provide a stable selection order.
    """
    language = language_code.casefold()
    eligible: list[tuple[int, object, int, MediaAsset, str]] = []
    for asset in assets:
        metadata = asset.metadata_ or {}
        asset_language = metadata.get("language_code")
        if asset_language not in {None, language}:
            continue

        url = asset.url.strip() if isinstance(asset.url, str) else ""
        if not url or url.startswith("media://pending/") or asset.type != "image":
            continue
        if asset.source == "generated":
            if metadata.get("generation_status") != "ready":
                continue
        elif asset.source == "official":
            if metadata.get("planning_status") != "reference_ready":
                continue
            if not MediaResolver.image_usage_allowed(metadata.get("usage")):
                continue
        else:
            continue

        language_priority = 0 if asset_language == language else 1
        eligible.append((language_priority, asset.created_at, asset.id, asset, url))

    if not eligible:
        return None

    _, _, _, selected, url = min(eligible, key=lambda item: item[:3])
    usage = (selected.metadata_ or {}).get("usage") or {}
    credit = usage.get("attribution") if selected.source == "official" else None
    return PublicationMedia(
        asset_id=selected.id,
        type=selected.type,
        url=url,
        credit=credit if isinstance(credit, str) and credit.strip() else None,
    )
