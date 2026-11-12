from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, PositiveFloat

from services.news.models import OfficialImagePolicy


class Settings(BaseSettings):
    app_name: str = "AI Media Platform"

    ai_gateway_url: str
    ai_gateway_internal_token: str | None = None
    telegram_gateway_timeout_seconds: PositiveFloat = Field(
        default=30, allow_inf_nan=False
    )

    postgres_db: str
    postgres_user: str
    postgres_password: str

    redis_port: int = 6379
    official_image_policies: dict[str, OfficialImagePolicy] = Field(
        default_factory=dict
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
