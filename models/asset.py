from sqlalchemy import Column, Integer, Text, DateTime, func
from db.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)

    topic = Column(Text, nullable=False)
    ru_content = Column(Text, nullable=False)
    en_content = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
