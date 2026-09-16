"""Tests for app.config.settings (TASK-002).

Covers: defaults, environment variable overrides, `.env` file loading and
precedence, and validation of `DEFAULT_LANGUAGE` / `LLM_PROVIDER`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import APP_TIMEZONE_NAME, SUPPORTED_LANGUAGES, ConfigurationError
from app.config.settings import APP_TIMEZONE, load_settings

_ENV_VARS = (
    "LLM_PROVIDER",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "DEFAULT_LANGUAGE",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "NEWS_LOOKBACK_DAYS",
)

# A path guaranteed not to exist, so `load_settings` never picks up this
# machine's real `.env` (which may hold actual local secrets) during tests
# that only care about environment variables.
_NO_ENV_FILE = "does-not-exist.env"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never depend on the developer's own environment."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_when_no_environment_variables_are_set() -> None:
    settings = load_settings(env_file=_NO_ENV_FILE)

    assert settings.llm_provider == "anthropic"
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None
    assert settings.database_url == "sqlite:///data/ai_daily.db"
    assert settings.default_language == "it"
    assert settings.telegram_bot_token is None
    assert settings.telegram_chat_id is None
    assert settings.news_lookback_days == 2


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/custom.db")
    monkeypatch.setenv("DEFAULT_LANGUAGE", "en")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("NEWS_LOOKBACK_DAYS", "5")

    settings = load_settings(env_file=_NO_ENV_FILE)

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "sk-test"
    assert settings.database_url == "sqlite:///data/custom.db"
    assert settings.default_language == "en"
    assert settings.telegram_bot_token == "bot-token"
    assert settings.telegram_chat_id == "12345"
    assert settings.news_lookback_days == 5


def test_empty_environment_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DEFAULT_LANGUAGE", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("NEWS_LOOKBACK_DAYS", "")

    settings = load_settings(env_file=_NO_ENV_FILE)

    assert settings.llm_provider == "anthropic"
    assert settings.database_url == "sqlite:///data/ai_daily.db"
    assert settings.default_language == "it"
    assert settings.anthropic_api_key is None
    assert settings.news_lookback_days == 2


def test_unsupported_language_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_LANGUAGE", "fr")

    with pytest.raises(ConfigurationError, match="DEFAULT_LANGUAGE"):
        load_settings(env_file=_NO_ENV_FILE)


def test_unsupported_llm_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "made-up-provider")

    with pytest.raises(ConfigurationError):
        load_settings(env_file=_NO_ENV_FILE)


def test_negative_news_lookback_days_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_LOOKBACK_DAYS", "-1")

    with pytest.raises(ConfigurationError, match="NEWS_LOOKBACK_DAYS"):
        load_settings(env_file=_NO_ENV_FILE)


def test_non_numeric_news_lookback_days_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_LOOKBACK_DAYS", "not-a-number")

    with pytest.raises(ConfigurationError):
        load_settings(env_file=_NO_ENV_FILE)


def test_dot_env_file_is_loaded(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-from-file\nDEFAULT_LANGUAGE=en\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "sk-from-file"
    assert settings.default_language == "en"


def test_existing_environment_variable_takes_precedence_over_dot_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")

    settings = load_settings(env_file=env_file)

    assert settings.llm_provider == "anthropic"


def test_missing_dot_env_file_does_not_raise() -> None:
    settings = load_settings(env_file=_NO_ENV_FILE)

    assert settings.llm_provider == "anthropic"


def test_supported_languages_are_it_and_en() -> None:
    assert set(SUPPORTED_LANGUAGES) == {"it", "en"}


def test_app_timezone_is_europe_rome() -> None:
    assert APP_TIMEZONE_NAME == "Europe/Rome"
    assert str(APP_TIMEZONE) == "Europe/Rome"
