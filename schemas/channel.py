from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ChannelCreate(BaseModel):
    name: str
    platform: str
    language_code: str
    gateway_channel_id: str | None = None
    is_active: bool = True

    @field_validator("gateway_channel_id")
    @classmethod
    def normalize_gateway_channel_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_telegram_configuration(self):
        if self.platform.casefold() == "telegram" and not self.gateway_channel_id:
            raise ValueError("gateway_channel_id is required for Telegram channels")
        return self


class ChannelResponse(BaseModel):
    id: int
    name: str
    platform: str
    language_code: str
    gateway_channel_id: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
