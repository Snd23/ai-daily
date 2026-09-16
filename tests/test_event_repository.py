"""Tests for `EventRepository` (TASK-011).

Exercises the repository against a real, migrated in-memory SQLite database
(same fixture pattern as `tests/test_source_repository.py`). CHECK-constraint
violations on the `event` table itself are already covered in
`tests/test_database.py` and are not repeated here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from app.database.connection import get_connection
from app.database.event import Event
from app.database.event_repository import EventRepository
from app.database.migrations import run_migrations

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


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> EventRepository:
    run_migrations(connection)
    return EventRepository(connection)


# --- create / get_by_id ------------------------------------------------------


def test_create_persists_and_returns_assigned_id(repository: EventRepository) -> None:
    created = repository.create(_make_event())

    assert created.id is not None
    fetched = repository.get_by_id(created.id)
    assert fetched == created


def test_get_by_id_returns_none_when_not_found(repository: EventRepository) -> None:
    assert repository.get_by_id(999) is None


def test_create_ignores_supplied_id(repository: EventRepository) -> None:
    created = repository.create(_make_event().model_copy(update={"id": 999}))
    assert created.id != 999
    assert repository.get_by_id(999) is None


# --- field round-trip ---------------------------------------------------------


@pytest.mark.parametrize(
    "status", ["VERIFIED", "PARTIALLY_VERIFIED", "DEVELOPING", "UNVERIFIED"]
)
def test_verification_status_round_trips(repository: EventRepository, status: str) -> None:
    created = repository.create(_make_event(verification_status=status))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.verification_status == status


@pytest.mark.parametrize("score", [0.0, 10.0, 6.25])
def test_confidence_score_round_trips(repository: EventRepository, score: float) -> None:
    created = repository.create(_make_event(confidence_score=score))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.confidence_score == score


@pytest.mark.parametrize("score", [0.0, 10.0, 6.25])
def test_importance_score_round_trips(repository: EventRepository, score: float) -> None:
    created = repository.create(_make_event(importance_score=score))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.importance_score == score


def test_future_date_round_trips_as_none(repository: EventRepository) -> None:
    created = repository.create(_make_event(future_date=None))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.future_date is None


def test_future_date_round_trips_as_value(repository: EventRepository) -> None:
    created = repository.create(_make_event(future_date="2026-03-01"))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.future_date == "2026-03-01"


def test_list_by_created_date_returns_events_of_that_day_only(
    repository: EventRepository,
) -> None:
    today = repository.create(_make_event(created_at="2026-09-16T07:00:00+02:00"))
    later_same_day = repository.create(_make_event(created_at="2026-09-16T23:59:59+02:00"))
    repository.create(_make_event(created_at="2026-09-15T07:00:00+02:00"))

    found = repository.list_by_created_date("2026-09-16")

    assert [event.id for event in found] == [today.id, later_same_day.id]


def test_list_by_created_date_returns_nothing_for_a_day_with_no_event(
    repository: EventRepository,
) -> None:
    repository.create(_make_event(created_at="2026-09-15T07:00:00+02:00"))

    assert repository.list_by_created_date("2026-09-16") == []
