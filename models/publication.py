from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True)

    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id"),
        index=True
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"),
        index=True
    )

    platform: Mapped[str] = mapped_column(
        String(50),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="pending"
    )

    external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )
