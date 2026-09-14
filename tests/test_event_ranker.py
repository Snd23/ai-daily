"""Tests for `app.ranking.event_ranker` (TASK-013).

Pure/in-memory only, mirroring the style of `tests/test_article_clusterer.py`:
hand-built `RankingInput` instances, no database, no `conftest.py`.
"""

from __future__ import annotations

from itertools import permutations

import pytest
from pydantic import ValidationError

from app.ranking.event_ranker import (
    RankedEvent,
    RankingInput,
    compute_importance_score,
    rank_events,
)


def _ranking_input(*, event_id: int = 1, **overrides: object) -> RankingInput:
    values: dict[str, object] = {
        "event_id": event_id,
        "technological_impact": 5.0,
        "economic_impact": 5.0,
        "user_impact": 5.0,
        "developer_relevance": 5.0,
        "scientific_relevance": 5.0,
        "regulatory_relevance": 5.0,
        "source_authoritativeness": 5.0,
        "novelty": 5.0,
    }
    values.update(overrides)
    return RankingInput(**values)  # type: ignore[arg-type]


# --- compute_importance_score: formula and weights --------------------------


def test_all_factors_at_minimum_yields_zero() -> None:
    input_ = _ranking_input(
        technological_impact=0.0,
        economic_impact=0.0,
        user_impact=0.0,
        developer_relevance=0.0,
        scientific_relevance=0.0,
        regulatory_relevance=0.0,
        source_authoritativeness=0.0,
        novelty=0.0,
    )

    assert compute_importance_score(input_) == 0.0


def test_all_factors_at_maximum_yields_ten() -> None:
    input_ = _ranking_input(
        technological_impact=10.0,
        economic_impact=10.0,
        user_impact=10.0,
        developer_relevance=10.0,
        scientific_relevance=10.0,
        regulatory_relevance=10.0,
        source_authoritativeness=10.0,
        novelty=10.0,
    )

    assert compute_importance_score(input_) == 10.0


def test_uniform_mid_value_returns_that_value() -> None:
    # Every weight applies to the same value, and the weights sum to 1.0,
    # so a uniform input must return exactly that value back.
    input_ = _ranking_input(
        technological_impact=6.0,
        economic_impact=6.0,
        user_impact=6.0,
        developer_relevance=6.0,
        scientific_relevance=6.0,
        regulatory_relevance=6.0,
        source_authoritativeness=6.0,
        novelty=6.0,
    )

    assert compute_importance_score(input_) == 6.0


def test_formula_applies_documented_weights_to_distinct_values() -> None:
    input_ = _ranking_input(
        technological_impact=10.0,  # * 0.20 = 2.0
        economic_impact=8.0,  # * 0.15 = 1.2
        user_impact=4.0,  # * 0.15 = 0.6
        developer_relevance=2.0,  # * 0.10 = 0.2
        scientific_relevance=0.0,  # * 0.10 = 0.0
        regulatory_relevance=5.0,  # * 0.10 = 0.5
        source_authoritativeness=10.0,  # * 0.10 = 1.0
        novelty=6.0,  # * 0.10 = 0.6
    )
    # sum = 2.0 + 1.2 + 0.6 + 0.2 + 0.0 + 0.5 + 1.0 + 0.6 = 6.1

    assert compute_importance_score(input_) == pytest.approx(6.1)


def test_only_technological_impact_reflects_its_own_weight() -> None:
    input_ = _ranking_input(
        technological_impact=10.0,
        economic_impact=0.0,
        user_impact=0.0,
        developer_relevance=0.0,
        scientific_relevance=0.0,
        regulatory_relevance=0.0,
        source_authoritativeness=0.0,
        novelty=0.0,
    )

    assert compute_importance_score(input_) == pytest.approx(2.0)


def test_only_novelty_reflects_its_own_weight() -> None:
    input_ = _ranking_input(
        technological_impact=0.0,
        economic_impact=0.0,
        user_impact=0.0,
        developer_relevance=0.0,
        scientific_relevance=0.0,
        regulatory_relevance=0.0,
        source_authoritativeness=0.0,
        novelty=10.0,
    )

    assert compute_importance_score(input_) == pytest.approx(1.0)


def test_result_is_not_rounded() -> None:
    # 1/3 has no exact float representation; the raw weighted sum must be
    # returned as-is, with no rounding applied (approved TASK-013 spec).
    input_ = _ranking_input(
        technological_impact=1 / 3,
        economic_impact=0.0,
        user_impact=0.0,
        developer_relevance=0.0,
        scientific_relevance=0.0,
        regulatory_relevance=0.0,
        source_authoritativeness=0.0,
        novelty=0.0,
    )

    assert compute_importance_score(input_) == (1 / 3) * 0.20


@pytest.mark.parametrize(
    "factors",
    [
        {"technological_impact": 10.0},
        {"economic_impact": 10.0},
        {"user_impact": 10.0},
        {"developer_relevance": 10.0},
        {"scientific_relevance": 10.0},
        {"regulatory_relevance": 10.0},
        {"source_authoritativeness": 10.0},
        {"novelty": 10.0},
        {},
    ],
)
def test_result_is_always_within_range(factors: dict[str, float]) -> None:
    base = {
        "technological_impact": 0.0,
        "economic_impact": 0.0,
        "user_impact": 0.0,
        "developer_relevance": 0.0,
        "scientific_relevance": 0.0,
        "regulatory_relevance": 0.0,
        "source_authoritativeness": 0.0,
        "novelty": 0.0,
    }
    base.update(factors)
    score = compute_importance_score(_ranking_input(**base))  # type: ignore[arg-type]

    assert 0.0 <= score <= 10.0


