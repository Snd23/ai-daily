"""AI generation (TASK-015): SUMMARIZE.

Generates the reader-facing title and summary of one event in one language
from caller-prepared data, with one `LLMProvider.complete()` call. Pure,
in-memory: never touches the database, never creates or updates an `Event`,
never persists `EventContent` (approved TASK-015 scope, MODEL B).
"""

from app.ai.event_summarizer import (
    ArticleContext,
    EventSummary,
    EventSummaryInput,
    SummarizationParseError,
    summarize_event,
)

__all__ = [
    "ArticleContext",
    "EventSummary",
    "EventSummaryInput",
    "SummarizationParseError",
    "summarize_event",
]
