from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from services.channel_service import ChannelService
from schemas.channel import ChannelCreate, ChannelResponse


router = APIRouter(
    prefix="/channels",
    tags=["channels"],
)


@router.get("/", response_model=list[ChannelResponse])
def get_channels(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = ChannelService(db)
    return service.get_channels(limit=limit, offset=offset)


@router.post("/", response_model=ChannelResponse)
def create_channel(
    data: ChannelCreate,
    db: Session = Depends(get_db),
):
    service = ChannelService(db)

    return service.create_channel(
        name=data.name,
        platform=data.platform,
        language_code=data.language_code,
        gateway_channel_id=data.gateway_channel_id,
        is_active=data.is_active,
    )
