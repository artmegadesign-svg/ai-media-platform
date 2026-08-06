from datetime import datetime, timedelta
from uuid import uuid4

from app.routes.analytics import publications, summary
from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from models.metric import Metric
from models.post import Post
from services.analytics_service import AnalyticsService, sanitize_metadata


def domain_objects(db):
    suffix = uuid4().hex
    post = Post(title="T", topic="T", ru_content="RU", en_content="EN")
    ru = Channel(name=f"analytics-ru-{suffix}", platform="web", language_code="ru")
    en = Channel(name=f"analytics-en-{suffix}", platform="web", language_code="en")
    db.add_all([post, ru, en])
    db.flush()
    contents = [
        ChannelContent(post_id=post.id, channel_id=ru.id, status="pending"),
        ChannelContent(post_id=post.id, channel_id=en.id, status="pending"),
    ]
    db.add_all(contents)
    db.commit()
    return post, ru, en, contents


def test_all_events_are_idempotent_and_languages_independent():
    db = SessionLocal()
    try:
        post, ru, en, contents = domain_objects(db)
        analytics = AnalyticsService(db)
        first = analytics.post_generated(post)
        assert analytics.post_generated(post).id == first.id
        analytics.publication_attempted(contents[0], channel=ru)
        analytics.publication_succeeded(contents[0], channel=ru)
        analytics.publication_attempted(contents[1], channel=en)
        analytics.publication_failed(contents[1], channel=en, error_message="boom")
        assert db.query(Metric).count() == 5
        assert {row.language_code for row in db.query(Metric).filter(Metric.publication_id.is_not(None))} == {"ru", "en"}
    finally:
        db.close()


def test_secret_sanitizer_is_recursive_and_truncates():
    cleaned = sanitize_metadata({
        "nested": {"api-key": "value", "safe": "Bearer abc"},
        "message": "password=hunter2 " + "x" * 1200,
    })
    assert cleaned["nested"] == {"api-key": "[REDACTED]", "safe": "[REDACTED]"}
    assert "hunter2" not in cleaned["message"]
    assert len(cleaned["message"]) == 1000


def test_summary_filters_zero_rate_and_publication_pagination():
    db = SessionLocal()
    try:
        post, ru, en, contents = domain_objects(db)
        analytics = AnalyticsService(db)
        analytics.post_generated(post)
        analytics.publication_attempted(contents[0], channel=ru)
        analytics.publication_succeeded(contents[0], channel=ru)
        analytics.publication_attempted(contents[1], channel=en)
        analytics.publication_failed(contents[1], channel=en)
        data = summary(language_code="ru", channel_id=ru.id, db=db)
        assert data["total_publication_attempts"] == 1
        assert data["successful_publications"] == 1
        assert data["success_rate"] == 1.0
        empty = summary(date_from=datetime.now() + timedelta(days=1), db=db)
        assert empty["success_rate"] == 0.0
        page = publications(status="failed", limit=1, offset=0, db=db)
        assert len(page) == 1
        assert page[0]["language_code"] == "en"
        assert page[0]["status"] == "failed"
    finally:
        db.close()
