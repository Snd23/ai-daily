"""Article deduplication (TASK-009).

Groups `pending` articles that share the same `content_hash` (produced by
`app.normalization`, TASK-008) and marks every article in a group except
one as a duplicate of the other. Distinct from clustering articles from
different sources about the same event (docs/ARCHITECTURE.md §2's
DEDUPLICATE vs. CLUSTER EVENTS stages) -- that is a separate, later stage.
"""

from app.deduplication.article_deduplicator import (
    DeduplicationBatchResult,
    DuplicateGroup,
    deduplicate_pending_articles,
    plan_deduplication,
)

__all__ = [
    "DeduplicationBatchResult",
    "DuplicateGroup",
    "deduplicate_pending_articles",
    "plan_deduplication",
]
