"""Tests for `EventContentRepository` (TASK-024).

Exercises the repository against a real, migrated in-memory SQLite
database (same fixture pattern as `tests/test_event_repository.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from app.database.connection import get_connection
from app.database.event import Event
from app.database.event_content import EventContent
from app.database.event_content_repository import EventContentRepository
from app.database.event_repository import EventRepository
from app.database.migrations import run_migrations

_TIMESTAMP = "2026-09-16T07:00:00+02:00"


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    run_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def event_id(connection: sqlite3.Connection) -> int:
    event = EventRepository(connection).create(
        Event(
            verification_status="VERIFIED",
            confidence_score=8.0,
            importance_score=7.0,
            event_type="standard",
            created_at=_TIMESTAMP,
        )
    )
    assert event.id is not None
    return event.id


def test_upsert_then_get_round_trips_every_field(
    connection: sqlite3.Connection, event_id: int
) -> None:
    repository = EventContentRepository(connection)
    content = EventContent(
        event_id=event_id,
        language="it",
        title="Titolo",
        summary="Riassunto.",
        structured_content='{"developer_impact": {"has_developer_impact": false}}',
    )

    repository.upsert(content)

    assert repository.get(event_id, "it") == content


def test_get_returns_none_for_a_language_with_no_content(
    connection: sqlite3.Connection, event_id: int
) -> None:
    repository = EventContentRepository(connection)
    repository.upsert(
        EventContent(event_id=event_id, language="it", title="Titolo", summary="Riassunto.")
    )

    assert repository.get(event_id, "en") is None


def test_upsert_replaces_the_row_for_the_same_event_and_language(
    connection: sqlite3.Connection, event_id: int
) -> None:
    """Re-running generation must not duplicate or fail on an existing row."""
    repository = EventContentRepository(connection)
    repository.upsert(
        EventContent(event_id=event_id, language="it", title="Primo", summary="Primo riassunto.")
    )

    repository.upsert(
        EventContent(event_id=event_id, language="it", title="Secondo", summary="Secondo.")
    )

    stored = repository.get(event_id, "it")
    assert stored is not None
    assert stored.title == "Secondo"
    rows = connection.execute("SELECT COUNT(*) FROM event_content").fetchone()
    assert rows[0] == 1


def test_the_same_event_can_hold_both_languages(
    connection: sqlite3.Connection, event_id: int
) -> None:
    repository = EventContentRepository(connection)
    repository.upsert(
        EventContent(event_id=event_id, language="it", title="Titolo", summary="Riassunto.")
    )
    repository.upsert(
        EventContent(event_id=event_id, language="en", title="Title", summary="Summary.")
    )

    italian = repository.get(event_id, "it")
    english = repository.get(event_id, "en")
    assert italian is not None and italian.title == "Titolo"
    assert english is not None and english.title == "Title"


def test_an_unsupported_language_is_rejected_by_the_model() -> None:
    with pytest.raises(ValidationError):
        EventContent(event_id=1, language="fr", title="Titre", summary="Resume.")


@pytest.mark.parametrize("field", ["title", "summary"])
def test_blank_generated_text_is_rejected(field: str) -> None:
    values = {"event_id": 1, "language": "it", "title": "Titolo", "summary": "Riassunto."}
    values[field] = "   "

    with pytest.raises(ValidationError):
        EventContent(**values)  # type: ignore[arg-type]
