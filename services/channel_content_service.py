from sqlalchemy.orm import Session

from models.channel_content import ChannelContent
from repositories.channel_content_repository import ChannelContentRepository


class ChannelContentService:

    def __init__(self, db: Session):
        self.repository = ChannelContentRepository(db)

    def create_content(
        self,
        channel_id: int,
        post_id: int,
        platform_post_id: str | None = None,
        status: str = "pending",
    ):
        content = ChannelContent(
            channel_id=channel_id,
            post_id=post_id,
            platform_post_id=platform_post_id,
            status=status,
        )

        return self.repository.create(content)

    def get_channel_content(self, channel_id: int):
        return self.repository.get_by_channel_id(channel_id)

    def get_post_content(self, post_id: int):
        return self.repository.get_by_post_id(post_id)
