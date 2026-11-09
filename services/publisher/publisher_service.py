"""Independent publication attempts, with no automatic retry or recovery send."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from sqlalchemy import Engine, inspect, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from services.analytics_service import AnalyticsService, sanitize_metadata
from services.publisher.factory import PublisherFactory, publisher_factory
from services.publisher.interface import PublisherInterface
from services.publisher.models import PublicationReference, PublishResult

logger = logging.getLogger(__name__)


class PublicationPersistenceError(RuntimeError):
    """The send must never be repeated; its database outcome needs reconciliation."""

    def __init__(self, content_id: int, result: PublishResult):
        super().__init__(f"Publication {content_id}: result persistence is unconfirmed; do not resend")
        self.content_id = content_id
        self.result = result


@dataclass(frozen=True)
class _Claim:
    reference: PublicationReference
    token: str
    language_code: str | None
    publisher: PublisherInterface | None
    preparation_error: PublishResult | None


class PublisherService:
    def __init__(
        self,
        db: Session | None = None,
        publisher: PublisherInterface | None = None,
        factory: PublisherFactory = publisher_factory,
        analytics_factory: Callable[..., AnalyticsService] = AnalyticsService,
        *,
        session_factory: Callable[[], Session] | None = None,
    ):
        self.db = db
        if session_factory is not None:
            self.sessions = session_factory
        elif db is not None:
            bind = db.get_bind()
            if not isinstance(bind, Engine):
                raise ValueError("Publisher requires an Engine, not a caller-owned Connection")
            self.sessions = sessionmaker(bind=bind, autoflush=False)
        else:
            self.sessions = SessionLocal
        self.publisher = publisher
        self.factory = factory
        self.analytics_factory = analytics_factory

    def _assert_caller_idle(self) -> None:
        if self.db is not None:
            if self.db.new or self.db.dirty or self.db.deleted:
                raise ValueError("Publisher cannot run with uncommitted caller changes")
            if self.db.in_transaction():
                # A flushed write is no longer in Session.dirty. Never discard it
                # by assuming an arbitrary caller transaction is read-only.
                raise ValueError("Publisher requires a caller session without an active transaction")

    @staticmethod
    def _safe_error(error: object) -> str:
        return str(sanitize_metadata(str(error)))[:1000]

    def _analytics(self, db: Session, reference: PublicationReference, language: str | None,
                   method: str, **kwargs) -> None:
        analytics = self.analytics_factory(db=db, commit=False)
        try:
            getattr(analytics, method)(
                reference.id, post_id=reference.post_id, channel_id=reference.channel_id,
                language_code=language, **kwargs,
            )
        finally:
            analytics.close()

    def _claim(self, content_id: int) -> _Claim | None:
        token = str(uuid4())
        with self.sessions() as db, db.begin():
            changed = db.execute(update(ChannelContent).where(
                ChannelContent.id == content_id, ChannelContent.status == "pending",
            ).values(status="publishing", claim_token=token,
                     claimed_at=datetime.now(timezone.utc))).rowcount
            if not changed:
                return None
            content = db.get(ChannelContent, content_id)
            reference = PublicationReference(content.id, content.post_id, content.channel_id)
            channel = db.get(Channel, content.channel_id)
            language = channel.language_code if channel else None
            publisher = None
            failure = None
            try:
                publisher = self.publisher or self.factory.create(db, content)
            except SQLAlchemyError:
                raise  # Database failure is not a provider rejection.
            except Exception as exc:
                failure = PublishResult(
                    success=False, outcome="failed", error_code="local_preparation",
                    error=self._safe_error(exc),
                )
            self._analytics(db, reference, language, "publication_attempted")
            return _Claim(reference, token, language, publisher, failure)

    @staticmethod
    def _normalize_result(result: PublishResult) -> PublishResult:
        if result.success and result.platform_post_id and result.outcome in (None, "published"):
            return result.model_copy(update={"outcome": "published"})
        if not result.success and result.outcome in ("failed", "unknown"):
            return result.model_copy(update={"error": PublisherService._safe_error(
                result.error or "Publisher returned an unsuccessful result",
            )})
        return PublishResult(
            success=False, outcome="unknown", error_code="publisher_invalid_result",
            error="Publisher did not provide a trustworthy delivery outcome",
        )

    def _write_result(self, claim: _Claim, result: PublishResult) -> bool:
        with self.sessions() as db, db.begin():
            changed = db.execute(update(ChannelContent).where(
                ChannelContent.id == claim.reference.id,
                ChannelContent.status == "publishing",
                ChannelContent.claim_token == claim.token,
            ).values(
                status=result.outcome,
                platform_post_id=result.platform_post_id if result.success else None,
                published_at=(result.published_at or datetime.now(timezone.utc)) if result.success else None,
                error_message=None if result.success else result.error,
                error_code=result.error_code, gateway_http_status=result.gateway_http_status,
                retry_after_at=result.retry_after_at,
            )).rowcount
            if not changed:
                current = db.get(ChannelContent, claim.reference.id)
                # A lost commit acknowledgement can leave the exact result already durable.
                return bool(current and current.claim_token == claim.token
                            and current.status == result.outcome
                            and current.platform_post_id == result.platform_post_id
                            and current.error_message == (None if result.success else result.error)
                            and current.error_code == result.error_code)
            if result.outcome != "unknown":
                self._analytics(
                    db, claim.reference, claim.language_code,
                    "publication_succeeded" if result.success else "publication_failed",
                    **({} if result.success else {"error_message": result.error}),
                )
            else:
                self._analytics(
                    db, claim.reference, claim.language_code, "publication_unknown",
                    metadata={"error_code": result.error_code, "error_message": result.error,
                              "gateway_http_status": result.gateway_http_status},
                )
            return True

    def _finish(self, claim: _Claim, result: PublishResult) -> PublishResult:
        # Retry only result persistence, never dispatch. Each iteration uses a fresh session.
        for attempt in range(2):
            try:
                if self._write_result(claim, result):
                    return result
                logger.warning(
                    "Stale publication result: id=%s claim_id=%s message_id=%s; no database changes",
                    claim.reference.id, claim.token, result.platform_post_id,
                )
                return PublishResult(
                    success=False, outcome="unknown", error_code="stale_claim",
                    error="Publication claim changed; result was not applied",
                )
            except Exception:
                if attempt:
                    logger.error(
                        "Publication result persistence unconfirmed: id=%s claim_id=%s message_id=%s; do not resend",
                        claim.reference.id, claim.token, result.platform_post_id,
                    )
                    raise PublicationPersistenceError(claim.reference.id, result) from None
        raise AssertionError("unreachable")

    def _publish_one(self, content_id: int) -> PublishResult:
        claim = self._claim(content_id)
        if claim is None:
            return PublishResult(success=False, error="Publication is not pending", error_code="not_pending")
        # No ORM objects, live sessions or database connections cross this boundary.
        if claim.preparation_error is not None:
            result = claim.preparation_error
        else:
            try:
                result = self._normalize_result(claim.publisher.publish(claim.reference))
            except Exception:
                result = PublishResult(
                    success=False, outcome="unknown", error_code="publisher_exception",
                    error="Publisher failed after dispatch began; delivery outcome is unknown",
                )
        return self._finish(claim, result)

    def publish(self, content: ChannelContent | PublicationReference) -> PublishResult:
        identity = inspect(content).identity if isinstance(content, ChannelContent) else (content.id,)
        content_id = identity[0] if identity else None
        self._assert_caller_idle()
        if content_id is None:
            raise ValueError("ChannelContent must be persisted before publication")
        return self._publish_one(content_id)

    def publish_pending(self) -> list[PublishResult]:
        return self._publish_pending()

    def publish_pending_for_posts(self, post_ids: Iterable[int]) -> list[PublishResult]:
        ids = list(dict.fromkeys(post_ids))
        return self._publish_pending(ids) if ids else []

    def _publish_pending(self, post_ids: list[int] | None = None) -> list[PublishResult]:
        self._assert_caller_idle()
        with self.sessions() as db:
            query = db.query(ChannelContent.id).filter(ChannelContent.status == "pending")
            if post_ids is not None:
                query = query.filter(ChannelContent.post_id.in_(post_ids))
            ids = [row[0] for row in query.order_by(ChannelContent.id).all()]
        results = []
        for content_id in ids:
            result = self._publish_one(content_id)
            if result.error_code != "not_pending":
                results.append(result)
        return results

    def inspect(self, content_id: int) -> dict:
        self._assert_caller_idle()
        with self.sessions() as db:
            row = db.get(ChannelContent, content_id)
            if row is None:
                raise ValueError("Publication not found")
            values = {field: getattr(row, field) for field in (
                "id", "post_id", "channel_id", "status", "claim_token", "claimed_at",
                "platform_post_id", "published_at", "error_code", "error_message",
                "gateway_http_status", "retry_after_at",
            )}
            for name in ("claimed_at", "published_at", "retry_after_at"):
                value = values[name]
                if value is not None and value.tzinfo is None:
                    values[name] = value.replace(tzinfo=timezone.utc)
            return values

    def reconcile(self, content_id: int, *, expected_status: str,
                  expected_claim_token: str | None, outcome: str, operator: str,
                  reason: str, confirm_no_inflight: bool = False,
                  message_id: int | None = None) -> dict:
        """Resolve one explicit ID using evidence; this method can never dispatch."""
        if expected_status not in {"publishing", "unknown"} or outcome not in {"published", "failed", "unknown"}:
            raise ValueError("Only unresolved publications can be reconciled")
        if not confirm_no_inflight or not operator.strip() or not reason.strip():
            raise ValueError("Operator, evidence and confirmation of no in-flight work are required")
        if outcome == "published" and (type(message_id) is not int or message_id <= 0):
            raise ValueError("A confirmed positive Telegram message_id is required")
        if outcome != "published" and message_id is not None:
            raise ValueError("message_id is only valid for a confirmed publication")
        self._assert_caller_idle()
        with self.sessions() as db, db.begin():
            row = db.get(ChannelContent, content_id)
            if row is None:
                raise ValueError("Publication not found")
            reference = PublicationReference(row.id, row.post_id, row.channel_id)
            channel = db.get(Channel, row.channel_id)
            language = channel.language_code if channel else None
            changed = db.execute(update(ChannelContent).where(
                ChannelContent.id == content_id, ChannelContent.status == expected_status,
                ChannelContent.claim_token == expected_claim_token,
            ).values(
                status=outcome, claim_token=None,
                platform_post_id=str(message_id) if outcome == "published" else None,
                published_at=datetime.now(timezone.utc) if outcome == "published" else None,
                error_code=None if outcome == "published" else "manually_reconciled",
                error_message=None if outcome == "published" else self._safe_error(reason),
            )).rowcount
            if not changed:
                raise ValueError("Publication changed; inspect it again before reconciliation")
            if outcome != "unknown":
                self._analytics(db, reference, language,
                                "publication_succeeded" if outcome == "published" else "publication_failed",
                                **({} if outcome == "published" else {"error_message": self._safe_error(reason)}))
            else:
                self._analytics(db, reference, language, "publication_unknown",
                                metadata={"error_code": "manually_reconciled", "reason": reason})
            self._analytics(
                db, reference, language, "publication_reconciled",
                metadata={"operator": operator, "reason": reason,
                          "previous_status": expected_status, "outcome": outcome},
            )
        return self.inspect(content_id)
