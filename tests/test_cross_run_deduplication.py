import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

import test_quality_issues_persistence as quality_fixtures
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.media_asset import MediaAsset
from models.metric import Metric
from models.post import Post
from repositories.channel_content_repository import ChannelContentRepository
from services.ai_engine.pipeline.content_pipeline import ContentPipeline
from services.ai_engine.services.generator_service import GeneratorService
from services.ai_engine.services.post_service import PostService
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService
from services.editorial.models import EditorialDecision
from services.intelligence.content_generation_service import IntelligenceContentGenerationService
from services.intelligence.models import IntelligenceResult
from services.news.models import NewsItem
from services.news.normalizer import source_identity
from services.orchestration.mvp_cycle import _created_post_ids, run_mvp_cycle


quality_sessions = quality_fixtures.quality_sessions


def _counts(sessions):
    with sessions() as db:
        return [db.query(m).count() for m in (Post, ContentVariant, ChannelContent, MediaAsset, Metric)]


def _approved(url="https://openai.com/story", title="OpenAI releases GPT-5"):
    news = NewsItem(source="OpenAI", title=title, url=url)
    return IntelligenceResult(
        news=news, trend=None,
        editorial=EditorialDecision(news.id, True, "normal", "breaking", "fixture", 74),
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("Duplicate must not execute downstream work")


@pytest.mark.parametrize("url", [
    "https://OPENAI.com/story/?utm_source=x#section", "https://openai.com/story",
])
def test_duplicate_before_ai_and_media_leaves_backlog_untouched(quality_sessions, monkeypatch, url):
    first = PostService().save("original", "RU", "EN", source_url="https://openai.com/story")
    with quality_sessions() as db:
        rows = db.query(ChannelContent).order_by(ChannelContent.id).all()
        rows[0].status = "pending"
        rows[1].status = "failed"
        db.commit()
    before = _counts(quality_sessions)
    monkeypatch.setattr(AIWriterService, "generate_ru", _forbidden)
    monkeypatch.setattr(AITranslatorService, "ru_to_en", _forbidden)
    service = IntelligenceContentGenerationService(planning_service_factory=_forbidden)

    result = service.generate([_approved(url=url, title="Updated article")])[0]

    assert result["status"] == "duplicate"
    assert result["post_created"] is False
    assert result["existing_post_id"] == first["id"]
    assert result["id"] is result["post_id"] is None
    assert _created_post_ids([result]) == []
    assert _counts(quality_sessions) == before
    with quality_sessions() as db:
        assert [r.status for r in db.query(ChannelContent).order_by(ChannelContent.id)] == ["pending", "failed"]


def test_processed_sources_are_removed_before_both_limits(quality_sessions, monkeypatch):
    for number in range(11):
        PostService().save(f"old {number}", "RU", "EN", source_url=f"https://openai.com/old-{number}")
    from services.news.service import NewsService
    from services.intelligence.service import IntelligenceService
    from services.trends.service import TrendService
    from services.editorial.service import EditorialService
    from services.news.scorer import NewsScorer
    import services.trends.scorer as trend_scorer

    now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(trend_scorer, "_utc_now", lambda: now)
    items = [NewsItem(
        source="OpenAI", title=f"OpenAI releases GPT-{n + 10}",
        url=f"https://openai.com/old-{n}", published_at=now,
    ) for n in range(11)]
    new = NewsItem(source="OpenAI", title="OpenAI releases GPT-5.1",
                   url="https://openai.com/new", published_at=now)
    items.append(new)

    class Collector:
        def collect(self):
            return items

    class Content:
        def generate(self, approved):
            assert [item.news.id for item in approved] == [new.id]
            return [{"status": "rejected", "post_id": None}]

    news = NewsService(collectors=[Collector()], scorer=NewsScorer(now), limit=1)
    intelligence = IntelligenceService(news, TrendService(), EditorialService())
    result = run_mvp_cycle(
        news_service=news, intelligence_service=intelligence, content_service=Content(),
        publisher_agent_factory=_forbidden,
    )
    assert result["collected_count"] == 12
    assert result["approved_count"] == 1
    assert result["post_ids"] == []


def test_all_processed_does_not_initialize_content_or_publisher(quality_sessions, monkeypatch):
    PostService().save("old", "RU", "EN", source_url="https://openai.com/story")
    from services.news.service import NewsService

    class Collector:
        def collect(self):
            return [_approved().news]

    monkeypatch.setattr("services.orchestration.mvp_cycle.create_intelligence_content_generation_service", _forbidden)
    result = run_mvp_cycle(news_service=NewsService(collectors=[Collector()]),
                           publisher_agent_factory=_forbidden)
    assert result["approved_count"] == 0
    assert result["content_results"] == result["publication_results"] == []


def test_manual_generation_and_legacy_post_do_not_gain_source_keys(quality_sessions, monkeypatch):
    ru = "Проверенная новость\n\n" + "Компания выпустила модель и сообщила условия её использования. " * 12
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda *_: ru)
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda *_: "Verified news\n\n" + "The company released a model and described its available features. " * 12)
    first = GeneratorService().generate("same topic")
    second = GeneratorService().generate("same topic")
    source = GeneratorService().generate("same topic", source_url="https://openai.com/story")
    assert len({first["id"], second["id"], source["id"]}) == 3
    with quality_sessions() as db:
        posts = db.query(Post).order_by(Post.id).all()
        assert [(p.source_key, p.source_url) for p in posts[:2]] == [(None, None)] * 2
        assert posts[2].source_key == source_identity("https://openai.com/story")[1]


