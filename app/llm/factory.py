"""Provider selection (TASK-014, extended with a `gemini` option): builds
a real `LLMProvider` from `Settings`.

Uses exclusively the already-existing `Settings.llm_provider`,
`Settings.anthropic_api_key`, `Settings.openai_api_key` and
`Settings.gemini_api_key` -- no new configuration key beyond
`gemini_api_key` was introduced for the free-tier Gemini option. This is
the only place in `app.llm` that constructs a real vendor SDK client;
every provider class itself only ever receives an already-constructed
client (see `app.llm.anthropic_provider`, `app.llm.openai_provider`,
`app.llm.gemini_provider`).
"""

from __future__ import annotations

import anthropic
import openai
from google import genai

from app.config.errors import ConfigurationError
from app.config.settings import Settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.provider import LLMProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Build the `LLMProvider` selected by `settings.llm_provider`.

    Raises:
        ConfigurationError: if the API key required by the selected
            provider is missing (CLAUDE.md §34 -- fail explicitly rather
            than construct a provider that can never succeed).
    """
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return AnthropicProvider(client=anthropic.Anthropic(api_key=settings.anthropic_api_key))

    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAIProvider(client=openai.OpenAI(api_key=settings.openai_api_key))

    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiProvider(client=genai.Client(api_key=settings.gemini_api_key))

    raise AssertionError(f"unreachable: unsupported llm_provider {settings.llm_provider!r}")
