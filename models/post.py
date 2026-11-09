from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Text, Integer, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from models.media_asset import MediaAsset


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (Index("ux_posts_source_key", "source_key", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    title: Mapped[str] = mapped_column(String(255))

    topic: Mapped[str] = mapped_column(
        String(255),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="draft"
    )

    ru_content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    en_content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    quality_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    quality_approved: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    quality_issues: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    generation_source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
