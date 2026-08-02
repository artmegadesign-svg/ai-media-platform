from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.channel_content import ChannelContent
from services.publisher.interface import PublisherInterface
from services.publisher.models import PublishResult


class PublisherService:

    def __init__(
        self,
        db: Session,
        publisher: PublisherInterface,
    ):
        self.db = db
        self.publisher = publisher

    def publish(
        self,
        content: ChannelContent,
    ) -> PublishResult:

        result = self.publisher.publish(content)

        if result.success:
            content.status = "published"
            content.platform_post_id = result.platform_post_id
            content.published_at = (
                result.published_at
                or datetime.now(timezone.utc)
            )
        else:
            content.status = "failed"

        self.db.commit()
        self.db.refresh(content)

        return result

    def publish_pending(self):

        contents = (
            self.db.query(ChannelContent)
            .filter(ChannelContent.status == "pending")
            .all()
        )

        results = []

        for content in contents:
            results.append(
                self.publish(content)
            )

        return results
