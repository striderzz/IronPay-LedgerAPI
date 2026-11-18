"""Settings read from environment variables (and `.env` when present)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ironpay:ironpay@localhost:5432/ironpay"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"

    # Auth. Set a long random JWT_SECRET in .env for anything beyond local use.
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 15

    # Token bucket rate limits: `rate` tokens per second refill, up to `burst` tokens.
    transfer_rate_per_sec: float = 5.0
    transfer_burst: int = 20
    login_rate_per_sec: float = 0.2
    login_burst: int = 5

    idempotency_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
