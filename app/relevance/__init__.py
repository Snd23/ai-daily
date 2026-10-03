"""AI relevance filter (TASK-039).

Splits the day's clusters into those about artificial intelligence and those
that are not, with one LLM call over their titles. Pure, in-memory: never
touches the database (the pipeline discards the rejected articles).
"""

from app.relevance.ai_relevance_filter import (
    AIRelevanceParseError,
    RelevanceSplit,
    filter_ai_relevant,
)

__all__ = [
    "AIRelevanceParseError",
    "RelevanceSplit",
    "filter_ai_relevant",
]
