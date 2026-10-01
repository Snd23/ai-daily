"""Shared exceptions for the LLM provider subsystem (TASK-014)."""


class LLMProviderError(Exception):
    """Raised when an `LLMProvider.complete()` call fails.

    Wraps the underlying vendor SDK exception (via `raise ... from exc`)
    so callers can handle a provider failure without importing or
    catching vendor-specific exception types (CLAUDE.md §19). Never
    raised for an invalid `CompletionRequest` -- that fails earlier with
    the normal `pydantic.ValidationError`.

    `retryable` is True for transient failures (rate limit, temporary
    overload) that a later identical call may survive (TASK-033);
    `retry_after_seconds` is the provider's own suggested wait, when it
    gives one. Both default to "not retryable, no hint".
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
