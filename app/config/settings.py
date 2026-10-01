"""Application settings loaded from environment variables.

See `.env.example` for the supported variables and their defaults, and
docs/ARCHITECTURE.md §1.1, §5.1 and §9 for the design decisions this module
implements:

- LLM provider selection and credentials are read but not validated against
  a live provider — the `LLMProvider` abstraction itself is a later task
  (TODO.md, TASK-014).
- `default_language` must be one of `SUPPORTED_LANGUAGES` (PRD §38): the
  language is never hardcoded in application components.
- `APP_TIMEZONE` is a fixed constant, not an environment variable: the MVP
  uses a single, fixed timezone with no per-user or per-locale handling
  (docs/ARCHITECTURE.md §9). Actually using it for scheduling or timestamps
  is left to the tasks that need it (e.g. Logging, TASK-003).
- `news_lookback_days` (TASK-028) is the FILTER stage's recency window
  (docs/ARCHITECTURE.md §2, §4.15): the maximum age, in days, an article's
  `published_at` may have to still be collected/clustered. Must be a
  non-negative integer; `DEFAULT_NEWS_LOOKBACK_DAYS` is the approved
  default (2 days).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ValidationError, field_validator

from app.config.errors import ConfigurationError

# Editorial languages supported by AI Daily (PRD §38, ARCHITECTURE §5.1).
# Adding a language means adding a value here plus an entry in
# config/labels.yaml, not modifying the pipeline.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("it", "en")

# Fixed application timezone (ARCHITECTURE §9 — decided, not yet wired into
# any scheduling or logging logic).
APP_TIMEZONE_NAME = "Europe/Rome"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)

LLMProviderName = Literal["anthropic", "openai", "gemini"]

# Approved TASK-028 default: an article/event is still fresh if its most
# recent `published_at` is no more than this many days before the reference
# date (docs/ARCHITECTURE.md §4.15). Exposed as a constant, not just a
# literal default value, so `app.collectors.rss` and `app.pipeline.generation`
# can fall back to the exact same number without duplicating it.
DEFAULT_NEWS_LOOKBACK_DAYS = 2


class Settings(BaseModel):
    """Validated application configuration (see `.env.example`)."""

    llm_provider: LLMProviderName = "anthropic"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    database_url: str = "sqlite:///data/ai_daily.db"
    default_language: str = "it"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    news_lookback_days: int = DEFAULT_NEWS_LOOKBACK_DAYS
    llm_min_interval_seconds: float = 0.0

    @field_validator("default_language")
    @classmethod
    def _validate_default_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"DEFAULT_LANGUAGE must be one of {SUPPORTED_LANGUAGES}, got {value!r}"
            )
        return value

    @field_validator("news_lookback_days")
    @classmethod
    def _validate_news_lookback_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"NEWS_LOOKBACK_DAYS must be >= 0, got {value!r}")
        return value

    @field_validator("llm_min_interval_seconds")
    @classmethod
    def _validate_llm_min_interval_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError(f"LLM_MIN_INTERVAL_SECONDS must be >= 0, got {value!r}")
        return value


def _read_env(name: str, default: str) -> str:
    """Read a required-with-default environment variable.

    An unset or empty value falls back to `default`; validation of the
    resulting value (if any) happens on the `Settings` model itself.
    """
    value = os.environ.get(name)
    return value if value else default


def _read_optional_env(name: str) -> str | None:
    """Read an optional environment variable (e.g. a secret with no default)."""
    return os.environ.get(name) or None


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load and validate application settings.

    Loads `.env` (if present) via python-dotenv, then reads process
    environment variables. Environment variables already set take
    precedence over values from the `.env` file, so real deployment
    environments are never overridden by a stray local `.env`.

    When `env_file` is not given, the `.env` file is looked up relative to
    the current working directory (`find_dotenv(usecwd=True)`) rather than
    to this module's own file location. `load_dotenv`'s own default
    (`find_dotenv()` with `usecwd=False`) walks up from
    `app/config/settings.py`'s directory instead, which can silently load
    this repository's own `.env` (real secrets included) even when the
    caller has `chdir`-ed elsewhere, e.g. into an isolated test workspace.

    Raises:
        ConfigurationError: if a value is present but invalid (e.g. an
            unsupported `DEFAULT_LANGUAGE` or `LLM_PROVIDER`).
    """
    resolved_path = env_file if env_file is not None else find_dotenv(usecwd=True)
    load_dotenv(dotenv_path=resolved_path, override=False)

    try:
        return Settings.model_validate(
            {
                "llm_provider": _read_env("LLM_PROVIDER", "anthropic"),
                "anthropic_api_key": _read_optional_env("ANTHROPIC_API_KEY"),
                "gemini_api_key": _read_optional_env("GEMINI_API_KEY"),
                "openai_api_key": _read_optional_env("OPENAI_API_KEY"),
                "database_url": _read_env("DATABASE_URL", "sqlite:///data/ai_daily.db"),
                "default_language": _read_env("DEFAULT_LANGUAGE", "it"),
                "telegram_bot_token": _read_optional_env("TELEGRAM_BOT_TOKEN"),
                "telegram_chat_id": _read_optional_env("TELEGRAM_CHAT_ID"),
                "news_lookback_days": _read_env(
                    "NEWS_LOOKBACK_DAYS", str(DEFAULT_NEWS_LOOKBACK_DAYS)
                ),
                "llm_min_interval_seconds": _read_env("LLM_MIN_INTERVAL_SECONDS", "0"),
            }
        )
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid application configuration: {exc}") from exc
