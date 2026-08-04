from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChannelCreate(BaseModel):
    name: str
    platform: str
    language_code: str
    gateway_channel_id: str | None = None


class ChannelResponse(BaseModel):
    id: int
    name: str
    platform: str
    language_code: str
    gateway_channel_id: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
