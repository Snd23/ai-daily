"""Event importance ranking (TASK-013).

Computes `importance_score` (docs/PRD.md §10, CLAUDE.md §25) for a set of
candidate events from eight independent, caller-supplied factors, using a
fixed, deterministic weighted formula (approved TASK-013 spec). This module
is pure and in-memory only: no `sqlite3`, no repository, no `Event`, no
`LLMProvider`, no network call. It never creates or updates a persisted
`Event` row and never reads or writes `Article.event_id` -- consistent
with the MODEL B boundary already established by `app.clustering`
(`Event` is only ever persisted once VERIFY/CLASSIFY/RANK have all
produced real values; this module only produces the RANK contribution).

`RankingInput.event_id` is simply the identifier of the event a ranking
applies to. This module does not interpret it, does not deduplicate on
it, and does not assume it refers to an already-persisted `Event.id` --
whether it does is a matter for whichever future stage constructs a
`RankingInput`. Each `RankingInput` is assumed by the caller to represent
a single candidate event; passing two `RankingInput` with the same
`event_id` is not validated against or specially handled here.

Approved TASK-013 formula and weights (do not change without a new
approved spec):

    importance_score =
        technological_impact      * 0.20 +
        economic_impact           * 0.15 +
        user_impact                * 0.15 +
        developer_relevance        * 0.10 +
        scientific_relevance       * 0.10 +
        regulatory_relevance       * 0.10 +
        source_authoritativeness   * 0.10 +
        novelty                    * 0.10

The weights sum to exactly 1.00, and every factor is validated to
0.0-10.0 inclusive, so the weighted sum is a convex combination of
values in [0.0, 10.0] and therefore always lands in [0.0, 10.0] itself --
no clamping is needed. The result is returned as-is, with no rounding:
presentation/rounding is explicitly out of scope for TASK-013 (approved
spec) and left to whichever future stage displays the score.

`verification_status`, `confidence_score`, `event_type` and category
play no part in this formula (approved TASK-013 spec): this module does
not receive them at all.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_TECHNOLOGICAL_IMPACT_WEIGHT = 0.20
_ECONOMIC_IMPACT_WEIGHT = 0.15
_USER_IMPACT_WEIGHT = 0.15
_DEVELOPER_RELEVANCE_WEIGHT = 0.10
_SCIENTIFIC_RELEVANCE_WEIGHT = 0.10
_REGULATORY_RELEVANCE_WEIGHT = 0.10
_SOURCE_AUTHORITATIVENESS_WEIGHT = 0.10
_NOVELTY_WEIGHT = 0.10


class RankingInput(BaseModel):
    """The eight factors (docs/PRD.md §10, CLAUDE.md §25) for one candidate event.

    Immutable and validated: every factor must be a number in
    [0.0, 10.0] inclusive, matching the range already used for
    `Event.confidence_score`/`Event.importance_score`
    (`app/database/event.py`). A missing, out-of-range or non-numeric
    factor fails validation rather than being silently corrected or
    clamped (CLAUDE.md §41).
    """

    model_config = ConfigDict(frozen=True)

    event_id: int
    technological_impact: float = Field(ge=0.0, le=10.0)
    economic_impact: float = Field(ge=0.0, le=10.0)
    user_impact: float = Field(ge=0.0, le=10.0)
    developer_relevance: float = Field(ge=0.0, le=10.0)
    scientific_relevance: float = Field(ge=0.0, le=10.0)
    regulatory_relevance: float = Field(ge=0.0, le=10.0)
    source_authoritativeness: float = Field(ge=0.0, le=10.0)
    novelty: float = Field(ge=0.0, le=10.0)


class RankedEvent(BaseModel):
    """The ranking result for one event: its id and computed `importance_score`.

    Immutable. `importance_score` is not rounded (approved TASK-013
    spec): it is the raw float produced by `compute_importance_score`.
    """

    model_config = ConfigDict(frozen=True)

    event_id: int
    importance_score: float = Field(ge=0.0, le=10.0)


def compute_importance_score(input: RankingInput) -> float:
    """Compute `importance_score` for `input` using the approved fixed formula.

    Pure: no I/O, no mutation of `input`. Deterministic: the same
    `RankingInput` always produces the same score. The result is not
    rounded (approved TASK-013 spec).
    """
    return (
        input.technological_impact * _TECHNOLOGICAL_IMPACT_WEIGHT
        + input.economic_impact * _ECONOMIC_IMPACT_WEIGHT
        + input.user_impact * _USER_IMPACT_WEIGHT
        + input.developer_relevance * _DEVELOPER_RELEVANCE_WEIGHT
        + input.scientific_relevance * _SCIENTIFIC_RELEVANCE_WEIGHT
        + input.regulatory_relevance * _REGULATORY_RELEVANCE_WEIGHT
        + input.source_authoritativeness * _SOURCE_AUTHORITATIVENESS_WEIGHT
        + input.novelty * _NOVELTY_WEIGHT
    )


def rank_events(inputs: list[RankingInput]) -> list[RankedEvent]:
    """Score every `RankingInput` in `inputs` and sort the results.

    Ordering (approved TASK-013 spec): `importance_score` descending,
    `event_id` ascending as a deterministic tie-break.

    Pure: no I/O, no repository, no `Event`. Does not mutate `inputs` or
    any element of it (every `RankingInput`/`RankedEvent` is immutable).
    Deterministic and independent of the order of `inputs`: an empty
    list returns an empty list, and a single input returns a single
    result.
    """
    ranked = [
        RankedEvent(event_id=item.event_id, importance_score=compute_importance_score(item))
        for item in inputs
    ]
    return sorted(
        ranked, key=lambda ranked_event: (-ranked_event.importance_score, ranked_event.event_id)
    )
