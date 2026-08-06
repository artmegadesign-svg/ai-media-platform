import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from models.channel import Channel
from models.channel_content import ChannelContent
from services.analytics_service import AnalyticsService, sanitize_metadata
from services.publisher.factory import PublisherFactory, publisher_factory
from services.publisher.interface import PublisherInterface
from services.publisher.models import PublishResult

logger = logging.getLogger(__name__)


class PublisherService:
    def __init__(
        self,
        db: Session,
        publisher: PublisherInterface | None = None,
        factory: PublisherFactory = publisher_factory,
        analytics_factory: Callable[[], AnalyticsService] = AnalyticsService,
    ):
        self.db = db
        self.publisher = publisher
        self.factory = factory
        self.analytics_factory = analytics_factory

    @staticmethod
    def _safe_error(error: object) -> str:
        sanitized = sanitize_metadata(str(error))
        return str(sanitized)[:1000]

    def _analytics(self, method: str, content: ChannelContent, **kwargs) -> None:
        analytics = None
        try:
            analytics = self.analytics_factory()
            channel = (
                self.db.get(Channel, content.channel_id)
                if hasattr(self.db, "get")
                else None
            )
            getattr(analytics, method)(content, channel=channel, **kwargs)
        except Exception:
            logger.exception(
                "Analytics event %s failed for publication %s", method, content.id
            )
        finally:
            if analytics is not None:
                try:
                    analytics.close()
                except Exception:
                    logger.exception(
                        "Analytics close failed for publication %s", content.id
                    )

    def _claim(self, content_id: int) -> ChannelContent | None:
        changed = self.db.execute(
            update(ChannelContent)
            .where(
                ChannelContent.id == content_id,
                ChannelContent.status == "pending",
            )
            .values(status="publishing")
        ).rowcount
        self.db.commit()
        return self.db.get(ChannelContent, content_id) if changed else None

    def _publisher_for(self, content: ChannelContent) -> PublisherInterface:
        return self.publisher or self.factory.create(self.db, content)

    def _publish_safely(self, content: ChannelContent) -> PublishResult:
        try:
            publisher = self._publisher_for(content)
            # End any read transaction opened by factory lookups before the external call.
            self.db.commit()
            return publisher.publish(content)
        except Exception as exc:
            logger.exception("Publisher failed for publication %s", content.id)
            self.db.rollback()
            return PublishResult(success=False, error=self._safe_error(exc))

    def publish(self, content: ChannelContent) -> PublishResult:
        claimed = content
        if content.id is not None and hasattr(self.db, "execute"):
            claimed = self._claim(content.id)
            if claimed is None:
                return PublishResult(
                    success=False,
                    error="Publication is not pending",
                )
        else:
            content.status = "publishing"
            self.db.commit()

        if hasattr(self.db, "get"):
            self._analytics("publication_attempted", claimed)

        result = self._publish_safely(claimed)
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
            content.error_message = PublisherService._safe_error(
                result.error or "Publisher returned an unsuccessful result"
            )

    def publish_pending(self) -> list[PublishResult]:
        ids = [
            row[0]
            for row in self.db.query(ChannelContent.id)
            .filter(ChannelContent.status == "pending")
            .all()
        ]
        claimed_ids = [
            content_id
            for content_id in ids
            if self.db.execute(
                update(ChannelContent)
                .where(
                    ChannelContent.id == content_id,
                    ChannelContent.status == "pending",
                )
                .values(status="publishing")
            ).rowcount
        ]
        self.db.commit()

        if not claimed_ids:
            return []

        contents = (
            self.db.query(ChannelContent)
            .filter(ChannelContent.id.in_(claimed_ids))
            .order_by(ChannelContent.id)
            .all()
        )

        for content in contents:
            self._analytics("publication_attempted", content)

        prepared: list[tuple[ChannelContent, PublisherInterface | None, PublishResult | None]] = []
        for content in contents:
            try:
                prepared.append((content, self.factory.create(self.db, content), None))
            except Exception as exc:
                logger.exception(
                    "Publisher factory failed for publication %s", content.id
                )
                prepared.append(
                    (
                        content,
                        None,
                        PublishResult(success=False, error=self._safe_error(exc)),
                    )
                )

        # Factory lookups are complete; do not hold an open DB transaction during I/O.
        self.db.commit()

        completed: list[tuple[ChannelContent, PublishResult]] = []
        for content, publisher, failure in prepared:
            if failure is not None:
                result = failure
            else:
                try:
                    result = publisher.publish(content)  # type: ignore[union-attr]
                except Exception as exc:
                    logger.exception("Publisher failed for publication %s", content.id)
                    result = PublishResult(
                        success=False,
                        error=self._safe_error(exc),
                    )
            self._apply_result(content, result)
            completed.append((content, result))

        # Persist every independent RU/EN result together. No item remains publishing.
        self.db.commit()

        for content, result in completed:
            self._analytics(
                "publication_succeeded" if result.success else "publication_failed",
                content,
                **({} if result.success else {"error_message": result.error}),
            )

        return [result for _, result in completed]
