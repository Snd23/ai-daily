"""Deterministic ranking factors for an event (TASK-024).

`app.ranking.event_ranker.compute_importance_score` (TASK-013) consumes
eight caller-supplied factors in `[0.0, 10.0]` and deliberately computes
none of them itself. This module derives those eight values from signals
that actually exist in the database, with no LLM call, so that RANK can
run for real (docs/ARCHITECTURE.md §6, ambiguity #9).

Every factor is a *weak* signal: six of them come from `Source.categories`
tags, which describe the outlets that reported an event rather than the
event itself. Two documented constants are therefore used instead of the
extremes of the range:

    _WITH_EVIDENCE    = 7.0   a supporting signal is present
    _WITHOUT_EVIDENCE = 3.0   no supporting signal is present

Both sit either side of the 5.0 midpoint: present evidence raises a factor
above neutral without claiming certainty, and absent evidence lowers it
without claiming the opposite is true. Nothing here invents a value that
is not backed by a signal -- an unknown stays at `_WITHOUT_EVIDENCE`
rather than being guessed (CLAUDE.md §17, §41).

Ranking stays language-neutral (docs/PRD.md §38): no factor reads
generated content, and in particular `developer_relevance` is derived from
source tags, never from the Developer Impact stage, which is
language-dependent, LLM-based and explicitly unrelated to this factor
(docs/ARCHITECTURE.md §4.10).

`source_authoritativeness` is computed **independently of VERIFY**
(`app.verification.event_verifier`) -- see `_source_authoritativeness`
below. This is a corrected design (Post-Implementation Review, Finding 1):
an earlier revision reused `VerificationResult.confidence_score` for this
factor, which silently violated two explicit, already-approved rules --
`app.ranking.event_ranker`'s own module docstring ("`verification_status`,
`confidence_score`, `event_type` and category play no part in this
formula... this module does not receive them at all") and docs/PRD.md §10
("Importance and verification are separate concerns... verification_status
must not be used to artificially inflate or penalize the
importance_score"). This module now has no dependency on
`app.verification` at all.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from app.database.article import Article
from app.database.source import Source
from app.ranking.event_ranker import RankingInput

_WITH_EVIDENCE = 7.0
_WITHOUT_EVIDENCE = 3.0

# An event is "new" if its most recent article was published no more than
# this many days before the edition date. Collection runs daily
# (docs/PRD.md §27), so a story whose newest article predates the edition
# by more than two days is being re-reported rather than breaking.
_NOVELTY_RECENT_DAYS = 2

# `Source.categories` tags that evidence each topical factor. The tags are
# the free-form ones already configured in `config/sources.yaml`; the
# factor names are those of `RankingInput` (docs/PRD.md §10).
_TECHNOLOGICAL_IMPACT_TAGS = frozenset({"models", "hardware"})
_ECONOMIC_IMPACT_TAGS = frozenset({"business", "startups"})
_USER_IMPACT_TAGS = frozenset({"society", "models"})
_DEVELOPER_RELEVANCE_TAGS = frozenset({"developer"})
_SCIENTIFIC_RELEVANCE_TAGS = frozenset({"research"})
_REGULATORY_RELEVANCE_TAGS = frozenset({"regulation"})

# The four-tier source hierarchy of docs/PRD.md §3 (Tier 1 = primary/
# official sources, highest priority ... Tier 4 = community/social, lowest),
# expressed as a base authority score. Defined here on its own, not
# imported from `app.verification.event_verifier.TIER_BASE`: this factor
# must have no dependency on the VERIFY stage or on how many sources
# corroborate an event, only on the tier/reliability_weight of the sources
# themselves.
_TIER_AUTHORITY: dict[int, float] = {1: 10.0, 2: 7.0, 3: 4.0, 4: 1.0}


def build_ranking_input(
    *,
    event_id: int,
    sources: Iterable[Source],
    articles: Iterable[Article],
    reference_date: date,
) -> RankingInput:
    """Derive the eight `RankingInput` factors for one candidate event.

    Args:
        event_id: identifier carried through to `RankingInput`. It is not
            interpreted by `compute_importance_score`, which is a pure
            function of the eight factors, so a provisional value may be
            used before the `Event` row exists.
        sources: the distinct sources that reported the event.
        articles: the event's articles, read only for `published_at`.
        reference_date: the edition's date, against which novelty is
            measured.

    Returns:
        The validated `RankingInput`.

    Pure and deterministic: no I/O, no mutation of the arguments, and
    independent of the order of `sources` and `articles`. Takes no
    `VerificationResult`/`confidence_score`/`verification_status` argument
    at all -- there is structurally no way to make any of the eight
    factors depend on VERIFY's output (docs/PRD.md §10).
    """
    sources = list(sources)
    tags = {tag for source in sources for tag in source.categories}

    return RankingInput(
        event_id=event_id,
        technological_impact=_tag_evidence(tags, _TECHNOLOGICAL_IMPACT_TAGS),
        economic_impact=_tag_evidence(tags, _ECONOMIC_IMPACT_TAGS),
        user_impact=_tag_evidence(tags, _USER_IMPACT_TAGS),
        developer_relevance=_tag_evidence(tags, _DEVELOPER_RELEVANCE_TAGS),
        scientific_relevance=_tag_evidence(tags, _SCIENTIFIC_RELEVANCE_TAGS),
        regulatory_relevance=_tag_evidence(tags, _REGULATORY_RELEVANCE_TAGS),
        source_authoritativeness=_source_authoritativeness(sources),
        novelty=_novelty(articles, reference_date),
    )


def _source_authoritativeness(sources: Iterable[Source]) -> float:
    """Score the authority of the single most authoritative source reporting an event.

        = max(_TIER_AUTHORITY[s.tier] * s.reliability_weight for s in sources)

    The maximum, not a sum or an average: adding more corroborating
    sources -- even weaker ones -- never changes this factor. It measures
    how authoritative the *best* source is, never how many sources report
    the event and never how well the event was verified (docs/PRD.md §10:
    importance and verification are separate concerns). Two events backed
    by the same sources always get the same value here, regardless of
    their `verification_status`/`confidence_score`.

    Returns `0.0` for an event with no sources (should not occur in
    practice: an event always has at least one article, hence one source).
    """
    return max(
        (_TIER_AUTHORITY[source.tier] * source.reliability_weight for source in sources),
        default=0.0,
    )


def _tag_evidence(tags: set[str], evidencing: frozenset[str]) -> float:
    """Score a factor by whether any of its evidencing tags is present."""
    return _WITH_EVIDENCE if tags & evidencing else _WITHOUT_EVIDENCE


def _novelty(articles: Iterable[Article], reference_date: date) -> float:
    """Score novelty from the most recent parsable `published_at`.

    An article with no `published_at`, or with one that cannot be parsed,
    contributes nothing: the absence of a publication date is preserved as
    unknown, never treated as evidence of freshness (CLAUDE.md §17). If no
    article has a usable date, the factor stays at `_WITHOUT_EVIDENCE`.
    """
    published_dates = [
        parsed for article in articles if (parsed := _parse_date(article.published_at)) is not None
    ]
    if not published_dates:
        return _WITHOUT_EVIDENCE

    age_in_days = (reference_date - max(published_dates)).days
    return _WITH_EVIDENCE if age_in_days <= _NOVELTY_RECENT_DAYS else _WITHOUT_EVIDENCE


def _parse_date(published_at: str | None) -> date | None:
    """Parse an ISO-8601 `published_at` into a date, or `None` if unusable."""
    if published_at is None:
        return None
    try:
        return datetime.fromisoformat(published_at).date()
    except ValueError:
        return None
