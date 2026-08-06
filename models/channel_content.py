from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ChannelContent(Base):
    __tablename__ = "channel_contents"

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

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )
