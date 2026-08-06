from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        Index("ix_metrics_event_type_occurred_at", "event_type", "occurred_at"),
        Index("ix_metrics_language_occurred_at", "language_code", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), index=True)
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_contents.id"), index=True
    )
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    language_code: Mapped[str | None] = mapped_column(String(10), index=True)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    post = relationship("Post")
    publication = relationship("ChannelContent")
    channel = relationship("Channel")
    asset = relationship("Asset")
