"""Tests for `app.verification.event_verifier` (VERIFY).

Pure/in-memory only, mirroring the style of `tests/test_article_clusterer.py`
and `tests/test_event_ranker.py`: hand-built `Article`/`Source` instances,
no database, no `conftest.py`.
"""

from __future__ import annotations

from itertools import permutations

import pytest
from pydantic import ValidationError

from app.database.article import Article
from app.database.source import Source
from app.verification.event_verifier import (
    CORROBORATION_BONUS_PER_SOURCE,
    MIN_RELIABILITY_WEIGHT,
    TIER_BASE,
    VerificationResult,
    verify_cluster,
)


def _article(*, id: int, source_id: int, **overrides: object) -> Article:
    values: dict[str, object] = {
        "id": id,
        "source_id": source_id,
        "title": "Title",
        "url": f"https://example.com/{id}",
        "published_at": None,
        "fetched_at": "2026-09-01T12:00:00+00:00",
        "raw_excerpt": "excerpt",
    }
    values.update(overrides)
    return Article(**values)  # type: ignore[arg-type]


def _source(*, id: int, tier: int, reliability_weight: float, **overrides: object) -> Source:
    values: dict[str, object] = {
        "id": id,
        "name": f"Source {id}",
        "type": "rss",
        "url": f"https://example.com/source/{id}",
        "tier": tier,
        "categories": [],
        "reliability_weight": reliability_weight,
        "is_active": True,
        "last_fetched_at": None,
    }
    values.update(overrides)
    return Source(**values)  # type: ignore[arg-type]


# --- basic status -------------------------------------------------------


def test_single_tier1_source_is_verified() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"


def test_single_tier2_source_is_partially_verified() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=2, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "PARTIALLY_VERIFIED"


def test_two_distinct_tier2_sources_are_verified() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=2, reliability_weight=1.0),
        2: _source(id=2, tier=2, reliability_weight=1.0),
    }

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"


def test_single_tier3_source_is_unverified() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=3, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"


def test_two_distinct_tier3_sources_are_partially_verified() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=3, reliability_weight=1.0),
        2: _source(id=2, tier=3, reliability_weight=1.0),
    }

    result = verify_cluster(articles, sources)

    assert result.verification_status == "PARTIALLY_VERIFIED"


def test_tier4_only_is_unverified() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=4, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"


def test_many_distinct_tier4_sources_never_reach_verified_or_partially_verified() -> None:
    articles = [_article(id=i, source_id=i) for i in range(1, 6)]
    sources = {i: _source(id=i, tier=4, reliability_weight=1.0) for i in range(1, 6)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"


# --- source distinctness -------------------------------------------------


def test_multiple_articles_same_source_count_as_one_source() -> None:
    single = [_article(id=1, source_id=1)]
    many = [_article(id=i, source_id=1) for i in range(1, 5)]
    sources = {1: _source(id=1, tier=1, reliability_weight=1.0)}

    result_single = verify_cluster(single, sources)
    result_many = verify_cluster(many, sources)

    assert result_single == result_many


def test_repeated_articles_from_same_source_do_not_increase_confidence() -> None:
    articles = [_article(id=i, source_id=1) for i in range(1, 5)]
    sources = {1: _source(id=1, tier=1, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.confidence_score == 10.0


def test_two_distinct_sources_are_counted_separately() -> None:
    # Two distinct Tier 2 sources reach VERIFIED (n2 >= 2) and the second
    # one contributes a corroboration bonus -- proof they are counted as
    # two, not collapsed into one.
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=2, reliability_weight=1.0),
        2: _source(id=2, tier=2, reliability_weight=1.0),
    }

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"
    assert result.confidence_score == 7.0 + CORROBORATION_BONUS_PER_SOURCE


# --- reliability gate -----------------------------------------------------


def test_tier1_reliability_1_0_is_eligible() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"
    assert result.confidence_score == 10.0


def test_tier1_reliability_at_threshold_is_eligible() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=MIN_RELIABILITY_WEIGHT)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"
    assert result.confidence_score == 5.0


def test_tier1_reliability_just_below_threshold_is_excluded() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=0.49)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"
    assert result.confidence_score == 0.0


def test_tier1_low_reliability_is_excluded() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=0.20)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"
    assert result.confidence_score == 0.0


def test_tier2_reliability_just_below_threshold_is_excluded() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=2, reliability_weight=0.49)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"
    assert result.confidence_score == 0.0


def test_ineligible_source_is_ignored_even_when_another_is_eligible() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=2, reliability_weight=1.0),
        2: _source(id=2, tier=2, reliability_weight=0.30),
    }

    result = verify_cluster(articles, sources)

    # Only source 1 counts: n2 == 1, not 2 -- PARTIALLY_VERIFIED, not VERIFIED.
    assert result.verification_status == "PARTIALLY_VERIFIED"
    assert result.confidence_score == 7.0


def test_ineligible_tier1_source_does_not_prevent_verification_by_others() -> None:
    articles = [
        _article(id=1, source_id=1),
        _article(id=2, source_id=2),
        _article(id=3, source_id=3),
    ]
    sources = {
        1: _source(id=1, tier=1, reliability_weight=0.30),
        2: _source(id=2, tier=2, reliability_weight=1.0),
        3: _source(id=3, tier=2, reliability_weight=0.9),
    }

    result = verify_cluster(articles, sources)

    assert result.verification_status == "VERIFIED"
    # The ineligible Tier 1 source contributes nothing: identical to the
    # two eligible Tier 2 sources alone.
    assert result.confidence_score == 7.0 + CORROBORATION_BONUS_PER_SOURCE


