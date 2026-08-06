import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from models.metric import Metric
from models.post import Post


EVENT_POST_GENERATED = "post_generated"
EVENT_PUBLICATION_ATTEMPTED = "publication_attempted"
EVENT_PUBLICATION_SUCCEEDED = "publication_succeeded"
EVENT_PUBLICATION_FAILED = "publication_failed"
_SECRET_KEY = re.compile(r"token|secret|password|authorization|api[_-]key", re.I)
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(token|secret|password|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)


def sanitize_metadata(value: Any, key: str | None = None) -> Any:
    if key and _SECRET_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize_metadata(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        value = _BEARER.sub("[REDACTED]", value)
        value = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
        return value[:1000]
    return value


class AnalyticsService:
    """Records internal domain outcomes; it has no transport/provider dependency."""

    def __init__(self, db: Session | None = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def _record(self, *, event_key: str, event_type: str, **values: Any) -> Metric:
        existing = self.db.query(Metric).filter(Metric.event_key == event_key).first()
        if existing:
            return existing
        metric = Metric(
            event_key=event_key,
            event_type=event_type,
            occurred_at=values.pop("occurred_at", None)
            or datetime.now(timezone.utc).replace(tzinfo=None),
            metadata_=sanitize_metadata(values.pop("metadata", None)),
            **values,
        )
        self.db.add(metric)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.db.query(Metric).filter(Metric.event_key == event_key).one()
        self.db.refresh(metric)
        return metric

    def post_generated(self, post: Post | int, metadata: dict | None = None) -> Metric:
        post_id = post.id if isinstance(post, Post) else post
        return self._record(
            event_key=f"post:{post_id}:generated",
            event_type=EVENT_POST_GENERATED,
            post_id=post_id,
            metadata=metadata,
        )

    def publication_attempted(
        self, publication: ChannelContent | int, *, channel: Channel | None = None,
        post_id: int | None = None, channel_id: int | None = None,
        language_code: str | None = None, metadata: dict | None = None,
    ) -> Metric:
        return self._publication_event(
            publication, "attempted", EVENT_PUBLICATION_ATTEMPTED,
            channel, post_id, channel_id, language_code, metadata,
        )

    def publication_succeeded(self, publication: ChannelContent | int, **kwargs: Any) -> Metric:
        return self._publication_event(
            publication, "result", EVENT_PUBLICATION_SUCCEEDED,
            kwargs.pop("channel", None), kwargs.pop("post_id", None),
            kwargs.pop("channel_id", None), kwargs.pop("language_code", None),
            kwargs.pop("metadata", None),
        )

    def publication_failed(
        self, publication: ChannelContent | int, *, error_message: str | None = None,
        **kwargs: Any,
    ) -> Metric:
        metadata = dict(kwargs.pop("metadata", None) or {})
        if error_message:
            metadata["error_message"] = error_message
        return self._publication_event(
            publication, "result", EVENT_PUBLICATION_FAILED,
            kwargs.pop("channel", None), kwargs.pop("post_id", None),
            kwargs.pop("channel_id", None), kwargs.pop("language_code", None), metadata,
        )

    def _publication_event(
        self, publication: ChannelContent | int, suffix: str, event_type: str,
        channel: Channel | None, post_id: int | None, channel_id: int | None,
        language_code: str | None, metadata: dict | None,
    ) -> Metric:
        publication_id = publication.id if isinstance(publication, ChannelContent) else publication
        if isinstance(publication, ChannelContent):
            post_id = publication.post_id
            channel_id = publication.channel_id
        if channel:
            channel_id = channel.id
            language_code = channel.language_code
        return self._record(
            event_key=f"publication:{publication_id}:{suffix}", event_type=event_type,
            publication_id=publication_id, post_id=post_id, channel_id=channel_id,
            language_code=language_code, metadata=metadata,
        )
