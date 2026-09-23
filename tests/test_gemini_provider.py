"""Tests for `app.llm.gemini_provider` (TASK-014 follow-up).

No real network call: `GeminiProvider` is always constructed with a fake
client double that implements just the `.models.generate_content(...)`
shape this module actually calls, following the same dependency-injection
design already used for `AnthropicProvider`/`OpenAIProvider`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors
from google.genai import types as genai_types

from app.llm.errors import LLMProviderError
from app.llm.gemini_provider import DEFAULT_GEMINI_MODEL, GeminiProvider
from app.llm.provider import CompletionRequest, Message


def _gemini_response(
    text: str, *, prompt_tokens: int = 10, candidates_tokens: int = 5
) -> Any:
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens, candidates_token_count=candidates_tokens
        ),
    )


class _FakeModels:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeGeminiClient:
    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self.models = _FakeModels(response=response, error=error)


def _api_error(message: str = "boom") -> errors.APIError:
    return errors.APIError(500, {"error": {"message": message}})


# --- complete(): happy path -----------------------------------------------------


def test_complete_returns_mapped_text_and_usage() -> None:
    client = _FakeGeminiClient(
        response=_gemini_response("hello there", prompt_tokens=7, candidates_tokens=3)
    )
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    response = provider.complete(request)

    assert response.text == "hello there"
    assert response.usage is not None
    assert response.usage.input_tokens == 7
    assert response.usage.output_tokens == 3


def test_complete_uses_default_model() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert client.models.calls[0]["model"] == DEFAULT_GEMINI_MODEL


def test_complete_honors_explicit_model_override() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client, model="gemini-custom")  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert client.models.calls[0]["model"] == "gemini-custom"


def test_complete_maps_user_role_to_user() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    contents = client.models.calls[0]["contents"]
    expected_part = genai_types.Part.from_text(text="hi")
    assert contents == [genai_types.Content(role="user", parts=[expected_part])]


def test_complete_maps_assistant_role_to_model() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="how are you"),
        ]
    )

    provider.complete(request)

    contents = client.models.calls[0]["contents"]
    assert [content.role for content in contents] == ["user", "model", "user"]
    assert [content.parts[0].text for content in contents] == ["hi", "hello", "how are you"]


def test_complete_without_system_message_omits_config() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    call = client.models.calls[0]
    assert call["config"] is None
    assert len(call["contents"]) == 1


def test_complete_with_system_message_splits_it_into_system_instruction() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]
    request = CompletionRequest(
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ]
    )

    provider.complete(request)

    call = client.models.calls[0]
    assert call["config"].system_instruction == "be terse"
    assert len(call["contents"]) == 1
    assert call["contents"][0].role == "user"


def test_complete_never_passes_max_tokens() -> None:
    client = _FakeGeminiClient(response=_gemini_response("ok"))
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    call = client.models.calls[0]
    assert "max_tokens" not in call
    assert "max_output_tokens" not in call


def test_complete_handles_missing_text() -> None:
    response = SimpleNamespace(text=None, usage_metadata=None)
    client = _FakeGeminiClient(response=response)
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    result = provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert result.text == ""


def test_complete_handles_missing_usage() -> None:
    response = SimpleNamespace(text="ok", usage_metadata=None)
    client = _FakeGeminiClient(response=response)
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    result = provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert result.usage is None


# --- complete(): error path ------------------------------------------------------


def test_complete_wraps_sdk_error_as_llm_provider_error() -> None:
    error = _api_error("network down")
    client = _FakeGeminiClient(error=error)
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    with pytest.raises(LLMProviderError) as excinfo:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))

    assert excinfo.value.__cause__ is error


def test_complete_error_does_not_leak_raw_sdk_exception_type() -> None:
    client = _FakeGeminiClient(error=_api_error())
    provider = GeminiProvider(client=client)  # type: ignore[arg-type]

    try:
        provider.complete(CompletionRequest(messages=[Message(role="user", content="hi")]))
    except LLMProviderError:
        pass
    except errors.APIError:
        pytest.fail("raw google.genai.errors.APIError leaked instead of LLMProviderError")
