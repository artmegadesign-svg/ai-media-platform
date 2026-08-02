from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base


class ContentVariant(Base):
    __tablename__ = "content_variants"

    id: Mapped[int] = mapped_column(primary_key=True)

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)

    language_code: Mapped[str] = mapped_column(String(10), index=True)

    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