def test_rejected_source_is_not_recorded(quality_sessions, monkeypatch):
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda *_: "bad")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda *_: "Verified news\n\n" + "The company released a model and described its available features. " * 12)
    result = ContentPipeline().generate_full_content("Rejected", source_url="https://openai.com/rejected")
    assert result["status"] == "rejected"
    assert isinstance(result["quality_issues"], list)
    assert _counts(quality_sessions) == [0, 0, 0, 0, 0]


def test_two_simultaneous_saves_leave_one_post_and_one_job_set(quality_sessions):
    engine = quality_sessions.kw["bind"]
    barrier = Barrier(2)

    def synchronize(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO posts "):
            barrier.wait(timeout=15)

    event.listen(engine, "before_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: PostService().save(
                "race", "RU", "EN", source_url="https://openai.com/race",
            ), range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize)
    assert sorted(r["post_created"] for r in results) == [False, True]
    winner = next(r for r in results if r["post_created"])
    loser = next(r for r in results if not r["post_created"])
    assert loser["existing_post_id"] == winner["id"]
    assert loser["id"] is None
    assert _counts(quality_sessions) == [1, 2, 2, 0, 1]
    assert PostService().save("manual after rollback", "RU", "EN")["post_created"]


def test_unrelated_unique_failure_rolls_back_whole_post(quality_sessions):
    engine = quality_sessions.kw["bind"]
    with engine.begin() as db:
        db.execute(text("CREATE UNIQUE INDEX ux_test_variant_language ON content_variants(language_code)"))
    PostService().save("first", "RU", "EN", source_url="https://openai.com/first")
    with pytest.raises(IntegrityError):
        PostService().save("second", "RU", "EN", source_url="https://openai.com/second")
    assert _counts(quality_sessions) == [1, 2, 2, 0, 1]
    assert PostService().find_by_source_key(source_identity("https://openai.com/second")[1]) is None


def test_not_null_failure_is_not_a_duplicate(quality_sessions):
    with pytest.raises(IntegrityError):
        PostService().save("bad", None, "EN", source_url="https://openai.com/bad")
    assert _counts(quality_sessions) == [0, 0, 0, 0, 0]


