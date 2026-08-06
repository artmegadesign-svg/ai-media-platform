import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from models.channel import Channel
from models.channel_content import ChannelContent
from services.analytics_service import AnalyticsService
from services.publisher.factory import PublisherFactory, publisher_factory
from services.publisher.interface import PublisherInterface
from services.publisher.models import PublishResult

logger = logging.getLogger(__name__)


class PublisherService:
    def __init__(
        self, db: Session, publisher: PublisherInterface | None = None,
        factory: PublisherFactory = publisher_factory,
        analytics_factory: Callable[[], AnalyticsService] = AnalyticsService,
    ):
        self.db = db
        self.publisher = publisher
        self.factory = factory
        self.analytics_factory = analytics_factory

    def _analytics(self, method: str, content: ChannelContent, **kwargs) -> None:
        analytics = self.analytics_factory()
        try:
            channel = self.db.get(Channel, content.channel_id) if hasattr(self.db, "get") else None
            getattr(analytics, method)(content, channel=channel, **kwargs)
        except Exception:
            logger.exception("Analytics event %s failed for publication %s", method, content.id)
        finally:
            analytics.close()

    def _claim(self, content_id: int) -> ChannelContent | None:
        changed = self.db.execute(
            update(ChannelContent)
            .where(ChannelContent.id == content_id, ChannelContent.status == "pending")
            .values(status="publishing")
        ).rowcount
        self.db.commit()
        return self.db.get(ChannelContent, content_id) if changed else None

    def publish(self, content: ChannelContent) -> PublishResult:
        claimed = content
        if content.id is not None and hasattr(self.db, "execute"):
            claimed = self._claim(content.id)
            if claimed is None:
                return PublishResult(success=False, error="Publication is not pending")
        else:
            content.status = "publishing"
            self.db.commit()
        if hasattr(self.db, "get"):
            self._analytics("publication_attempted", claimed)
        publisher = self.publisher or self.factory.create(self.db, claimed)
        result = publisher.publish(claimed)
        self._apply_result(claimed, result)
        self.db.commit()
        self.db.refresh(claimed)
        if hasattr(self.db, "get"):
            self._analytics(
                "publication_succeeded" if result.success else "publication_failed",
                claimed,
                **({} if result.success else {"error_message": result.error}),
            )
        return result

    @staticmethod
    def _apply_result(content: ChannelContent, result: PublishResult) -> None:
        if result.success:
            content.status = "published"
            content.platform_post_id = result.platform_post_id
            content.published_at = result.published_at or datetime.now(timezone.utc)
            content.error_message = None
        else:
            content.status = "failed"
            content.error_message = result.error

    def publish_pending(self) -> list[PublishResult]:
        ids = [row[0] for row in self.db.query(ChannelContent.id).filter(ChannelContent.status == "pending").all()]
        claimed_ids = [
            content_id for content_id in ids
            if self.db.execute(
                update(ChannelContent)
                .where(ChannelContent.id == content_id, ChannelContent.status == "pending")
                .values(status="publishing")
            ).rowcount
        ]
        self.db.commit()
        contents = self.db.query(ChannelContent).filter(ChannelContent.id.in_(claimed_ids)).order_by(ChannelContent.id).all()
        for content in contents:
            self._analytics("publication_attempted", content)
        completed = []
        for content in contents:
            result = self.factory.create(self.db, content).publish(content)
            self._apply_result(content, result)
            completed.append((content, result))
        self.db.commit()
        for content, result in completed:
            self._analytics(
                "publication_succeeded" if result.success else "publication_failed",
                content,
                **({} if result.success else {"error_message": result.error}),
            )
        return [result for _, result in completed]
