"""Shared exceptions for the LLM provider subsystem (TASK-014)."""


class LLMProviderError(Exception):
    """Raised when an `LLMProvider.complete()` call fails.

    Wraps the underlying vendor SDK exception (via `raise ... from exc`)
    so callers can handle a provider failure without importing or
    catching vendor-specific exception types (CLAUDE.md §19). Never
    raised for an invalid `CompletionRequest` -- that fails earlier with
    the normal `pydantic.ValidationError`.
    """
