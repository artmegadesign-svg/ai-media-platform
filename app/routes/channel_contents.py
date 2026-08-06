from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db

from schemas.channel_content import (
    ChannelContentCreate,
    ChannelContentResponse,
)

from services.channel_content_service import ChannelContentService


router = APIRouter(
    prefix="/channel-content",
    tags=["channel-content"],
)


@router.post("/", response_model=ChannelContentResponse)
def create_channel_content(
    data: ChannelContentCreate,
    db: Session = Depends(get_db),
):
    service = ChannelContentService(db)

    return service.create_content(
        channel_id=data.channel_id,
        post_id=data.post_id,
        platform_post_id=data.platform_post_id,
        status=data.status,
    )


@router.get(
    "/channel/{channel_id}",
    response_model=list[ChannelContentResponse],
)
def get_channel_content(
    channel_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = ChannelContentService(db)

    return service.get_channel_content(channel_id, limit=limit, offset=offset)


@router.get(
    "/post/{post_id}",
    response_model=ChannelContentResponse | None,
)
def get_post_content(
    post_id: int,
    db: Session = Depends(get_db),
):
    service = ChannelContentService(db)

    return service.get_post_content(post_id)
