from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ChannelContent(Base):
    __tablename__ = "channel_contents"
    __table_args__ = (
        Index("ux_channel_contents_post_channel", "post_id", "channel_id", unique=True),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"),
        index=True
    )

    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id"),
        index=True
    )

    platform_post_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="pending"
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_http_status: Mapped[int | None] = mapped_column(nullable=True)
    retry_after_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )
