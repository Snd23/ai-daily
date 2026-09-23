"""LLM provider abstraction (TASK-014).

A provider-agnostic completion primitive (`LLMProvider.complete`) plus
three concrete implementations (`AnthropicProvider`, `OpenAIProvider`,
`GeminiProvider`) and a factory that selects one from the existing
`Settings.llm_provider` configuration. Deliberately excludes
`summarize`/`explain`/`classify`/`rank`: those are domain-specific use
cases owned by their own future consumer tasks (see `app.llm.provider`
module docstring).
"""

from app.llm.anthropic_provider import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_MAX_TOKENS,
    AnthropicProvider,
)
from app.llm.errors import LLMProviderError
from app.llm.factory import create_llm_provider
from app.llm.gemini_provider import DEFAULT_GEMINI_MODEL, GeminiProvider
from app.llm.openai_provider import DEFAULT_OPENAI_MODEL, OpenAIProvider
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Message, Usage

__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_OPENAI_MODEL",
    "AnthropicProvider",
    "CompletionRequest",
    "CompletionResponse",
    "GeminiProvider",
    "LLMProvider",
    "LLMProviderError",
    "Message",
    "OpenAIProvider",
    "Usage",
    "create_llm_provider",
]
