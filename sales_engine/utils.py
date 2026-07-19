from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from loguru import logger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_path: str = Field(default="data/sales_engine.sqlite3", alias="DATABASE_PATH")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-flash", alias="GEMINI_MODEL")
    gmail_username: Optional[str] = Field(default=None, alias="GMAIL_USERNAME")
    gmail_app_password: Optional[str] = Field(default=None, alias="GMAIL_APP_PASSWORD")
    sender_name: str = Field(default="Sales Team", alias="SENDER_NAME")
    value_proposition: str = Field(
        default="We help revenue teams identify qualified opportunities and automate personalized outreach without losing human oversight.",
        alias="VALUE_PROPOSITION",
    )
    log_path: str = Field(default="logs/sales_engine.log", alias="LOG_PATH")
    request_timeout_seconds: int = Field(default=15, alias="REQUEST_TIMEOUT_SECONDS")

    @field_validator("database_path", "log_path")
    @classmethod
    def non_empty_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Path values cannot be empty")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    Path(settings.log_path).parent.mkdir(parents=True, exist_ok=True)
    logger.add(settings.log_path, rotation="1 MB", retention="7 days", enqueue=True, backtrace=False, diagnose=False)
    return settings


def normalize_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("Website URL is required")
    if not re.match(r"^https?://", value, flags=re.I):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError(f"Invalid website URL: {url}")
    normalized = parsed._replace(fragment="").geturl().rstrip("/")
    return normalized


def truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[: max_chars - 1] + "…" if len(clean) > max_chars else clean
