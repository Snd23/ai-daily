"""AI generation (TASK-015, TASK-016): SUMMARIZE, AI SENZA SBATTI.

Generates reader-facing, caller-prepared content with `LLMProvider.complete()`
calls. Pure, in-memory: never touches the database, never creates or updates
an `Event`, `EventContent`, `Concept`, `ConceptTranslation` or `Edition`
(approved TASK-015/TASK-016 scope, MODEL B).
"""

from app.ai.concept_explainer import (
    ConceptExplanation,
    ConceptExplanationInput,
    ConceptExplanationParseError,
    explain_concept,
)
from app.ai.event_summarizer import (
    ArticleContext,
    EventSummary,
    EventSummaryInput,
    SummarizationParseError,
    summarize_event,
)

__all__ = [
    "ArticleContext",
    "ConceptExplanation",
    "ConceptExplanationInput",
    "ConceptExplanationParseError",
    "EventSummary",
    "EventSummaryInput",
    "SummarizationParseError",
    "explain_concept",
    "summarize_event",
]
