"""Execute previously approved AI-image plans through an injected provider."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from models.media_asset import MediaAsset
from repositories.media_asset_repository import MediaAssetRepository


class MediaGenerationError(RuntimeError):
    """Base error raised while executing a media generation plan."""


class InvalidMediaPlanError(MediaGenerationError):
    """Raised when an asset is not an executable generated-image plan."""


@dataclass(frozen=True, slots=True)
class GeneratedMedia:
    """Provider-neutral description of a generated and durably stored image."""

    url: str
    thumbnail_url: str | None = None
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageGenerationProvider(Protocol):
    """Boundary implemented by a later concrete image/storage integration."""

    def generate(self, *, prompt: str, language_code: str | None) -> GeneratedMedia:
        """Generate and store an image, returning its durable public reference."""


class MediaGenerationService:
    """Turn a pending Phase 2 plan into a ready generated media asset.

    Network and vendor details deliberately live behind ``ImageGenerationProvider``.
    This keeps orchestration deterministic and makes retries idempotent once the
    asset has reached ``ready``.
    """

    def __init__(self, db: Session, provider: ImageGenerationProvider):
        self.db = db
        self.repository = MediaAssetRepository(db)
        self.provider = provider

    def generate(
        self,
        asset_id: int,
        *,
        prompt: str,
        language_code: str | None = None,
    ) -> MediaAsset:
        asset = self.repository.get(asset_id)
        if asset is None:
            raise InvalidMediaPlanError(f"Media asset {asset_id} was not found")

        metadata = dict(asset.metadata_ or {})
        self._validate(asset, metadata, prompt, language_code)
        if metadata.get("generation_status") == "ready":
            return asset

        try:
            result = self.provider.generate(
                prompt=prompt.strip(), language_code=language_code
            )
            if not isinstance(result.url, str) or not result.url.strip():
                raise MediaGenerationError("Image provider returned an empty URL")
        except Exception as exc:
            metadata["generation_status"] = "failed"
            metadata["generation_error"] = str(exc)
            asset.metadata_ = metadata
            self.db.commit()
            if isinstance(exc, MediaGenerationError):
                raise
            raise MediaGenerationError("Image generation failed") from exc

        metadata.update(
            {
                "generation_status": "ready",
                "planning_status": "complete",
                "generation_prompt": prompt.strip(),
                "language_code": language_code,
                "provider": result.provider,
                "provider_metadata": dict(result.metadata),
            }
        )
        metadata.pop("generation_error", None)
        asset.url = result.url.strip()
        asset.thumbnail_url = result.thumbnail_url
        asset.metadata_ = metadata
        self.db.commit()
        self.db.refresh(asset)
        return asset

    @staticmethod
    def _validate(
        asset: MediaAsset,
        metadata: dict[str, Any],
        prompt: str,
        language_code: str | None,
    ) -> None:
        if asset.source != "generated" or asset.type != "image":
            raise InvalidMediaPlanError("Only generated image plans can be executed")
        if metadata.get("strategy") != "generate_image":
            raise InvalidMediaPlanError("Asset does not use the generate_image strategy")
        if metadata.get("planning_status") not in {"generation_required", "complete"}:
            raise InvalidMediaPlanError("Asset is not awaiting image generation")
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidMediaPlanError("A non-empty generation prompt is required")
        if language_code not in {None, "ru", "en"}:
            raise InvalidMediaPlanError("language_code must be 'ru', 'en', or None")
