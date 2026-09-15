"""Tests for `app.llm.factory` (TASK-014).

Only construction is exercised here (no `complete()` call, no network):
constructing a real `anthropic.Anthropic`/`openai.OpenAI` client does not
itself perform any HTTP request.
"""

from __future__ import annotations

import pytest

from app.config.errors import ConfigurationError
from app.config.settings import Settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.factory import create_llm_provider
from app.llm.openai_provider import OpenAIProvider


def test_creates_anthropic_provider_when_selected_with_key() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="test-key")

    provider = create_llm_provider(settings)

    assert isinstance(provider, AnthropicProvider)


def test_raises_configuration_error_when_anthropic_key_missing() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key=None)

    with pytest.raises(ConfigurationError):
        create_llm_provider(settings)


def test_creates_openai_provider_when_selected_with_key() -> None:
    settings = Settings(llm_provider="openai", openai_api_key="test-key")

    provider = create_llm_provider(settings)

    assert isinstance(provider, OpenAIProvider)


def test_raises_configuration_error_when_openai_key_missing() -> None:
    settings = Settings(llm_provider="openai", openai_api_key=None)

    with pytest.raises(ConfigurationError):
        create_llm_provider(settings)