# --- RankingInput validation --------------------------------------------------


@pytest.mark.parametrize(
    "factor",
    [
        "technological_impact",
        "economic_impact",
        "user_impact",
        "developer_relevance",
        "scientific_relevance",
        "regulatory_relevance",
        "source_authoritativeness",
        "novelty",
    ],
)
def test_ranking_input_rejects_factor_below_minimum(factor: str) -> None:
    with pytest.raises(ValidationError):
        _ranking_input(**{factor: -0.01})


@pytest.mark.parametrize(
    "factor",
    [
        "technological_impact",
        "economic_impact",
        "user_impact",
        "developer_relevance",
        "scientific_relevance",
        "regulatory_relevance",
        "source_authoritativeness",
        "novelty",
    ],
)
def test_ranking_input_rejects_factor_above_maximum(factor: str) -> None:
    with pytest.raises(ValidationError):
        _ranking_input(**{factor: 10.01})


def test_ranking_input_accepts_factor_at_each_boundary() -> None:
    _ranking_input(technological_impact=0.0)
    _ranking_input(technological_impact=10.0)


def test_ranking_input_rejects_non_numeric_factor() -> None:
    with pytest.raises(ValidationError):
        _ranking_input(technological_impact="high")  # type: ignore[arg-type]


def test_ranking_input_is_frozen() -> None:
    input_ = _ranking_input()

    with pytest.raises(ValidationError):
        input_.technological_impact = 9.0  # type: ignore[misc]


def test_ranked_event_is_frozen() -> None:
    ranked = RankedEvent(event_id=1, importance_score=5.0)

    with pytest.raises(ValidationError):
        ranked.importance_score = 9.0  # type: ignore[misc]


# --- rank_events: behavior ----------------------------------------------------


def test_rank_events_with_empty_input_returns_empty_list() -> None:
    assert rank_events([]) == []


def test_rank_events_with_single_input_returns_single_result() -> None:
    input_ = _ranking_input(event_id=1, technological_impact=8.0)

    result = rank_events([input_])

    assert result == [RankedEvent(event_id=1, importance_score=compute_importance_score(input_))]


def test_rank_events_orders_by_score_descending() -> None:
    low = _ranking_input(event_id=1, technological_impact=1.0)
    high = _ranking_input(event_id=2, technological_impact=9.0)

    result = rank_events([low, high])

    assert [ranked.event_id for ranked in result] == [2, 1]


def test_rank_events_tie_breaks_by_event_id_ascending_when_scores_equal() -> None:
    a = _ranking_input(event_id=5, technological_impact=5.0)
    b = _ranking_input(event_id=2, technological_impact=5.0)
    c = _ranking_input(event_id=8, technological_impact=5.0)

    result = rank_events([a, b, c])

    assert [ranked.event_id for ranked in result] == [2, 5, 8]
    assert result[0].importance_score == result[1].importance_score == result[2].importance_score


def test_rank_events_is_deterministic_across_repeated_calls() -> None:
    inputs = [
        _ranking_input(event_id=1, technological_impact=3.0),
        _ranking_input(event_id=2, technological_impact=9.0),
        _ranking_input(event_id=3, technological_impact=6.0),
    ]

    first = rank_events(inputs)
    second = rank_events(inputs)

    assert first == second


def test_rank_events_result_is_independent_of_input_order() -> None:
    inputs = [
        _ranking_input(event_id=1, technological_impact=3.0),
        _ranking_input(event_id=2, technological_impact=9.0),
        _ranking_input(event_id=3, technological_impact=9.0),
        _ranking_input(event_id=4, technological_impact=0.0),
    ]

    reference = rank_events(inputs)

    for ordering in permutations(inputs):
        assert rank_events(list(ordering)) == reference


def test_rank_events_does_not_mutate_input_list() -> None:
    a = _ranking_input(event_id=2, technological_impact=1.0)
    b = _ranking_input(event_id=1, technological_impact=9.0)
    inputs = [a, b]

    rank_events(inputs)

    assert inputs == [a, b]


def test_rank_events_output_score_matches_compute_importance_score() -> None:
    inputs = [
        _ranking_input(event_id=1, technological_impact=4.0, novelty=7.0),
        _ranking_input(event_id=2, economic_impact=3.0, regulatory_relevance=8.0),
    ]

    result = rank_events(inputs)

    by_id = {ranked.event_id: ranked.importance_score for ranked in result}
    for item in inputs:
        assert by_id[item.event_id] == compute_importance_score(item)


def test_rank_events_with_duplicate_event_id_is_not_deduplicated() -> None:
    # Approved TASK-013 spec: rank_events does not deduplicate or validate
    # event_id -- each RankingInput is trusted to represent one candidate.
    a = _ranking_input(event_id=1, technological_impact=2.0)
    b = _ranking_input(event_id=1, technological_impact=9.0)

    result = rank_events([a, b])

    assert len(result) == 2
    assert [ranked.event_id for ranked in result] == [1, 1]
