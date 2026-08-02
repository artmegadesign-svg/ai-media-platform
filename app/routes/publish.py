from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.channel_content import ChannelContent
from services.publisher.publisher_service import PublisherService
from services.publisher.adapters.mock import MockPublisher


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
    content = (
        db.query(ChannelContent)
        .filter(ChannelContent.id == content_id)
        .first()
    )

    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    service = PublisherService(
        db=db,
        publisher=MockPublisher(),
    )

    result = service.publish(content)

    return {
        "success": result.success,
        "content_id": content.id,
        "status": content.status,
        "platform_post_id": content.platform_post_id,
        "published_at": (
            content.published_at.isoformat()
            if content.published_at
            else None
        ),
        "error": result.error,
    }
