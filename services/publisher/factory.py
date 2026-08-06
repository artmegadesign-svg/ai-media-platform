from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.settings import settings
from models.channel import Channel
from models.channel_content import ChannelContent
from models.post import Post
from services.publisher.adapters.mock import MockPublisher
from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.interface import PublisherInterface


class PublisherFactory:
    telegram_publisher_class = TelegramPublisher

    @staticmethod
    def _get(db: Session, model, object_id: int):
        if hasattr(db, "get"):
            return db.get(model, object_id)
        return db.query(model).filter(model.id == object_id).first()

    def create(self, db: Session, content: ChannelContent) -> PublisherInterface:
        channel = self._get(db, Channel, content.channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if channel.platform.lower() != "telegram":
            return MockPublisher()
        if not channel.gateway_channel_id:
            raise HTTPException(status_code=422, detail="Telegram channel has no gateway_channel_id")
        if not settings.ai_gateway_internal_token:
            raise HTTPException(status_code=503, detail="AI Gateway internal token is not configured")
        post = self._get(db, Post, content.post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        text = post.ru_content if channel.language_code.lower() == "ru" else post.en_content
        return self.telegram_publisher_class(
            gateway_url=settings.ai_gateway_url,
            internal_token=settings.ai_gateway_internal_token,
            gateway_channel_id=channel.gateway_channel_id,
            text=text,
        )


publisher_factory = PublisherFactory()
