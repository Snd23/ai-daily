"""Tests for `EditionRepository` (TASK-024).

Exercises the repository against a real, migrated in-memory SQLite
database (same fixture pattern as `tests/test_event_repository.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from app.database.connection import get_connection
from app.database.edition import EditionRecord
from app.database.edition_repository import EditionRepository
from app.database.migrations import run_migrations

_TIMESTAMP = "2026-09-16T07:00:00+02:00"


def _make_record(**overrides: Any) -> EditionRecord:
    values: dict[str, Any] = {
        "edition_number": 1,
        "date": "2026-09-16",
        "language": "it",
        "status": "draft",
        "created_at": _TIMESTAMP,
    }
    values.update(overrides)
    return EditionRecord(**values)


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    run_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


def test_next_edition_number_starts_at_one(connection: sqlite3.Connection) -> None:
    assert EditionRepository(connection).next_edition_number() == 1


def test_next_edition_number_follows_the_highest_existing_number(
    connection: sqlite3.Connection,
) -> None:
    repository = EditionRepository(connection)
    repository.create(_make_record(edition_number=7))

    assert repository.next_edition_number() == 8


def test_create_assigns_an_id_and_round_trips(connection: sqlite3.Connection) -> None:
    repository = EditionRepository(connection)

    created = repository.create(_make_record())

    assert created.id is not None
    assert repository.get_by_date_and_language("2026-09-16", "it") == created


def test_get_by_date_and_language_distinguishes_languages(
    connection: sqlite3.Connection,
) -> None:
    repository = EditionRepository(connection)
    repository.create(_make_record(edition_number=1, language="it"))
    repository.create(_make_record(edition_number=2, language="en"))

    italian = repository.get_by_date_and_language("2026-09-16", "it")
    english = repository.get_by_date_and_language("2026-09-16", "en")
    assert italian is not None and italian.edition_number == 1
    assert english is not None and english.edition_number == 2


def test_get_by_date_and_language_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert EditionRepository(connection).get_by_date_and_language("2026-09-16", "it") is None


def test_update_pdf_path_records_the_path_and_status(connection: sqlite3.Connection) -> None:
    repository = EditionRepository(connection)
    created = repository.create(_make_record())
    assert created.id is not None

    repository.update_pdf_path(created.id, "data/editions/2026-09-16-it.pdf", "published")

    stored = repository.get_by_date_and_language("2026-09-16", "it")
    assert stored is not None
    assert stored.pdf_path == "data/editions/2026-09-16-it.pdf"
    assert stored.status == "published"


def test_update_pdf_path_rejects_an_unknown_edition(connection: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="No edition found with id=999"):
        EditionRepository(connection).update_pdf_path(999, "somewhere.pdf", "published")


def test_a_duplicate_edition_number_is_rejected_by_the_schema(
    connection: sqlite3.Connection,
) -> None:
    repository = EditionRepository(connection)
    repository.create(_make_record(edition_number=1, language="it"))

    with pytest.raises(sqlite3.IntegrityError):
        repository.create(_make_record(edition_number=1, language="en"))


def test_an_unsupported_language_is_rejected_by_the_model() -> None:
    with pytest.raises(ValidationError):
        _make_record(language="fr")
