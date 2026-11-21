"""Reservation regressions: all AI calls are replaced with deterministic fakes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from db.session import SessionLocal
from models.ai_generation_reservation import AIGenerationReservation as Reservation
from models.post import Post
from services.ai_engine.services.generation_reservation_service import (
    GenerationReservationService, LostGenerationLease, _now,
)
from services.ai_engine.pipeline.content_pipeline import ContentPipeline
from services.ai_engine.services.post_service import PostService


URL = "https://example.com/lease-news"


def service():
    return GenerationReservationService(lease_seconds=120)


def test_parallel_claim_has_one_winner():
    barrier = Barrier(2)

    def attempt(_):
        barrier.wait(timeout=10)
        return service().claim(URL)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(attempt, range(2)))
    assert sum(c is not None for c in claims) == 1


def test_completed_cannot_be_reclaimed():
    claim = service().claim(URL)
    assert claim is not None and service().start(claim)
    with SessionLocal.begin() as db:
        db.add(Post(source_key=claim.source_key, source_url=claim.canonical_url,
                    title="Test", topic="Test", status="published",
                    ru_content="ru", en_content="en"))
        db.flush()
        row = db.get(Reservation, claim.source_key)
        row.status = "completed"
        row.owner_token = None
    assert service().claim(URL) is None


def test_expired_reserved_reclaim_increments_fence():
    first = service().claim(URL)
    with SessionLocal.begin() as db:
        db.get(Reservation, first.source_key).lease_expires_at = _now() - timedelta(seconds=1)
    second = service().claim(URL)
    assert second is not None
    assert second.owner_token != first.owner_token
    assert second.lease_version == first.lease_version + 1
    assert not service().start(first)
    assert service().start(second)


def test_expired_generating_becomes_uncertain_and_never_reclaims():
    claim = service().claim(URL)
    assert service().start(claim)
    with SessionLocal.begin() as db:
        db.get(Reservation, claim.source_key).lease_expires_at = _now() - timedelta(seconds=1)
    assert service().claim(URL) is None
    assert service().reconcile_expired_generating(claim.source_key)
    assert service().claim(URL) is None
    with SessionLocal() as db:
        assert db.get(Reservation, claim.source_key).status == "uncertain"


def test_uncertain_cannot_be_restarted():
    claim = service().claim(URL)
    assert service().start(claim)
    assert service().finish_without_post(claim, status="uncertain")
    assert service().claim(URL) is None


def test_stale_worker_cannot_complete_post():
    first = service().claim(URL)
    with SessionLocal.begin() as db:
        db.get(Reservation, first.source_key).lease_expires_at = _now() - timedelta(seconds=1)
    second = service().claim(URL)
    assert service().start(second)
    with pytest.raises(LostGenerationLease):
        PostService().save("Topic", "ru", "en", source_url=URL, reservation=first)
    with SessionLocal() as db:
        assert db.execute(select(Post).where(Post.source_key == first.source_key)).first() is None


def test_post_and_reservation_commit_together():
    claim = service().claim(URL)
    assert service().start(claim)
    result = PostService().save("Topic", "ru", "en", source_url=URL, reservation=claim)
    assert result["post_created"] is True
    with SessionLocal() as db:
        row = db.get(Reservation, claim.source_key)
        assert row.status == "completed" and row.post_id == result["id"]
    assert service().claim(URL) is None


def test_post_failure_rolls_back_reservation_completion(monkeypatch):
    claim = service().claim(URL)
    assert service().start(claim)
    import services.ai_engine.services.post_service as post_module

    def fail(*args, **kwargs):
        raise RuntimeError("simulated database insert failure")

    monkeypatch.setattr(post_module, "ContentVariant", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        PostService().save("Topic", "ru", "en", source_url=URL, reservation=claim)
    with SessionLocal() as db:
        row = db.get(Reservation, claim.source_key)
        assert row.status == "generating" and row.post_id is None
        assert db.execute(select(Post).where(Post.source_key == claim.source_key)).first() is None


def test_pipeline_uncertain_blocks_second_paid_call(monkeypatch):
    calls = []
    from services.ai_engine.services.writer_service import AIWriterService

    def failed_writer(self, topic):
        calls.append(topic)
        raise TimeoutError("provider outcome unknown")

    monkeypatch.setattr(AIWriterService, "generate_ru", failed_writer)
    pipeline = ContentPipeline()
    with pytest.raises(TimeoutError):
        pipeline.generate_full_content("Topic", source_url=URL)
    assert pipeline.generate_full_content("Topic", source_url=URL) == {
        "status": "reserved", "post_created": False,
    }
    assert len(calls) == 1


def test_normal_generation_without_source_does_not_reserve(monkeypatch):
    from services.ai_engine.services.writer_service import AIWriterService
    from services.ai_engine.services.translator_service import AITranslatorService
    from services.ai_engine.agents.quality_agent import QualityAgent

    monkeypatch.setattr(AIWriterService, "generate_ru", lambda self, topic: "ru")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda self, text: "en")
    monkeypatch.setattr(QualityAgent, "check", lambda self, text: {
        "score": 100, "approved": True, "issues": None,
    })
    result = ContentPipeline().generate_full_content("Manual topic")
    assert result["post_created"] is True
    with SessionLocal() as db:
        assert db.query(Reservation).count() == 0
