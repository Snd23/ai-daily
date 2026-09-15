"""Tests for `app.llm.provider` (TASK-014): the provider-agnostic contract.

Pure/in-memory only, no network, no SDK client involved -- mirrors the
style of `tests/test_event_ranker.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Message, Usage

# --- Message ------------------------------------------------------------------


def test_message_accepts_each_valid_role() -> None:
    for role in ("system", "user", "assistant"):
        Message(role=role, content="hello")  # type: ignore[arg-type]


def test_message_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        Message(role="tool", content="hello")  # type: ignore[arg-type]


def test_message_is_frozen() -> None:
    message = Message(role="user", content="hello")

    with pytest.raises(ValidationError):
        message.content = "changed"  # type: ignore[misc]


# --- CompletionRequest ----------------------------------------------------------


def test_completion_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(messages=[])


def test_completion_request_accepts_single_user_message() -> None:
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    assert request.messages == [Message(role="user", content="hi")]


def test_completion_request_accepts_system_message_first() -> None:
    request = CompletionRequest(
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ]
    )

    assert request.messages[0].role == "system"


def test_completion_request_rejects_system_message_not_first() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(
            messages=[
                Message(role="user", content="hi"),
                Message(role="system", content="be terse"),
            ]
        )


def test_completion_request_rejects_more_than_one_system_message() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(
            messages=[
                Message(role="system", content="be terse"),
                Message(role="system", content="also this"),
                Message(role="user", content="hi"),
            ]
        )


def test_completion_request_accepts_multi_turn_conversation() -> None:
    request = CompletionRequest(
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="how are you"),
        ]
    )

    assert len(request.messages) == 3


def test_completion_request_is_frozen() -> None:
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    with pytest.raises(ValidationError):
        request.messages = []  # type: ignore[misc]


# --- Usage / CompletionResponse -------------------------------------------------


def test_usage_rejects_negative_token_counts() -> None:
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1, output_tokens=0)
    with pytest.raises(ValidationError):
        Usage(input_tokens=0, output_tokens=-1)


def test_usage_accepts_zero_token_counts() -> None:
    Usage(input_tokens=0, output_tokens=0)


def test_completion_response_usage_is_optional() -> None:
    response = CompletionResponse(text="hello")

    assert response.usage is None


def test_completion_response_accepts_usage() -> None:
    response = CompletionResponse(text="hello", usage=Usage(input_tokens=1, output_tokens=2))

    assert response.usage == Usage(input_tokens=1, output_tokens=2)


def test_completion_response_is_frozen() -> None:
    response = CompletionResponse(text="hello")

    with pytest.raises(ValidationError):
        response.text = "changed"  # type: ignore[misc]


# --- LLMProvider ------------------------------------------------------------------


def test_llm_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
