from datetime import datetime

from models.channel_content import ChannelContent

from services.publisher.publisher_service import PublisherService
from services.publisher.adapters.mock import MockPublisher


class FakeSession:

    def commit(self):
        pass

    def refresh(self, obj):
        pass


def test_mock_publish():

    content = ChannelContent(
        channel_id=1,
        post_id=1,
        status="pending",
    )

    service = PublisherService(
        db=FakeSession(),
        publisher=MockPublisher(),
    )

    result = service.publish(content)

    assert result.success is True
    assert content.status == "published"
    assert content.platform_post_id.startswith("mock_")
    assert isinstance(content.published_at, datetime)
