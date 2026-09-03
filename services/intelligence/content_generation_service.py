"""Orchestrate approved intelligence through content and media preparation."""

from collections.abc import Iterable
from typing import Any, Callable, Protocol

from db.session import SessionLocal
from services.ai_engine.services.generator_service import GeneratorService
from services.intelligence.models import IntelligenceResult
from services.media.generation_service import (
    ImageGenerationProvider,
    MediaGenerationError,
    MediaGenerationService,
)
from services.media.planning_service import MediaPlanningService
from services.media.resolver import MediaStrategy


class GeneratorServiceProtocol(Protocol):
    def generate(self, topic: str) -> dict: ...


class IntelligenceContentGenerationService:
    """Generate content, then prepare media for each successfully persisted post.

    ``GeneratorService`` remains the owner of content persistence.  Media work is
    deliberately performed only after it returns the persisted post identifier.
    Image execution is optional until a production provider is supplied.
    """

    def __init__(
        self,
        generator: GeneratorServiceProtocol | None = None,
        *,
        image_provider: ImageGenerationProvider | None = None,
        session_factory: Callable[[], Any] = SessionLocal,
        planning_service_factory: Callable[[Any], MediaPlanningService] = MediaPlanningService,
        generation_service_factory: Callable[
            [Any, ImageGenerationProvider], MediaGenerationService
        ] = MediaGenerationService,
    ) -> None:
        self.generator = generator if generator is not None else GeneratorService()
        self.image_provider = image_provider
        self.session_factory = session_factory
        self.planning_service_factory = planning_service_factory
        self.generation_service_factory = generation_service_factory

    def generate(self, results: Iterable[IntelligenceResult]) -> list[dict]:
        """Pass normalized news headlines to the existing generation entry point."""
        generated = []
        for result in results:
            if not result.publish:
                continue

            topic = result.news.title.strip()
            if not topic:
                continue

            content = self.generator.generate(topic)
            orchestration = {
                **content,
                "source_id": str(result.news.id),
                "source_url": result.news.url,
                "content_generation_status": content.get("status"),
                "post_id": content.get("id"),
                "media_asset_id": None,
                "media_strategy": None,
                "media_generation_status": "not_started",
                "media_url": None,
            }

            # A rejection has no persisted Post and must never enter media flow.
            if content.get("status") == "rejected" or content.get("id") is None:
                generated.append(orchestration)
                continue

            db = self.session_factory()
            try:
                asset = self.planning_service_factory(db).plan(
                    content["id"], self._source_metadata(result)
                )
                metadata = dict(asset.metadata_ or {})
                strategy = metadata.get("strategy")
                generation_required = strategy == MediaStrategy.GENERATE_IMAGE.value
                orchestration.update(
                    media_asset_id=asset.id,
                    media_strategy=strategy,
                    media_generation_status=metadata.get("generation_status")
                    or "not_required",
                    media_url=None if generation_required else asset.url,
                )

                if generation_required:
                    if self.image_provider is None:
                        orchestration["media_generation_status"] = "pending"
                    else:
                        try:
                            asset = self.generation_service_factory(
                                db, self.image_provider
                            ).generate(asset.id, prompt=topic)
                        except MediaGenerationError:
                            orchestration["media_generation_status"] = "failed"
                        else:
                            orchestration.update(
                                media_generation_status="ready", media_url=asset.url
                            )
            finally:
                db.close()

            generated.append(orchestration)

        return generated

    @staticmethod
    def _source_metadata(result: IntelligenceResult) -> dict[str, Any]:
        """Map only metadata actually present in the intelligence contract.

        These fields intentionally do not claim official status or provenance.
        Consequently ordinary news safely resolves to generated media.
        """
        news = result.news
        published_at = getattr(news, "published_at", None)
        return {
            "title": news.title,
            "url": news.url,
            "image_url": getattr(news, "image_url", None),
            "source": news.source,
            "category": getattr(news, "category", None),
            "content": getattr(news, "content", None),
            "published_at": published_at.isoformat() if published_at else None,
            "editorial_format": result.editorial.format,
            "trend": result.trend,
        }
