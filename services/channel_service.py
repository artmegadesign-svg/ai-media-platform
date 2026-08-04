from sqlalchemy.orm import Session

from models.channel import Channel
from repositories.channel_repository import ChannelRepository


class ChannelService:
    def __init__(self, db: Session):
        self.repository = ChannelRepository(db)

    def create_channel(
        self,
        name: str,
        platform: str,
        language_code: str,
        gateway_channel_id: str | None = None,
        is_active: bool = True,
    ):
        channel = Channel(
            name=name,
            platform=platform,
            language_code=language_code,
            gateway_channel_id=gateway_channel_id,
            is_active=is_active,
        )

        return self.repository.create(channel)

    def get_channels(self):
        return self.repository.get_all()

    def get_active_channels(self):
        return self.repository.get_active_channels()

    def get_by_name(self, name: str):
        return self.repository.get_by_name(name)
