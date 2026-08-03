from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    app_name: str = "AI Media Platform"

    ai_gateway_url: str

    postgres_db: str
    postgres_user: str
    postgres_password: str

    redis_port: int = 6379


    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
