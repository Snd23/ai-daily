"""Tests for `SourceRepository` (TASK-005).

Exercises the repository against a real, migrated in-memory SQLite database
(same fixture pattern as `tests/test_database.py`). CHECK-constraint
violations on the `source` table itself are already covered there and are
not repeated here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository


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


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SourceRepository:
    run_migrations(connection)
    return SourceRepository(connection)


# --- create / get ------------------------------------------------------


def test_create_persists_and_returns_assigned_id(repository: SourceRepository) -> None:
    created = repository.create(_make_source())

    assert created.id is not None
    fetched = repository.get_by_id(created.id)
    assert fetched == created


def test_get_by_id_returns_none_when_not_found(repository: SourceRepository) -> None:
    assert repository.get_by_id(999) is None


def test_get_by_url_returns_matching_source(repository: SourceRepository) -> None:
    created = repository.create(_make_source(url="https://example.com/feed"))

    fetched = repository.get_by_url("https://example.com/feed")

    assert fetched == created


def test_get_by_url_returns_none_when_not_found(repository: SourceRepository) -> None:
    assert repository.get_by_url("https://example.com/missing") is None


def test_categories_round_trip_through_real_sqlite(repository: SourceRepository) -> None:
    created = repository.create(_make_source(categories=["models", "business", "research"]))

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.categories == ["models", "business", "research"]


def test_last_fetched_at_is_none_on_creation(repository: SourceRepository) -> None:
    created = repository.create(_make_source())
    assert created.last_fetched_at is None


# --- list_active / list_all ---------------------------------------------


def test_list_active_excludes_deactivated_sources(repository: SourceRepository) -> None:
    active = repository.create(_make_source(name="Active", url="https://a.example/feed"))
    inactive = repository.create(
        _make_source(name="Inactive", url="https://b.example/feed", is_active=False)
    )

    active_sources = repository.list_active()

    assert active in active_sources
    assert inactive not in active_sources


def test_list_all_includes_deactivated_sources(repository: SourceRepository) -> None:
    active = repository.create(_make_source(name="Active", url="https://a.example/feed"))
    inactive = repository.create(
        _make_source(name="Inactive", url="https://b.example/feed", is_active=False)
    )

    all_sources = repository.list_all()

    assert active in all_sources
    assert inactive in all_sources


# --- update --------------------------------------------------------------


def test_update_persists_changed_fields(repository: SourceRepository) -> None:
    created = repository.create(_make_source())

    updated = created.model_copy(
        update={"reliability_weight": 0.5, "last_fetched_at": "2026-01-01T00:00:00+00:00"}
    )
    repository.update(updated)

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.reliability_weight == 0.5
    assert fetched.last_fetched_at == "2026-01-01T00:00:00+00:00"


def test_update_raises_for_unknown_id(repository: SourceRepository) -> None:
    unknown = _make_source().model_copy(update={"id": 999})
    with pytest.raises(ValueError, match="No source found"):
        repository.update(unknown)


def test_update_without_id_raises(repository: SourceRepository) -> None:
    with pytest.raises(ValueError, match="no id"):
        repository.update(_make_source())


# --- deactivate ------------------------------------------------------------


def test_deactivate_sets_is_active_false(repository: SourceRepository) -> None:
    created = repository.create(_make_source())

    repository.deactivate(created.id)  # type: ignore[arg-type]

    fetched = repository.get_by_id(created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.is_active is False
    assert fetched not in repository.list_active()


def test_deactivate_raises_for_unknown_id(repository: SourceRepository) -> None:
    with pytest.raises(ValueError, match="No source found"):
        repository.deactivate(999)
