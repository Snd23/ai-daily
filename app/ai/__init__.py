"""AI generation (TASK-015, TASK-016, TASK-018): SUMMARIZE, AI SENZA SBATTI, DEVELOPER IMPACT.

Generates reader-facing, caller-prepared content with `LLMProvider.complete()`
calls. Pure, in-memory: never touches the database, never creates or updates
an `Event`, `EventContent`, `Concept`, `ConceptTranslation` or `Edition`
(approved TASK-015/TASK-016/TASK-018 scope, MODEL B).
"""

from app.ai.concept_explainer import (
    ConceptExplanation,
    ConceptExplanationInput,
    ConceptExplanationParseError,
    explain_concept,
)
from app.ai.developer_impact import (
    DeveloperImpact,
    DeveloperImpactInput,
    DeveloperImpactParseError,
    analyze_developer_impact,
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
    "DeveloperImpact",
    "DeveloperImpactInput",
    "DeveloperImpactParseError",
    "EventSummary",
    "EventSummaryInput",
    "SummarizationParseError",
    "analyze_developer_impact",
    "explain_concept",
    "summarize_event",
]
