from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://radar:radar@localhost:5432/radar"
    redis_url: str = "redis://localhost:6379/0"
    evidence_dir: Path = Path("/data/evidence")

    # enrichment
    http_timeout: float = 20.0
    http_user_agent: str = (
        "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    )
    accept_language: str = "az-AZ,az;q=0.9,ru;q=0.8,tr;q=0.7,en;q=0.6"
    screenshot_enabled: bool = True
    chromium_path: str | None = None  # leave empty to use the Playwright-managed browser
    enrichment_concurrency: int = 4
    enrichment_refresh_days: int = 7

    api_token: str = ""  # shared secret between web and api until Phase 5 auth

    # collectors
    ocr_enabled: bool = True
    ocr_langs: str = "aze+rus+tur+eng"
    telegram_session_path: Path = Path("/data/telegram/radar.session")
    certstream_url: str = "wss://certstream.calidog.io/"

    # secrets used from Phase 2 on
    apify_token: str = ""
    anthropic_api_key: str = ""
    serp_api_key: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_bot_token: str = ""
    telegram_digest_chat_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
