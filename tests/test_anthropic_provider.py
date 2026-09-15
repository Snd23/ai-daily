"""Tests for `app.llm.anthropic_provider` (TASK-014).

No real network call: `AnthropicProvider` is always constructed with a
fake client double that implements just the `.messages.create(...)`
shape this module actually calls, following the dependency-injection
design approved for TASK-014.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.llm.anthropic_provider import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_MAX_TOKENS,
    AnthropicProvider,
)
from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, Message


def _anthropic_message(text: str, *, input_tokens: int = 10, output_tokens: int = 5) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeMessages:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeAnthropicClient:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self.messages = _FakeMessages(response=response, error=error)


def _connection_error(message: str = "boom") -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(
        message=message, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )


# --- complete(): happy path -----------------------------------------------------


def test_complete_returns_mapped_text_and_usage() -> None:
    client = _FakeAnthropicClient(
        response=_anthropic_message("hello there", input_tokens=7, output_tokens=3)
    )
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    response = provider.complete(request)

    assert response.text == "hello there"
    assert response.usage is not None
    assert response.usage.input_tokens == 7
    assert response.usage.output_tokens == 3


def test_complete_uses_default_model_and_max_tokens() -> None:
    client = _FakeAnthropicClient(response=_anthropic_message("ok"))
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    call = client.messages.calls[0]
    assert call["model"] == DEFAULT_ANTHROPIC_MODEL
    assert call["max_tokens"] == DEFAULT_MAX_TOKENS


def test_complete_honors_explicit_model_override() -> None:
    client = _FakeAnthropicClient(response=_anthropic_message("ok"))
    provider = AnthropicProvider(client=client, model="claude-custom")  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert client.messages.calls[0]["model"] == "claude-custom"


def test_complete_without_system_message_omits_system_kwarg() -> None:
    client = _FakeAnthropicClient(response=_anthropic_message("ok"))
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    call = client.messages.calls[0]
    assert "system" not in call
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_with_system_message_splits_it_into_system_kwarg() -> None:
    client = _FakeAnthropicClient(response=_anthropic_message("ok"))
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ]
    )

    provider.complete(request)

    call = client.messages.calls[0]
    assert call["system"] == "be terse"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_maps_multi_turn_conversation() -> None:
    client = _FakeAnthropicClient(response=_anthropic_message("ok"))
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="how are you"),
        ]
    )

    provider.complete(request)

    assert client.messages.calls[0]["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"},
    ]


def test_complete_response_without_usage_is_not_produced_when_usage_present() -> None:
    # Anthropic's Message always includes usage; this documents that the
    # provider always maps it through rather than dropping it.
    client = _FakeAnthropicClient(
        response=_anthropic_message("ok", input_tokens=1, output_tokens=1)
    )
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]

    response = provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert response.usage is not None


# --- complete(): error path ------------------------------------------------------


def test_complete_wraps_sdk_error_as_llm_provider_error() -> None:
    error = _connection_error("network down")
    client = _FakeAnthropicClient(error=error)
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]

    with pytest.raises(LLMProviderError) as excinfo:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert excinfo.value.__cause__ is error


def test_complete_error_does_not_leak_raw_sdk_exception_type() -> None:
    client = _FakeAnthropicClient(error=_connection_error())
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]

    try:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))
    except LLMProviderError:
        pass
    except anthropic.APIError:
        pytest.fail("raw anthropic.APIError leaked instead of LLMProviderError")
