"""Event verification: VERIFY.

Computes `verification_status` and `confidence_score` for a candidate
event from its cluster's articles and the `Source` metadata of the
sources they come from. Pure, in-memory: never touches the database,
never creates or updates an `Event`, never reads or writes
`Article.event_id` (MODEL B).
"""

from app.verification.event_verifier import (
    CORROBORATION_BONUS_PER_SOURCE,
    MIN_RELIABILITY_WEIGHT,
    TIER_BASE,
    VerificationResult,
    verify_cluster,
)

__all__ = [
    "CORROBORATION_BONUS_PER_SOURCE",
    "MIN_RELIABILITY_WEIGHT",
    "TIER_BASE",
    "VerificationResult",
    "verify_cluster",
]
