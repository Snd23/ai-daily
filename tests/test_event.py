"""Tests for the `Event` model (TASK-011).

Pure model/validation behavior — no database involved (see
`tests/test_event_repository.py` for DB-backed behavior). Scope is limited
to persistence: these tests confirm the model matches the `event` table's
existing CHECK constraints (TASK-004); no verification logic exists to test.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.database.event import Event

_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _make_event(**overrides: object) -> Event:
    values: dict[str, Any] = {
        "verification_status": "VERIFIED",
        "confidence_score": 8.0,
        "importance_score": 7.0,
        "event_type": "standard",
        "future_date": None,
        "created_at": _TIMESTAMP,
    }
    values.update(overrides)
    return Event(**values)


def test_event_accepts_valid_fields() -> None:
    event = _make_event()
    assert event.id is None
    assert event.verification_status == "VERIFIED"
    assert event.confidence_score == 8.0
    assert event.importance_score == 7.0
    assert event.event_type == "standard"
    assert event.future_date is None
    assert event.created_at == _TIMESTAMP


# --- verification_status ----------------------------------------------------


@pytest.mark.parametrize(
    "valid_status", ["VERIFIED", "PARTIALLY_VERIFIED", "DEVELOPING", "UNVERIFIED"]
)
def test_event_accepts_every_verification_status(valid_status: str) -> None:
    event = _make_event(verification_status=valid_status)
    assert event.verification_status == valid_status


@pytest.mark.parametrize("invalid_status", ["verified", "CONFIRMED", "", "MAYBE"])
def test_event_rejects_invalid_verification_status(invalid_status: str) -> None:
    with pytest.raises(ValidationError):
        _make_event(verification_status=invalid_status)


# --- event_type --------------------------------------------------------------


@pytest.mark.parametrize("valid_type", ["standard", "research", "developer_relevant"])
def test_event_accepts_every_event_type(valid_type: str) -> None:
    event = _make_event(event_type=valid_type)
    assert event.event_type == valid_type


@pytest.mark.parametrize("invalid_type", ["Standard", "opinion", ""])
def test_event_rejects_invalid_event_type(invalid_type: str) -> None:
    with pytest.raises(ValidationError):
        _make_event(event_type=invalid_type)


# --- confidence_score / importance_score (0.0-10.0 inclusive) ---------------


@pytest.mark.parametrize("valid_score", [0.0, 10.0, 5.5])
def test_event_accepts_confidence_score_within_range(valid_score: float) -> None:
    event = _make_event(confidence_score=valid_score)
    assert event.confidence_score == valid_score


@pytest.mark.parametrize("invalid_score", [-0.01, 10.01, -1.0, 11.0])
def test_event_rejects_confidence_score_out_of_range(invalid_score: float) -> None:
    with pytest.raises(ValidationError):
        _make_event(confidence_score=invalid_score)


@pytest.mark.parametrize("valid_score", [0.0, 10.0, 5.5])
def test_event_accepts_importance_score_within_range(valid_score: float) -> None:
    event = _make_event(importance_score=valid_score)
    assert event.importance_score == valid_score


@pytest.mark.parametrize("invalid_score", [-0.01, 10.01, -1.0, 11.0])
def test_event_rejects_importance_score_out_of_range(invalid_score: float) -> None:
    with pytest.raises(ValidationError):
        _make_event(importance_score=invalid_score)


def test_event_rejects_non_numeric_confidence_score() -> None:
    with pytest.raises(ValidationError):
        _make_event(confidence_score="high")


def test_event_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Event(event_type="standard", created_at=_TIMESTAMP)  # type: ignore[call-arg]


# --- future_date --------------------------------------------------------------


def test_event_accepts_none_future_date() -> None:
    event = _make_event(future_date=None)
    assert event.future_date is None


def test_event_accepts_future_date_value() -> None:
    event = _make_event(future_date="2026-03-01")
    assert event.future_date == "2026-03-01"
