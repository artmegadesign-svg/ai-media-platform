from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func

from db.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String, nullable=False)

    source_url = Column(Text, nullable=True)

    language = Column(String, nullable=False)  # ru / en

    niche = Column(String, nullable=True)

    score = Column(Float, default=0)

    status = Column(
        String,
        default="new"
    )  # new / processed / published

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
