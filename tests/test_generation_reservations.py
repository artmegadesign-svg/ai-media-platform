"""Reservation regressions: all AI calls are replaced with deterministic fakes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import test_quality_issues_persistence as quality_fixtures

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


quality_sessions = quality_fixtures.quality_sessions

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
    assert not service().reconcile_expired_generating(claim.source_key)
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


def test_existing_post_reconciles_expired_reservation():
    claim = service().claim(URL)
    result = PostService().save("Topic", "ru", "en", source_url=URL)
    with SessionLocal.begin() as db:
        db.get(Reservation, claim.source_key).lease_expires_at = _now() - timedelta(seconds=1)
    assert service().claim(URL) is None
    with SessionLocal() as db:
        row = db.get(Reservation, claim.source_key)
        assert row.status == "completed"
        assert row.post_id == result["id"]
    assert not service().start(claim)


@pytest.mark.parametrize("approved", [True, False])
def test_expired_writer_cannot_dispatch_translation_or_correction(monkeypatch, approved):
    pipeline = ContentPipeline()
    calls = []

    def writer(topic):
        calls.append("writer")
        with SessionLocal.begin() as db:
            row = db.query(Reservation).one()
            row.lease_expires_at = _now() - timedelta(seconds=1)
        return "ru"

    monkeypatch.setattr(pipeline.writer, "generate_ru", writer)
    monkeypatch.setattr(pipeline.translator, "ru_to_en", lambda text: pytest.fail("paid translation"))
    monkeypatch.setattr(pipeline.quality, "check", lambda text: {
        "approved": approved, "score": 100 if approved else 0,
        "issues": [] if approved else ["Headline too long"],
    })
    with pytest.raises(LostGenerationLease):
        pipeline.generate_full_content("Topic", source_url=URL)
    assert calls == ["writer"]
    with SessionLocal() as db:
        assert db.query(Reservation).one().status == "uncertain"
    assert pipeline.generate_full_content("Topic", source_url=URL)["post_created"] is False


def test_stale_owner_cannot_renew_or_finish():
    first = service().claim(URL)
    with SessionLocal.begin() as db:
        db.get(Reservation, first.source_key).lease_expires_at = _now() - timedelta(seconds=1)
    second = service().claim(URL)
    assert service().start(second)
    assert not service().renew(first)
    assert not service().finish_without_post(first, status="uncertain")
    with SessionLocal() as db:
        assert db.get(Reservation, first.source_key).owner_token == second.owner_token


@pytest.mark.parametrize("stage", ["variant", "channel", "commit"])
def test_persistence_failure_rolls_back_all_rows(monkeypatch, stage):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from models.channel import Channel
    from models.channel_content import ChannelContent
    from models.content_variant import ContentVariant

    with SessionLocal.begin() as db:
        db.add(Channel(name="Lease test", platform="telegram", language_code="ru"))
    claim = service().claim(URL)
    assert service().start(claim)

    def fail(*args):
        raise RuntimeError("injected persistence failure")

    if stage == "commit":
        original_commit = Session.commit

        def fail_commit(db):
            db.flush()
            fail()

        monkeypatch.setattr(Session, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError, match="injected persistence"):
                PostService().save("Topic", "ru", "en", source_url=URL, reservation=claim)
        finally:
            monkeypatch.setattr(Session, "commit", original_commit)
    else:
        model = ContentVariant if stage == "variant" else ChannelContent
        event.listen(model, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="injected persistence"):
                PostService().save("Topic", "ru", "en", source_url=URL, reservation=claim)
        finally:
            event.remove(model, "before_insert", fail)

    with SessionLocal() as db:
        assert db.query(Post).count() == 0
        assert db.query(ContentVariant).count() == 0
        assert db.query(ChannelContent).count() == 0
        row = db.get(Reservation, claim.source_key)
        assert row.status == "generating"
        assert row.post_id is None


def test_duplicate_save_reconciles_without_overwriting_post():
    claim = service().claim(URL)
    assert service().start(claim)
    existing = PostService().save("Original", "ru", "en", source_url=URL)
    duplicate = PostService().save("Stale", "other", "other", source_url=URL, reservation=claim)
    assert duplicate["post_created"] is False
    with SessionLocal() as db:
        post = db.query(Post).one()
        assert post.title == "Original"
        row = db.get(Reservation, claim.source_key)
        assert row.status == "completed"
        assert row.post_id == existing["id"]


def test_rejected_is_terminal():
    claim = service().claim(URL)
    assert service().start(claim)
    assert service().finish_without_post(claim, status="rejected")
    assert service().claim(URL) is None


def test_database_backend_concurrent_claim(quality_sessions):
    barrier = Barrier(2)
    reservation_service = GenerationReservationService(session_factory=quality_sessions)

    def attempt(_):
        barrier.wait(timeout=10)
        return reservation_service.claim(URL)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(attempt, range(2)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert reservation_service.start(winners[0])
    assert reservation_service.claim(URL) is None
    result = PostService().save("Topic", "ru", "en", source_url=URL, reservation=winners[0])
    with quality_sessions() as db:
        row = db.get(Reservation, winners[0].source_key)
        assert row.status == "completed"
        assert row.post_id == result["id"]
        assert db.query(Post).count() == 1
    assert reservation_service.claim(URL) is None
