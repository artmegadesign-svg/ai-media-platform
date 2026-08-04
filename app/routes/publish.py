from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.session import SessionLocal
from core.settings import settings
from models.channel import Channel
from models.channel_content import ChannelContent
from models.post import Post
from services.publisher.publisher_service import PublisherService
from services.publisher.adapters.mock import MockPublisher
from services.publisher.adapters.telegram import TelegramPublisher


router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/publish/{content_id}")
def publish(
    content_id: int,
    db: Session = Depends(get_db),
):
    content = db.query(ChannelContent).filter(ChannelContent.id == content_id).first()

    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    channel = db.query(Channel).filter(Channel.id == content.channel_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    publisher = MockPublisher()
    if channel.platform.lower() == "telegram":
        if not channel.gateway_channel_id:
            raise HTTPException(
                status_code=422,
                detail="Telegram channel has no gateway_channel_id",
            )
        if not settings.ai_gateway_internal_token:
            raise HTTPException(
                status_code=503,
                detail="AI Gateway internal token is not configured",
            )
        post = db.query(Post).filter(Post.id == content.post_id).first()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        text = (
            post.ru_content
            if channel.language_code.lower() == "ru"
            else post.en_content
        )
        publisher = TelegramPublisher(
            gateway_url=settings.ai_gateway_url,
            internal_token=settings.ai_gateway_internal_token,
            gateway_channel_id=channel.gateway_channel_id,
            text=text,
        )

    service = PublisherService(
        db=db,
        publisher=publisher,
    )

    result = service.publish(content)

    return {
        "success": result.success,
        "content_id": content.id,
        "status": content.status,
        "platform_post_id": content.platform_post_id,
        "published_at": (
            content.published_at.isoformat() if content.published_at else None
        ),
        "error": result.error,
    }
