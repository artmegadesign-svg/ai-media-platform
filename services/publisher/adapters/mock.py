from datetime import datetime, timezone

from models.channel_content import ChannelContent

from services.publisher.interface import PublisherInterface
from services.publisher.models import PublishResult


class MockPublisher(PublisherInterface):

    def publish(
        self,
        content: ChannelContent,
    ) -> PublishResult:

        content_id = getattr(content, "id", None)

        return PublishResult(
            success=True,
            platform_post_id=f"mock_{content_id or content.post_id}",
            published_at=datetime.now(timezone.utc),
        )
