"""Tests for the `Source` model (TASK-005).

Pure model/validation behavior — no database involved (see
`tests/test_source_repository.py` for DB-backed behavior).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.database.source import Source, decode_categories, encode_categories


def _make_source(**overrides: object) -> Source:
    values: dict[str, object] = {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/blog/rss",
        "tier": 1,
        "categories": ["models", "business"],
        "reliability_weight": 1.0,
        "is_active": True,
        "last_fetched_at": None,
    }
    values.update(overrides)
    return Source(**values)


def test_source_accepts_valid_fields() -> None:
    source = _make_source()
    assert source.id is None
    assert source.name == "OpenAI"
    assert source.type == "rss"
    assert source.tier == 1
    assert source.categories == ["models", "business"]
    assert source.is_active is True


@pytest.mark.parametrize("invalid_type", ["ftp", "RSS", ""])
def test_source_rejects_invalid_type(invalid_type: str) -> None:
    with pytest.raises(ValidationError):
        _make_source(type=invalid_type)


@pytest.mark.parametrize("invalid_tier", [0, 5, -1])
def test_source_rejects_invalid_tier(invalid_tier: int) -> None:
    with pytest.raises(ValidationError):
        _make_source(tier=invalid_tier)


# --- reliability_weight (TASK-010) -----------------------------------------


@pytest.mark.parametrize("valid_weight", [0.0, 1.0, 0.5])
def test_source_accepts_reliability_weight_within_range(valid_weight: float) -> None:
    source = _make_source(reliability_weight=valid_weight)
    assert source.reliability_weight == valid_weight


@pytest.mark.parametrize("invalid_weight", [-0.01, 1.01])
def test_source_rejects_reliability_weight_out_of_range(invalid_weight: float) -> None:
    with pytest.raises(ValidationError):
        _make_source(reliability_weight=invalid_weight)


def test_source_rejects_non_numeric_reliability_weight() -> None:
    with pytest.raises(ValidationError):
        _make_source(reliability_weight="high")


def test_source_rejects_missing_reliability_weight() -> None:
    values = {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/blog/rss",
        "tier": 1,
        "categories": ["models", "business"],
        "is_active": True,
        "last_fetched_at": None,
    }
    with pytest.raises(ValidationError):
        Source(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", ["", "   "])
def test_source_rejects_blank_name(blank: str) -> None:
    with pytest.raises(ValidationError):
        _make_source(name=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_source_rejects_blank_url(blank: str) -> None:
    with pytest.raises(ValidationError):
        _make_source(url=blank)


def test_categories_round_trip_through_json() -> None:
    categories = ["models", "business", "research"]
    assert decode_categories(encode_categories(categories)) == categories


def test_categories_round_trip_handles_empty_list() -> None:
    assert decode_categories(encode_categories([])) == []
