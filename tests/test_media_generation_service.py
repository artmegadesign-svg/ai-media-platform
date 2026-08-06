from dataclasses import dataclass, field

import pytest
from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.post import Post
from services.media.generation_service import (
    GeneratedMedia,
    InvalidMediaPlanError,
    MediaGenerationError,
    MediaGenerationService,
)
from services.media.planning_service import MediaPlanningService


def _post(db: Session) -> Post:
    post = Post(title="Generate", topic="media", ru_content="Текст", en_content="Text")
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@dataclass
class StubProvider:
    result: GeneratedMedia = field(
        default_factory=lambda: GeneratedMedia(
            url="https://cdn.example/generated/image.png",
            thumbnail_url="https://cdn.example/generated/thumb.png",
            provider="stub",
            metadata={"request_id": "req-1"},
        )
    )
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def generate(self, *, prompt: str, language_code: str | None) -> GeneratedMedia:
        self.calls.append((prompt, language_code))
        return self.result


def test_executes_pending_plan_and_persists_result():
    with SessionLocal() as db:
        asset = MediaPlanningService(db).plan(_post(db).id, None)
        provider = StubProvider()

        result = MediaGenerationService(db, provider).generate(
            asset.id, prompt="  Editorial illustration  ", language_code="en"
        )

        assert result.url == "https://cdn.example/generated/image.png"
        assert result.thumbnail_url == "https://cdn.example/generated/thumb.png"
        assert result.metadata_["planning_status"] == "complete"
        assert result.metadata_["generation_status"] == "ready"
        assert result.metadata_["generation_prompt"] == "Editorial illustration"
        assert result.metadata_["provider_metadata"] == {"request_id": "req-1"}
        assert provider.calls == [("Editorial illustration", "en")]


def test_ready_generation_is_idempotent():
    with SessionLocal() as db:
        asset = MediaPlanningService(db).plan(_post(db).id, None)
        provider = StubProvider()
        service = MediaGenerationService(db, provider)

        service.generate(asset.id, prompt="First")
        result = service.generate(asset.id, prompt="Retry")

        assert result.metadata_["generation_prompt"] == "First"
        assert provider.calls == [("First", None)]


def test_rejects_official_reference():
    with SessionLocal() as db:
        asset = MediaPlanningService(db).plan(
            _post(db).id,
            {
                "news_type": "official_release",
                "material_type": "image",
                "verified_official_source": True,
                "source_url": "https://official.example/image.png",
                "official_domain": "official.example",
                "origin": "press_office",
                "license_type": "official_publication",
                "provenance": {"release": "1"},
            },
        )

        with pytest.raises(InvalidMediaPlanError):
            MediaGenerationService(db, StubProvider()).generate(asset.id, prompt="No")


def test_records_provider_failure_for_retry():
    class FailingProvider:
        def generate(self, *, prompt: str, language_code: str | None) -> GeneratedMedia:
            raise RuntimeError("provider unavailable")

    with SessionLocal() as db:
        asset = MediaPlanningService(db).plan(_post(db).id, None)

        with pytest.raises(MediaGenerationError, match="Image generation failed"):
            MediaGenerationService(db, FailingProvider()).generate(
                asset.id, prompt="Illustration"
            )

        db.refresh(asset)
        assert asset.metadata_["generation_status"] == "failed"
        assert asset.metadata_["generation_error"] == "provider unavailable"
