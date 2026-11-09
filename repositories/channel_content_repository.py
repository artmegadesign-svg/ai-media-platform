from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.channel_content import ChannelContent
from repositories.base import BaseRepository, is_unique_conflict


class ChannelContentRepository(BaseRepository[ChannelContent]):

    def __init__(self, db: Session):
        super().__init__(
            db=db,
            model=ChannelContent,
        )

    def get_by_post_and_channel(self, post_id: int, channel_id: int):
        return self.db.query(ChannelContent).filter_by(
            post_id=post_id, channel_id=channel_id,
        ).first()

    def create(self, obj: ChannelContent):
        post_id, channel_id = obj.post_id, obj.channel_id
        existing = self.get_by_post_and_channel(post_id, channel_id)
        if existing is not None:
            return existing
        try:
            return super().create(obj)
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_conflict(
                exc, "ux_channel_contents_post_channel",
                "channel_contents.post_id, channel_contents.channel_id",
            ):
                existing = self.get_by_post_and_channel(post_id, channel_id)
                if existing is not None:
                    return existing
            raise

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
