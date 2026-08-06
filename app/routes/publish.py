from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from models.channel_content import ChannelContent
from services.publisher.publisher_service import PublisherService
from services.publisher.factory import publisher_factory
from services.publisher.factory import settings  # noqa: F401 - legacy injection seam

# Backward-compatible injection seam. Construction remains centralized in the factory.
TelegramPublisher = publisher_factory.telegram_publisher_class

router = APIRouter()


@router.post("/publish/{content_id}")
def publish(content_id: int, db: Session = Depends(get_db)):
    if hasattr(db, "get"):
        content = db.get(ChannelContent, content_id)
    else:
        content = db.query(ChannelContent).filter(ChannelContent.id == content_id).first()
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    publisher_factory.telegram_publisher_class = TelegramPublisher
    result = PublisherService(db=db, factory=publisher_factory).publish(content)
    return {
        "success": result.success,
        "content_id": content.id,
        "status": content.status,
        "platform_post_id": content.platform_post_id,
        "published_at": content.published_at.isoformat() if content.published_at else None,
        "error": result.error,
    }
