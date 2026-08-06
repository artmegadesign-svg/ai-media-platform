from sqlalchemy.orm import Session

from models.channel_content import ChannelContent
from repositories.base import BaseRepository


class ChannelContentRepository(BaseRepository[ChannelContent]):

    def __init__(self, db: Session):
        super().__init__(
            db=db,
            model=ChannelContent,
        )

    def get_by_channel_id(self, channel_id: int, limit: int = 50, offset: int = 0):
        return (
            self.db.query(ChannelContent)
            .filter(ChannelContent.channel_id == channel_id)
            .order_by(ChannelContent.created_at.desc(), ChannelContent.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_by_post_id(self, post_id: int):
        return (
            self.db.query(ChannelContent)
            .filter(ChannelContent.post_id == post_id)
            .first()
        )
