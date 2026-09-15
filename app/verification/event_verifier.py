"""Event verification: VERIFY.

Computes `verification_status` and `confidence_score` (docs/PRD.md §4,
CLAUDE.md §13-15) for a single candidate event -- the articles of one
`ArticleCluster` (`app.clustering.article_clusterer`, CLUSTER EVENTS) plus
the `Source` metadata of the sources they come from. Pure, in-memory:
never touches the database, never creates or updates an `Event`, never
reads or writes `Article.event_id`/`status`/`duplicate_of` (MODEL B,
docs/ARCHITECTURE.md §4.7) -- the same boundary already established by
`app.clustering` and `app.ranking`.

Distinct from `app.ranking.event_ranker` (RANK, importance) and from
CLASSIFY (not implemented): this module never computes `importance_score`
and never assigns a category. It never calls an LLM and never reads
article content: `verification_status` and `confidence_score` are derived
deterministically from source metadata alone (`Source.tier`,
`Source.reliability_weight`).

Reliability gate -- a `Source` counts as evidence only if
`reliability_weight >= MIN_RELIABILITY_WEIGHT`. A `Source` below this
threshold is completely ignored: it contributes to neither
`verification_status` nor `confidence_score`, does not count as
corroboration, and cannot by itself make an event `VERIFIED` or
`PARTIALLY_VERIFIED`. If no eligible `Source` remains, the result is
`UNVERIFIED` with `confidence_score = 0.0` -- a normal outcome ("no
sufficiently reliable source is available"), not an error.

Source counting is always by distinct `source_id`, never by article
count: several articles from the same `Source` count once (article
volume is never corroboration, CLAUDE.md §16).

`verification_status` (n1/n2/n3 = distinct eligible sources of that tier):

    VERIFIED            if n1 >= 1 or n2 >= 2
    PARTIALLY_VERIFIED  elif n2 == 1 or n3 >= 2
    UNVERIFIED          otherwise

Tier 4 never contributes to reaching `VERIFIED` or `PARTIALLY_VERIFIED`,
regardless of how many distinct Tier 4 sources are present (docs/PRD.md
§3: Tier 4 must never be the sole confirmation of a fact -- here that
extends to any count of Tier 4 sources alone). `DEVELOPING` remains a
valid `VerificationStatus` value but this module never produces it: it
describes whether an event is still unfolding, a signal not derivable
from a single tier/reliability snapshot -- no temporal proxy (e.g.
`published_at` spread) is used to approximate it.

`confidence_score` is a deterministic measure of the structural strength
of the sourcing evidence, not a probability that the event is true:

    source_strength(s) = TIER_BASE[s.tier] * s.reliability_weight   (eligible sources only)
    best = max(source_strength(s) for s in eligible)
    authoritative_extra = count of eligible sources with tier in {1, 2},
                           excluding the single source that achieves `best`
    confidence_score = min(10.0, best + authoritative_extra * CORROBORATION_BONUS_PER_SOURCE)

`reliability_weight` has exactly two effects here: the eligibility gate
above, and this multiplicative role inside `source_strength`. Once a
`Source` is eligible, its exact `reliability_weight` never further
changes `verification_status` -- only the gate itself does.

`hedging_constraints` is always `[]` in this implementation: marker-based
hedging detection was proposed (docs/ARCHITECTURE.md §4.4) but is
explicitly deferred (the required Italian/English marker lists are not
approved). The field exists so the output shape already matches what
`app.ai.event_summarizer.EventSummaryInput.hedging_constraints` consumes;
only the internal derivation is deferred, not the field itself.

Input is fully prepared by the caller: `sources` is a mapping of
`source_id` to `Source`, built by the orchestration -- this module never
opens a database connection or repository, the same pattern already used
by `app.deduplication.article_deduplicator.plan_deduplication`'s
`source_tiers` parameter.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.database.article import Article
from app.database.event import VerificationStatus
from app.database.source import Source

MIN_RELIABILITY_WEIGHT = 0.50

TIER_BASE: dict[int, float] = {1: 10.0, 2: 7.0, 3: 4.0, 4: 1.0}
CORROBORATION_BONUS_PER_SOURCE = 1.5

_AUTHORITATIVE_TIERS = frozenset({1, 2})


class VerificationResult(BaseModel):
    """The outcome of verifying one candidate event (one cluster of articles).

    Immutable. Carries no `event_id`: no `Event` exists yet at this stage
    (MODEL B) -- the caller is responsible for associating this result
    with the cluster it was computed from.
    """

    model_config = ConfigDict(frozen=True)

    verification_status: VerificationStatus
    confidence_score: float = Field(ge=0.0, le=10.0)
    hedging_constraints: list[str] = Field(default_factory=list)


def verify_cluster(articles: list[Article], sources: Mapping[int, Source]) -> VerificationResult:
    """Verify one candidate event from its cluster's articles and their sources.

    Args:
        articles: the articles of a single candidate event (e.g. one
            `ArticleCluster.articles`). Must be non-empty.
        sources: `Source` metadata keyed by `source_id`, covering every
            `article.source_id` in `articles`. Built by the caller --
            this function never reads a database or repository.

    Returns:
        A `VerificationResult`. `hedging_constraints` is always `[]` (see
        module docstring).

    Raises:
        ValueError: if `articles` is empty.
        KeyError: if some `article.source_id` is not a key of `sources`.

    Pure and deterministic: no I/O, no mutation of `articles`/`sources`.
    Independent of the order of `articles`, and of any iteration order of
    `sources` (only ever looked up by key).
    """
    if not articles:
        raise ValueError("articles must not be empty")

    distinct_sources = _distinct_sources(articles, sources)
    eligible_sources = _eligible_sources(distinct_sources)

    return VerificationResult(
        verification_status=_determine_status(eligible_sources),
        confidence_score=_compute_confidence(eligible_sources),
        hedging_constraints=[],
    )


def _distinct_sources(articles: list[Article], sources: Mapping[int, Source]) -> list[Source]:
    """Return the distinct `Source`s referenced by `articles`, by `source_id`.

    Several articles sharing the same `source_id` contribute a single
    entry -- article volume is never corroboration (CLAUDE.md §16).
    """
    seen: set[int] = set()
    distinct: list[Source] = []
    for article in articles:
        if article.source_id not in seen:
            seen.add(article.source_id)
            distinct.append(sources[article.source_id])
    return distinct


def _eligible_sources(distinct_sources: list[Source]) -> list[Source]:
    """Apply the reliability gate: keep only sources at or above the threshold."""
    return [
        source for source in distinct_sources if source.reliability_weight >= MIN_RELIABILITY_WEIGHT
    ]


def _determine_status(eligible_sources: list[Source]) -> VerificationStatus:
    """Map the eligible distinct sources to a `verification_status`.

    See the module docstring for the approved rule. `DEVELOPING` is never
    returned.
    """
    n1 = sum(1 for source in eligible_sources if source.tier == 1)
    n2 = sum(1 for source in eligible_sources if source.tier == 2)
    n3 = sum(1 for source in eligible_sources if source.tier == 3)

    if n1 >= 1 or n2 >= 2:
        return "VERIFIED"
    if n2 == 1 or n3 >= 2:
        return "PARTIALLY_VERIFIED"
    return "UNVERIFIED"


def _compute_confidence(eligible_sources: list[Source]) -> float:
    """Compute `confidence_score` from the eligible distinct sources.

    See the module docstring for the approved formula. Not a probability:
    a deterministic measure of sourcing strength, capped at 10.0.
    """
    if not eligible_sources:
        return 0.0

    best_source = max(eligible_sources, key=_source_strength)
    best = _source_strength(best_source)

    authoritative_extra = sum(
        1
        for source in eligible_sources
        if source.tier in _AUTHORITATIVE_TIERS and source is not best_source
    )

    return min(10.0, best + authoritative_extra * CORROBORATION_BONUS_PER_SOURCE)


def _source_strength(source: Source) -> float:
    return TIER_BASE[source.tier] * source.reliability_weight