def test_channel_pair_is_idempotent_including_a_race(quality_sessions):
    post = PostService().save("post", "RU", "EN")
    with quality_sessions() as db:
        channel = Channel(name="Race channel", platform="web", language_code="en")
        db.add(channel)
        db.commit()
        channel_id = channel.id
    engine = quality_sessions.kw["bind"]
    barrier = Barrier(2)

    def synchronize(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO channel_contents "):
            barrier.wait(timeout=15)

    def create(_):
        with quality_sessions() as db:
            row = ChannelContentRepository(db).create(ChannelContent(
                post_id=post["id"], channel_id=channel_id, status="published", platform_post_id="existing",
            ))
            return row.id

    event.listen(engine, "before_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(create, range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize)
    assert ids[0] == ids[1]
    with quality_sessions() as db:
        row = ChannelContentRepository(db).create(ChannelContent(
            post_id=post["id"], channel_id=channel_id, status="pending", platform_post_id="replacement",
        ))
        assert (row.id, row.status, row.platform_post_id) == (ids[0], "published", "existing")
        assert db.query(ChannelContent).count() == 3


def test_replay_in_two_fresh_processes(quality_sessions):
    engine = quality_sessions.kw["bind"]
    url = engine.url
    if url.get_backend_name() == "postgresql":
        with engine.connect() as db:
            schema = db.execute(text("select current_schema()")).scalar()
        url = url.set(query={"host": os.environ["AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR"],
                             "options": f"-csearch_path={schema}"})
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(DATABASE_URL=url.render_as_string(hide_password=False), PYTHONDONTWRITEBYTECODE="1")
    code = r'''
import json, socket
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.dotenv_values = lambda *a, **k: {}
def blocked(*a, **k): raise AssertionError("External network disabled")
socket.socket.connect = blocked
socket.create_connection = blocked
from db.session import SessionLocal
from models.post import Post
from models.channel_content import ChannelContent
from services.news.models import NewsItem
from services.news.service import NewsService
from services.news.scorer import NewsScorer
from services.orchestration.mvp_cycle import run_mvp_cycle
from services.intelligence.content_generation_service import IntelligenceContentGenerationService
from services.publisher.publisher_service import PublisherService
from services.publisher.models import PublishResult
import services.trends.scorer as trend_scorer
now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
trend_scorer._utc_now = lambda: now
class Collector:
    def collect(self):
        return [NewsItem(source="OpenAI", title="OpenAI releases GPT-5.1", url="https://openai.com/replay/?utm_source=feed", published_at=now)]
calls = []
class Publisher:
    def publish(self, content):
        calls.append(content.id)
        return PublishResult(success=True, platform_post_id="mock")
class Factory:
    def create(self, db, content): return Publisher()
def agent(db):
    return SimpleNamespace(run_for_posts=PublisherService(db, factory=Factory()).publish_pending_for_posts)
ru = "Проверенная новость\n\n" + "Компания выпустила модель и сообщила условия её использования. " * 12
with patch("services.ai_engine.services.writer_service.AIWriterService.generate_ru", return_value=ru) as writer, patch("services.ai_engine.services.translator_service.AITranslatorService.ru_to_en", return_value="Verified news\n\n" + "The company released a model and described its available features. " * 12):
    result = run_mvp_cycle(news_service=NewsService(collectors=[Collector()], scorer=NewsScorer(now)), content_service=IntelligenceContentGenerationService(), publisher_agent_factory=agent)
    with SessionLocal() as db:
        print(json.dumps({"writer": writer.call_count, "sent": len(calls), "posts": db.query(Post).count(), "jobs": db.query(ChannelContent).count(), "post_ids": result["post_ids"]}))
'''
    outputs = [json.loads(subprocess.check_output([sys.executable, "-B", "-c", code], env=env, text=True)) for _ in range(2)]
    assert outputs[0] == {"writer": 1, "sent": 2, "posts": 1, "jobs": 2, "post_ids": [1]}
    assert outputs[1] == {"writer": 0, "sent": 0, "posts": 1, "jobs": 2, "post_ids": []}
