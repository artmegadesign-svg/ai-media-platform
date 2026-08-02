from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChannelContentBase(BaseModel):
    channel_id: int
    post_id: int
    platform_post_id: str | None = None
    status: str = "pending"
    published_at: datetime | None = None


class ChannelContentCreate(ChannelContentBase):
    pass


class ChannelContentResponse(ChannelContentBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )
