"""`RetryingProvider` (TASK-033): pacing and retry for any `LLMProvider`.

Wraps an already-built provider (CLAUDE.md §19: the rest of the app stays
provider-agnostic) and adds two behaviors the free tier of the Gemini API
needs (5 requests per minute, occasional 503 overload):

- pacing: at least `min_interval_seconds` between the start of two calls
  (0 disables it);
- retry: when the provider raises an `LLMProviderError` marked `retryable`,
  wait and call again, up to `MAX_RETRIES` times. The wait is the
  provider's own hint (`retry_after_seconds`) when present, otherwise the
  next value of `BACKOFF_SECONDS`. After the last retry the error is
  raised unchanged, so the caller's per-event handling still applies.

`sleep` and `clock` are injectable so tests never really wait.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider

logger = logging.getLogger(__name__)

BACKOFF_SECONDS: tuple[float, ...] = (5.0, 15.0, 45.0)
MAX_RETRIES = len(BACKOFF_SECONDS)


class RetryingProvider(LLMProvider):
    """`LLMProvider` decorator adding call pacing and retry on transient errors."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        min_interval_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._last_call_started: float | None = None

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        retries_done = 0
        while True:
            self._pace()
            try:
                return self._inner.complete(request)
            except LLMProviderError as exc:
                if not exc.retryable or retries_done >= MAX_RETRIES:
                    raise
                delay = (
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else BACKOFF_SECONDS[retries_done]
                )
                retries_done += 1
                logger.warning(
                    "LLM call failed (%s); retry %d/%d in %.0f s",
                    exc,
                    retries_done,
                    MAX_RETRIES,
                    delay,
                )
                self._sleep(delay)

    def _pace(self) -> None:
        """Wait until `min_interval_seconds` have passed since the last call started."""
        if self._last_call_started is not None and self._min_interval_seconds > 0:
            wait = self._min_interval_seconds - (self._clock() - self._last_call_started)
            if wait > 0:
                self._sleep(wait)
        self._last_call_started = self._clock()
