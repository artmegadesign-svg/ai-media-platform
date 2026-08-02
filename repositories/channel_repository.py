from sqlalchemy.orm import Session

from models.channel import Channel
from repositories.base import BaseRepository


class ChannelRepository(BaseRepository[Channel]):
    def __init__(self, db: Session):
        super().__init__(
            db=db,
            model=Channel,
        )

    def get_by_name(self, name: str):
        return (
            self.db.query(Channel)
            .filter(Channel.name == name)
            .first()
        )

    def get_active_channels(self):
        return (
            self.db.query(Channel)
            .filter(Channel.is_active == True)
            .all()
        )
