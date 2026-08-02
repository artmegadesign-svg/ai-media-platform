from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import SessionLocal
from services.channel_service import ChannelService
from schemas.channel import ChannelCreate, ChannelResponse


router = APIRouter(
    prefix="/channels",
    tags=["channels"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=list[ChannelResponse])
def get_channels(
    db: Session = Depends(get_db),
):
    service = ChannelService(db)
    return service.get_channels()


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
    )