def test_many_sources_below_threshold_yield_unverified_and_zero_confidence() -> None:
    articles = [_article(id=i, source_id=i) for i in range(1, 11)]
    sources = {i: _source(id=i, tier=1, reliability_weight=0.49) for i in range(1, 11)}

    result = verify_cluster(articles, sources)

    assert result.verification_status == "UNVERIFIED"
    assert result.confidence_score == 0.0


# --- confidence: tier_base * reliability_weight ---------------------------


@pytest.mark.parametrize(
    ("tier", "reliability_weight", "expected"),
    [
        (1, 1.0, 10.0),
        (1, 0.5, 5.0),
        (2, 1.0, 7.0),
        (2, 0.5, 3.5),
        (3, 1.0, 4.0),
        (3, 0.5, 2.0),
        (4, 1.0, 1.0),
        (4, 0.5, 0.5),
    ],
)
def test_confidence_score_for_single_source(
    tier: int, reliability_weight: float, expected: float
) -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=tier, reliability_weight=reliability_weight)}

    result = verify_cluster(articles, sources)

    assert result.confidence_score == expected
    assert TIER_BASE[tier] * reliability_weight == expected


def test_confidence_score_adds_corroboration_bonus_for_second_tier2_source() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=2, reliability_weight=1.0),
        2: _source(id=2, tier=2, reliability_weight=0.9),
    }

    result = verify_cluster(articles, sources)

    assert result.confidence_score == 7.0 + CORROBORATION_BONUS_PER_SOURCE


def test_confidence_score_is_capped_at_ten() -> None:
    articles = [_article(id=i, source_id=i) for i in range(1, 5)]
    sources = {
        1: _source(id=1, tier=1, reliability_weight=1.0),
        2: _source(id=2, tier=2, reliability_weight=1.0),
        3: _source(id=3, tier=2, reliability_weight=0.9),
        4: _source(id=4, tier=1, reliability_weight=0.7),
    }

    result = verify_cluster(articles, sources)

    assert result.confidence_score == 10.0


def test_confidence_score_is_zero_when_no_source_is_eligible() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=4, reliability_weight=0.1)}

    result = verify_cluster(articles, sources)

    assert result.confidence_score == 0.0
    assert result.verification_status == "UNVERIFIED"


# --- determinism -----------------------------------------------------------


def test_repeated_call_with_same_input_produces_the_same_result() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    sources = {
        1: _source(id=1, tier=1, reliability_weight=0.8),
        2: _source(id=2, tier=2, reliability_weight=0.6),
    }

    first = verify_cluster(articles, sources)
    second = verify_cluster(articles, sources)

    assert first == second


def test_result_is_independent_of_article_order() -> None:
    a = _article(id=1, source_id=1)
    b = _article(id=2, source_id=2)
    c = _article(id=3, source_id=1)
    sources = {
        1: _source(id=1, tier=1, reliability_weight=0.8),
        2: _source(id=2, tier=2, reliability_weight=0.6),
    }

    reference = verify_cluster([a, b, c], sources)

    for ordering in permutations([a, b, c]):
        assert verify_cluster(list(ordering), sources) == reference


def test_result_is_independent_of_sources_mapping_key_order() -> None:
    articles = [_article(id=1, source_id=1), _article(id=2, source_id=2)]
    source_1 = _source(id=1, tier=1, reliability_weight=0.8)
    source_2 = _source(id=2, tier=2, reliability_weight=0.6)

    forward = verify_cluster(articles, {1: source_1, 2: source_2})
    backward = verify_cluster(articles, {2: source_2, 1: source_1})

    assert forward == backward


def test_published_at_has_no_effect_on_the_result() -> None:
    # No temporal proxy is used to approximate DEVELOPING (approved spec):
    # varying published_at must never change status or confidence.
    sources = {1: _source(id=1, tier=2, reliability_weight=0.8)}

    recent = verify_cluster(
        [_article(id=1, source_id=1, published_at="2026-09-15T00:00:00+00:00")], sources
    )
    old = verify_cluster(
        [_article(id=1, source_id=1, published_at="2020-01-01T00:00:00+00:00")], sources
    )
    missing = verify_cluster([_article(id=1, source_id=1, published_at=None)], sources)

    assert recent == old == missing


# --- validation --------------------------------------------------------------


def test_empty_articles_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        verify_cluster([], {})


def test_missing_source_raises_key_error() -> None:
    articles = [_article(id=1, source_id=1)]

    with pytest.raises(KeyError):
        verify_cluster(articles, {})


def test_verification_result_rejects_confidence_score_above_ten() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(verification_status="VERIFIED", confidence_score=10.01)


def test_verification_result_rejects_confidence_score_below_zero() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(verification_status="VERIFIED", confidence_score=-0.01)


def test_verification_result_rejects_invalid_verification_status() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(verification_status="CONFIRMED", confidence_score=5.0)  # type: ignore[arg-type]


def test_hedging_constraints_default_to_an_empty_list() -> None:
    articles = [_article(id=1, source_id=1)]
    sources = {1: _source(id=1, tier=1, reliability_weight=1.0)}

    result = verify_cluster(articles, sources)

    assert result.hedging_constraints == []
