"""Tests for `app.llm.openai_provider` (TASK-014).

No real network call: `OpenAIProvider` is always constructed with a fake
client double that implements just the `.chat.completions.create(...)`
shape this module actually calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from app.llm.errors import LLMProviderError
from app.llm.openai_provider import DEFAULT_OPENAI_MODEL, OpenAIProvider
from app.llm.provider import CompletionRequest, Message


def _chat_completion(text: str, *, prompt_tokens: int = 10, completion_tokens: int = 5) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class _FakeCompletions:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeOpenAIClient:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(response=response, error=error))


def _connection_error(message: str = "boom") -> openai.APIConnectionError:
    return openai.APIConnectionError(
        message=message,
        request=httpx2.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


# --- complete(): happy path -----------------------------------------------------


def test_complete_returns_mapped_text_and_usage() -> None:
    client = _FakeOpenAIClient(
        response=_chat_completion("hello there", prompt_tokens=7, completion_tokens=3)
    )
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    response = provider.complete(request)

    assert response.text == "hello there"
    assert response.usage is not None
    assert response.usage.input_tokens == 7
    assert response.usage.output_tokens == 3


def test_complete_uses_default_model() -> None:
    client = _FakeOpenAIClient(response=_chat_completion("ok"))
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert client.chat.completions.calls[0]["model"] == DEFAULT_OPENAI_MODEL


def test_complete_honors_explicit_model_override() -> None:
    client = _FakeOpenAIClient(response=_chat_completion("ok"))
    provider = OpenAIProvider(client=client, model="gpt-custom")  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert client.chat.completions.calls[0]["model"] == "gpt-custom"


def test_complete_never_passes_max_tokens() -> None:
    # Approved TASK-014 correction: DEFAULT_MAX_TOKENS is an Anthropic-only
    # wrapper detail and must NOT be applied to OpenAI "for symmetry".
    client = _FakeOpenAIClient(response=_chat_completion("ok"))
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    call = client.chat.completions.calls[0]
    assert "max_tokens" not in call
    assert "max_completion_tokens" not in call


def test_complete_passes_system_message_directly_in_messages() -> None:
    # Unlike Anthropic, OpenAI accepts role="system" inside `messages`
    # directly -- no splitting needed.
    client = _FakeOpenAIClient(response=_chat_completion("ok"))
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ]
    )

    provider.complete(request)

    call = client.chat.completions.calls[0]
    assert "system" not in call
    assert call["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]


def test_complete_maps_multi_turn_conversation() -> None:
    client = _FakeOpenAIClient(response=_chat_completion("ok"))
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="how are you"),
        ]
    )

    provider.complete(request)

    assert client.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"},
    ]


def test_complete_handles_missing_message_content() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0),
    )
    client = _FakeOpenAIClient(response=response)
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    result = provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert result.text == ""


def test_complete_handles_missing_usage() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=None,
    )
    client = _FakeOpenAIClient(response=response)
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    result = provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert result.usage is None


# --- complete(): error path ------------------------------------------------------


def test_complete_wraps_sdk_error_as_llm_provider_error() -> None:
    error = _connection_error("network down")
    client = _FakeOpenAIClient(error=error)
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    with pytest.raises(LLMProviderError) as excinfo:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert excinfo.value.__cause__ is error


def test_complete_error_does_not_leak_raw_sdk_exception_type() -> None:
    client = _FakeOpenAIClient(error=_connection_error())
    provider = OpenAIProvider(client=client)  # type: ignore[arg-type]

    try:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))
    except LLMProviderError:
        pass
    except openai.APIError:
        pytest.fail("raw openai.APIError leaked instead of LLMProviderError")
