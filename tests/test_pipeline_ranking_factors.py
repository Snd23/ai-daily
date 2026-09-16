"""Tests for `app.pipeline.ranking_factors` (TASK-024).

Pure functions: no database, no network, no LLM.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.database.article import Article
from app.database.source import Source
from app.pipeline.ranking_factors import build_ranking_input
from app.ranking.event_ranker import compute_importance_score
from app.verification.event_verifier import verify_cluster

_EDITION_DATE = date(2026, 9, 16)
_WITH_EVIDENCE = 7.0
_WITHOUT_EVIDENCE = 3.0


def _make_source(**overrides: Any) -> Source:
    values: dict[str, Any] = {
        "id": 1,
        "name": "Example",
        "type": "rss",
        "url": "https://example.com/feed",
        "tier": 1,
        "categories": [],
        "reliability_weight": 1.0,
        "is_active": True,
    }
    values.update(overrides)
    return Source(**values)


def _make_article(**overrides: Any) -> Article:
    values: dict[str, Any] = {
        "id": 1,
        "source_id": 1,
        "title": "Example",
        "url": "https://example.com/a",
        "published_at": "2026-09-16T08:00:00+00:00",
        "fetched_at": "2026-09-16T09:00:00+00:00",
        "raw_excerpt": "<p>Example</p>",
    }
    values.update(overrides)
    return Article(**values)


def _build(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "event_id": 1,
        "sources": [_make_source()],
        "articles": [_make_article()],
        "reference_date": _EDITION_DATE,
    }
    values.update(overrides)
    return build_ranking_input(**values)


@pytest.mark.parametrize(
    ("tag", "factor"),
    [
        ("models", "technological_impact"),
        ("hardware", "technological_impact"),
        ("business", "economic_impact"),
        ("startups", "economic_impact"),
        ("society", "user_impact"),
        ("models", "user_impact"),
        ("developer", "developer_relevance"),
        ("research", "scientific_relevance"),
        ("regulation", "regulatory_relevance"),
    ],
)
def test_a_tag_raises_the_factor_it_evidences(tag: str, factor: str) -> None:
    with_tag = _build(sources=[_make_source(categories=[tag])])
    without_tag = _build(sources=[_make_source(categories=[])])

    assert getattr(with_tag, factor) == _WITH_EVIDENCE
    assert getattr(without_tag, factor) == _WITHOUT_EVIDENCE


# --- source_authoritativeness (Post-Implementation Review, Finding 1) ------
#
# Corrected: this factor must be derived only from Source.tier and
# Source.reliability_weight, and must be fully independent of VERIFY's
# confidence_score/verification_status (docs/PRD.md §10: "Importance and
# verification are separate concerns").


def test_source_authoritativeness_is_derived_from_tier_and_reliability_weight() -> None:
    """Test 1 -- the factor must actually depend on tier and reliability_weight."""
    tier_1 = _build(sources=[_make_source(tier=1, reliability_weight=1.0)])
    tier_4 = _build(sources=[_make_source(tier=4, reliability_weight=1.0)])
    assert tier_1.source_authoritativeness > tier_4.source_authoritativeness

    high_weight = _build(sources=[_make_source(tier=2, reliability_weight=1.0)])
    low_weight = _build(sources=[_make_source(tier=2, reliability_weight=0.5)])
    assert high_weight.source_authoritativeness > low_weight.source_authoritativeness


def test_build_ranking_input_has_no_verification_parameter() -> None:
    """Structural guard: the function must offer no path at all for a caller
    to pass VerificationResult/confidence_score/verification_status --
    the independence required by PRD §10 is enforced by the signature
    itself, not merely by convention.
    """
    import inspect

    parameters = inspect.signature(build_ranking_input).parameters
    assert "confidence_score" not in parameters
    assert "verification_status" not in parameters
    assert "verification" not in parameters


def test_source_authoritativeness_is_independent_of_verification_result() -> None:
    """Test 2 -- same sources must yield the same source_authoritativeness
    however differently VERIFY would have scored the event's corroboration.

    `verify_cluster`'s confidence_score is itself a pure function of the
    distinct source set, so two clusters sharing the same *set* of sources
    always get the same confidence_score too -- there is no way, through
    the real pipeline, to vary confidence_score while holding the source
    set fixed. That is exactly the point: this factor is computed with no
    reference to VERIFY at all, so there is no VERIFY output that could
    ever perturb it, unlike the previous, incorrect implementation.
    """
    same_sources = [_make_source(tier=2, reliability_weight=0.9)]

    first_call = _build(sources=same_sources, event_id=1)
    second_call = _build(sources=same_sources, event_id=2)

    assert first_call.source_authoritativeness == second_call.source_authoritativeness


def test_source_authoritativeness_uses_the_best_source_not_a_sum() -> None:
    """More corroborating sources must never inflate this factor."""
    one_source = _build(sources=[_make_source(tier=1, reliability_weight=1.0)])
    two_sources = _build(
        sources=[
            _make_source(id=1, tier=1, reliability_weight=1.0),
            _make_source(id=2, tier=2, reliability_weight=0.9),
        ]
    )

    assert one_source.source_authoritativeness == two_sources.source_authoritativeness


@pytest.mark.parametrize(
    ("stronger", "weaker"),
    [
        ({"tier": 1, "reliability_weight": 1.0}, {"tier": 2, "reliability_weight": 1.0}),
        ({"tier": 2, "reliability_weight": 1.0}, {"tier": 3, "reliability_weight": 1.0}),
        ({"tier": 3, "reliability_weight": 1.0}, {"tier": 4, "reliability_weight": 1.0}),
        ({"tier": 1, "reliability_weight": 1.0}, {"tier": 1, "reliability_weight": 0.5}),
    ],
)
def test_authority_ordering_matches_the_repositorys_tier_hierarchy(
    stronger: dict[str, Any], weaker: dict[str, Any]
) -> None:
    """Test 3 -- a more authoritative source must never score lower."""
    stronger_result = _build(sources=[_make_source(**stronger)])
    weaker_result = _build(sources=[_make_source(**weaker)])

    assert stronger_result.source_authoritativeness >= weaker_result.source_authoritativeness


def test_source_authoritativeness_stays_within_the_ranking_input_range() -> None:
    tier_1_full_weight = _build(sources=[_make_source(tier=1, reliability_weight=1.0)])
    tier_4_low_weight = _build(sources=[_make_source(tier=4, reliability_weight=0.3)])

    assert 0.0 <= tier_1_full_weight.source_authoritativeness <= 10.0
    assert 0.0 <= tier_4_low_weight.source_authoritativeness <= 10.0


def test_novelty_is_high_for_a_recently_published_article() -> None:
    recent = _build(articles=[_make_article(published_at="2026-09-15T08:00:00+00:00")])

    assert recent.novelty == _WITH_EVIDENCE


def test_novelty_is_low_for_an_old_article() -> None:
    old = _build(articles=[_make_article(published_at="2026-09-01T08:00:00+00:00")])

    assert old.novelty == _WITHOUT_EVIDENCE


def test_novelty_uses_the_most_recent_article_of_the_event() -> None:
    mixed = _build(
        articles=[
            _make_article(id=1, published_at="2026-08-01T08:00:00+00:00"),
            _make_article(id=2, published_at="2026-09-16T08:00:00+00:00"),
        ]
    )

    assert mixed.novelty == _WITH_EVIDENCE


def test_a_missing_publication_date_is_not_treated_as_freshness() -> None:
    """An absent date stays unknown; it is never counted as recent."""
    undated = _build(articles=[_make_article(published_at=None)])

    assert undated.novelty == _WITHOUT_EVIDENCE


def test_an_unparsable_publication_date_is_ignored_rather_than_raising() -> None:
    unparsable = _build(articles=[_make_article(published_at="last Tuesday")])

    assert unparsable.novelty == _WITHOUT_EVIDENCE


def test_factors_are_independent_of_source_and_article_order() -> None:
    sources = [
        _make_source(id=1, categories=["research"]),
        _make_source(id=2, categories=["business"]),
    ]
    articles = [
        _make_article(id=1, published_at="2026-09-16T08:00:00+00:00"),
        _make_article(id=2, published_at="2026-08-01T08:00:00+00:00"),
    ]

    forward = _build(sources=sources, articles=articles)
    backward = _build(sources=list(reversed(sources)), articles=list(reversed(articles)))

    assert forward == backward


def test_the_produced_factors_are_accepted_by_the_ranking_formula() -> None:
    """Every factor must land in the [0, 10] range `RankingInput` validates."""
    ranking_input = _build(
        sources=[
            _make_source(
                tier=1, reliability_weight=1.0, categories=["models", "business", "developer"]
            )
        ],
    )

    score = compute_importance_score(ranking_input)

    assert 0.0 <= score <= 10.0


def test_more_evidence_produces_a_higher_score_than_less() -> None:
    rich = compute_importance_score(
        _build(
            sources=[
                _make_source(
                    tier=1,
                    reliability_weight=1.0,
                    categories=["models", "business", "developer", "research", "regulation"],
                )
            ],
        )
    )
    poor = compute_importance_score(
        _build(sources=[_make_source(tier=4, reliability_weight=0.3, categories=["community"])])
    )

    assert rich > poor


def test_importance_score_is_independent_of_verification_confidence_score() -> None:
    """Test 4 -- directly demonstrates docs/PRD.md §10: two events backed by
    sources with the same best-source authority must get the same
    importance_score, even when VERIFY would score their corroboration
    very differently.

    `single_source` and `double_sourced` both have a Tier 2,
    reliability_weight=0.9 source as their strongest source (same topical
    tags, same publication date, so every tag-evidence and novelty factor
    is held constant too); `double_sourced` additionally has a *second*,
    equally-weak Tier 2 source. `verify_cluster` is run on both (using the
    real VERIFY stage, not a stub) to prove this genuinely changes
    verification_status and confidence_score -- then the same two source
    sets are fed to ranking, proving importance_score does not move.
    """
    strongest_source = _make_source(
        id=1, tier=2, reliability_weight=0.9, categories=["models", "business"]
    )
    second_source = _make_source(
        id=2, tier=2, reliability_weight=0.9, categories=["models", "business"]
    )
    articles_single = [_make_article(id=1, source_id=1, published_at="2026-09-16T08:00:00+00:00")]
    articles_double = [
        _make_article(id=1, source_id=1, published_at="2026-09-16T08:00:00+00:00"),
        _make_article(id=2, source_id=2, published_at="2026-09-16T08:00:00+00:00"),
    ]

    single_verification = verify_cluster(articles_single, {1: strongest_source})
    double_verification = verify_cluster(
        articles_double, {1: strongest_source, 2: second_source}
    )
    # Prove the premise: VERIFY really does treat these two scenarios
    # differently.
    assert single_verification.verification_status == "PARTIALLY_VERIFIED"
    assert double_verification.verification_status == "VERIFIED"
    assert single_verification.confidence_score != double_verification.confidence_score

    single_source_score = compute_importance_score(
        _build(sources=[strongest_source], articles=articles_single)
    )
    double_sourced_score = compute_importance_score(
        _build(sources=[strongest_source, second_source], articles=articles_double)
    )

    assert single_source_score == double_sourced_score
