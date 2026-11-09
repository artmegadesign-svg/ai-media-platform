from datetime import datetime, timezone

from services.publisher.interface import PublisherInterface
from services.publisher.models import PublicationReference, PublishResult


class MockPublisher(PublisherInterface):

    def publish(
        self,
        content: PublicationReference,
    ) -> PublishResult:

        content_id = getattr(content, "id", None)

        return PublishResult(
            success=True,
            platform_post_id=f"mock_{content_id or content.post_id}",
            published_at=datetime.now(timezone.utc),
        )
