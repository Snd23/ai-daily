"""Tests for `app.llm.retrying_provider` (TASK-033).

No real sleeping and no network: `sleep` and `clock` are injected, and the
wrapped provider is a scripted fake.
"""

from __future__ import annotations

import pytest

from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Message
from app.llm.retrying_provider import BACKOFF_SECONDS, MAX_RETRIES, RetryingProvider

_REQUEST = CompletionRequest(messages=[Message(role="user", content="hi")])
_OK = CompletionResponse(text="ok")


class _ScriptedProvider(LLMProvider):
    """Returns or raises each scripted outcome in order."""

    def __init__(self, *outcomes: CompletionResponse | LLMProviderError) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, LLMProviderError):
            raise outcome
        return outcome


class _FakeTime:
    """A clock that only moves when `sleep` is called."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _wrap(inner: LLMProvider, fake_time: _FakeTime, **kwargs: float) -> RetryingProvider:
    return RetryingProvider(inner, sleep=fake_time.sleep, clock=fake_time.clock, **kwargs)


def test_success_passes_through_without_sleeping() -> None:
    fake_time = _FakeTime()
    provider = _wrap(_ScriptedProvider(_OK), fake_time)

    assert provider.complete(_REQUEST) == _OK
    assert fake_time.sleeps == []


def test_retryable_error_uses_provider_hint_then_succeeds() -> None:
    fake_time = _FakeTime()
    inner = _ScriptedProvider(LLMProviderError("429", retryable=True, retry_after_seconds=45), _OK)
    provider = _wrap(inner, fake_time)

    assert provider.complete(_REQUEST) == _OK
    assert inner.calls == 2
    assert fake_time.sleeps == [45]


def test_retryable_error_without_hint_uses_backoff_sequence() -> None:
    fake_time = _FakeTime()
    inner = _ScriptedProvider(
        LLMProviderError("503", retryable=True),
        LLMProviderError("503", retryable=True),
        LLMProviderError("503", retryable=True),
        _OK,
    )
    provider = _wrap(inner, fake_time)

    assert provider.complete(_REQUEST) == _OK
    assert fake_time.sleeps == list(BACKOFF_SECONDS)


def test_error_is_raised_after_max_retries() -> None:
    fake_time = _FakeTime()
    failure = LLMProviderError("503", retryable=True)
    inner = _ScriptedProvider(*[failure] * (MAX_RETRIES + 1))
    provider = _wrap(inner, fake_time)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_REQUEST)

    assert exc_info.value is failure
    assert inner.calls == MAX_RETRIES + 1
    assert len(fake_time.sleeps) == MAX_RETRIES


def test_non_retryable_error_is_raised_immediately() -> None:
    fake_time = _FakeTime()
    inner = _ScriptedProvider(LLMProviderError("400"))
    provider = _wrap(inner, fake_time)

    with pytest.raises(LLMProviderError):
        provider.complete(_REQUEST)

    assert inner.calls == 1
    assert fake_time.sleeps == []


def test_min_interval_spaces_consecutive_calls() -> None:
    fake_time = _FakeTime()
    provider = _wrap(_ScriptedProvider(_OK, _OK, _OK), fake_time, min_interval_seconds=13)

    provider.complete(_REQUEST)
    provider.complete(_REQUEST)
    fake_time.now += 5  # the caller itself spent 5 s between calls
    provider.complete(_REQUEST)

    assert fake_time.sleeps == [13, 8]


def test_no_pacing_when_interval_is_zero() -> None:
    fake_time = _FakeTime()
    provider = _wrap(_ScriptedProvider(_OK, _OK), fake_time)

    provider.complete(_REQUEST)
    provider.complete(_REQUEST)

    assert fake_time.sleeps == []
