"""Event importance ranking (TASK-013): RANK.

Computes `importance_score` for candidate events from eight caller-supplied
factors, using a fixed, deterministic weighted formula. Pure, in-memory:
never touches the database, never creates or updates an `Event`, never
reads or writes `Article.event_id` (approved TASK-013 scope).
"""

from app.ranking.event_ranker import (
    RankedEvent,
    RankingInput,
    compute_importance_score,
    rank_events,
)

__all__ = [
    "RankedEvent",
    "RankingInput",
    "compute_importance_score",
    "rank_events",
]
