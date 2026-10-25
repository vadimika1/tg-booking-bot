from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"

    telegram_bot_token: str = ""
    telegram_manager_chat_ids: str = ""
    telegram_sticker_welcome: str = ""
    telegram_sticker_booked: str = ""
    telegram_sticker_cancelled: str = ""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tg_booking"
    postgres_user: str = "tg_booking"
    postgres_password: str = "tg_booking"

    redis_url: str = "redis://localhost:6379/0"
    timezone: str = "Europe/Moscow"
    slot_buffer_min: int = 10

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    bot_polling_timeout: int = 30
    worker_poll_interval: int = 30
    worker_daily_report_enabled: bool = True
    worker_daily_report_hour: int = Field(default=20, ge=0, le=23)
    worker_daily_report_minute: int = Field(default=0, ge=0, le=59)

    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_sync_url(self) -> str:
        return (
            "postgresql+psycopg://"
            f"{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
