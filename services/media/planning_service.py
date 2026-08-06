"""Persist preparatory media plans; execution belongs to later phases."""

from typing import Any, Mapping

from sqlalchemy.orm import Session

from models.media_asset import MediaAsset
from services.media.resolver import MediaDecision, MediaResolver, MediaStrategy
from services.media.service import MediaService


class MediaPlanningService:
    def __init__(self, db: Session, resolver: MediaResolver | None = None):
        self.media_service = MediaService(db)
        self.resolver = resolver or MediaResolver()

    def plan(
        self, post_id: int, source_metadata: Mapping[str, Any] | None
    ) -> MediaAsset:
        decision = self.resolver.resolve(source_metadata)
        asset = self._to_asset(post_id, decision)
        return self.media_service.attach_asset(asset)

    @staticmethod
    def _to_asset(post_id: int, decision: MediaDecision) -> MediaAsset:
        metadata = {
            **decision.metadata,
            "planning_status": "generation_required"
            if decision.strategy is MediaStrategy.GENERATE_IMAGE
            else "reference_ready",
            "generation_status": "pending"
            if decision.strategy is MediaStrategy.GENERATE_IMAGE
            else None,
            "strategy": decision.strategy.value,
            "reason": decision.reason,
            # A single neutral asset is planned by default. A later phase may set
            # this to "ru" or "en" when language-specific generation is needed.
            "language_code": decision.metadata.get("language_code"),
        }
        url = decision.source_url or f"media://pending/{decision.strategy.value}"
        return MediaAsset(
            post_id=post_id,
            type=decision.media_type.value,
            source=decision.source,
            origin=decision.origin,
            license_type=decision.license_type,
            url=url,
            metadata_=metadata,
        )
