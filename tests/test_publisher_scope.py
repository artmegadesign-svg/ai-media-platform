from models.channel import Channel
from models.channel_content import ChannelContent
from models.post import Post
from services.publisher.models import PublishResult
from services.publisher.publisher_service import PublisherService


class RecordingPublisher:
    def __init__(self, published_ids):
        self.published_ids = published_ids

    def publish(self, content):
        self.published_ids.append(content.id)
        return PublishResult(success=True, platform_post_id=f"mock_{content.id}")


class RecordingFactory:
    def __init__(self, published_ids):
        self.published_ids = published_ids

    def create(self, db, content):
        return RecordingPublisher(self.published_ids)


class NoOpAnalytics:
    def publication_attempted(self, *args, **kwargs):
        pass

    def publication_succeeded(self, *args, **kwargs):
        pass

    def publication_failed(self, *args, **kwargs):
        pass

    def close(self):
        pass


def _post(topic):
    return Post(
        title=topic,
        topic=topic,
        status="published",
        ru_content="RU",
        en_content="EN",
    )


def test_publish_pending_for_posts_leaves_older_pending_content_untouched(isolated_db):
    db = isolated_db
    channel = Channel(
        name="Scoped publisher test",
        platform="web",
        language_code="en",
        is_active=True,
    )
    old_post = _post("old pending post")
    current_post = _post("current cycle post")
    db.add_all([channel, old_post, current_post])
    db.flush()

    old_pending = ChannelContent(
        channel_id=channel.id,
        post_id=old_post.id,
        status="pending",
    )
    current_pending = ChannelContent(
        channel_id=channel.id,
        post_id=current_post.id,
        status="pending",
    )
    db.add_all([old_pending, current_pending])
    db.commit()
    old_id = old_pending.id
    current_id = current_pending.id
    current_post_id = current_post.id

    published_ids = []
    results = PublisherService(
        db,
        factory=RecordingFactory(published_ids),
        analytics_factory=NoOpAnalytics,
    ).publish_pending_for_posts([current_post_id])

    db.expire_all()
    assert len(results) == 1
    assert published_ids == [current_id]
    assert db.get(ChannelContent, current_id).status == "published"
    assert db.get(ChannelContent, old_id).status == "pending"

def test_publish_pending_for_posts_with_empty_scope_does_nothing(isolated_db):
    db = isolated_db
    published_ids = []
    result = PublisherService(
        db,
        factory=RecordingFactory(published_ids),
        analytics_factory=NoOpAnalytics,
    ).publish_pending_for_posts([])

    assert result == []
    assert published_ids == []
