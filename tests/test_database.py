"""Tests for the database connection and migration infrastructure (TASK-004).

Covers: schema creation, `schema_migrations` bookkeeping, migration
idempotency and atomicity, foreign key enforcement, CHECK constraints,
composite primary keys, UNIQUE constraints, the approved nullable columns,
and the category seed data.

No entity repositories exist yet (TODO.md, Milestone 2 onward): these tests
talk to the schema directly via `sqlite3`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.database.connection import get_connection
from app.database.migrations import run_migrations

EXPECTED_TABLES = {
    "schema_migrations",
    "source",
    "event",
    "article",
    "category",
    "event_category",
    "concept",
    "concept_translation",
    "event_content",
    "edition",
}

_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _insert_source(connection: sqlite3.Connection, **overrides: object) -> int:
    values: dict[str, object] = {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/blog/rss",
        "tier": 1,
        "categories": "[]",
        "reliability_weight": 1.0,
        "is_active": 1,
        "last_fetched_at": None,
    }
    values.update(overrides)
    cursor = connection.execute(
        """
        INSERT INTO source
            (name, type, url, tier, categories, reliability_weight, is_active, last_fetched_at)
        VALUES
            (:name, :type, :url, :tier, :categories, :reliability_weight, :is_active,
             :last_fetched_at)
        """,
        values,
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _insert_event(connection: sqlite3.Connection, **overrides: object) -> int:
    values: dict[str, object] = {
        "verification_status": "VERIFIED",
        "confidence_score": 8.0,
        "importance_score": 7.0,
        "event_type": "standard",
        "future_date": None,
        "created_at": _TIMESTAMP,
    }
    values.update(overrides)
    cursor = connection.execute(
        """
        INSERT INTO event
            (verification_status, confidence_score, importance_score, event_type,
             future_date, created_at)
        VALUES
            (:verification_status, :confidence_score, :importance_score, :event_type,
             :future_date, :created_at)
        """,
        values,
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def migrated_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    run_migrations(connection)
    return connection


# --- get_connection ---------------------------------------------------------


def test_get_connection_enables_foreign_keys(connection: sqlite3.Connection) -> None:
    value = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert value == 1


def test_get_connection_creates_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "ai_daily.db"
    conn = get_connection(f"sqlite:///{db_path.as_posix()}")
    try:
        assert db_path.parent.is_dir()
    finally:
        conn.close()


def test_get_connection_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported database URL"):
        get_connection("postgresql://localhost/db")


# --- migrations: schema creation and bookkeeping ----------------------------


def test_migrations_create_all_expected_tables(migrated_connection: sqlite3.Connection) -> None:
    assert EXPECTED_TABLES <= _table_names(migrated_connection)


def test_schema_migrations_records_applied_migration(
    migrated_connection: sqlite3.Connection,
) -> None:
    rows = migrated_connection.execute("SELECT filename FROM schema_migrations").fetchall()
    assert ("0001_initial_schema.sql",) in rows


def test_running_migrations_twice_is_idempotent(migrated_connection: sqlite3.Connection) -> None:
    second_run = run_migrations(migrated_connection)
    assert second_run == []

    count = migrated_connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE filename = ?",
        ("0001_initial_schema.sql",),
    ).fetchone()[0]
    assert count == 1

    category_count = migrated_connection.execute("SELECT COUNT(*) FROM category").fetchone()[0]
    assert category_count == 10


def test_failed_migration_is_rolled_back_and_not_recorded(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_broken.sql").write_text(
        "CREATE TABLE ok_table (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO this_table_does_not_exist (id) VALUES (1);\n",
        encoding="utf-8",
    )

    conn = get_connection("sqlite:///:memory:")
    try:
        with pytest.raises(sqlite3.OperationalError):
            run_migrations(conn, migrations_dir=migrations_dir)

        assert "ok_table" not in _table_names(conn)
        assert conn.execute("SELECT filename FROM schema_migrations").fetchall() == []
    finally:
        conn.close()


# --- category seed ------------------------------------------------------


def test_category_seed_contains_the_ten_approved_categories(
    migrated_connection: sqlite3.Connection,
) -> None:
    rows = migrated_connection.execute(
        "SELECT slug, canonical_name FROM category ORDER BY id"
    ).fetchall()

    assert rows == [
        ("top_stories", "TOP STORIES"),
        ("models_llm", "MODELS & LLM"),
        ("big_tech_business", "BIG TECH & BUSINESS"),
        ("ai_research", "AI RESEARCH"),
        ("ai_developers", "AI FOR DEVELOPERS"),
        ("robotics", "ROBOTICS"),
        ("regulation", "AI & REGULATION"),
        ("society", "AI & SOCIETY"),
        ("hardware", "AI HARDWARE"),
        ("startups", "STARTUPS"),
    ]


# --- foreign keys ------------------------------------------------------


def test_foreign_keys_are_enforced(migrated_connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO article (source_id, title, url, published_at, fetched_at, raw_excerpt)
            VALUES (999, 'Title', 'https://example.com/a', :ts, :ts, 'excerpt')
            """,
            {"ts": _TIMESTAMP},
        )


# --- CHECK constraints ------------------------------------------------------


@pytest.mark.parametrize(("column", "value"), [("type", "ftp"), ("tier", 5), ("is_active", 2)])
def test_source_check_constraints_reject_invalid_values(
    migrated_connection: sqlite3.Connection, column: str, value: object
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_source(migrated_connection, **{column: value})


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("verification_status", "MAYBE"),
        ("confidence_score", 11.0),
        ("importance_score", -1.0),
        ("event_type", "unexpected"),
    ],
)
def test_event_check_constraints_reject_invalid_values(
    migrated_connection: sqlite3.Connection, column: str, value: object
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_event(migrated_connection, **{column: value})


def test_article_status_check_constraint_rejects_invalid_value(
    migrated_connection: sqlite3.Connection,
) -> None:
    source_id = _insert_source(migrated_connection)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO article
                (source_id, title, url, published_at, fetched_at, raw_excerpt, status)
            VALUES (:source_id, 'Title', 'https://example.com/x', :ts, :ts, 'excerpt', 'unknown')
            """,
            {"source_id": source_id, "ts": _TIMESTAMP},
        )


def test_language_check_constraints_reject_unsupported_languages(
    migrated_connection: sqlite3.Connection,
) -> None:
    event_id = _insert_event(migrated_connection)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            "INSERT INTO event_content (event_id, language, title, summary) "
            "VALUES (?, 'fr', 't', 's')",
            (event_id,),
        )

    concept_id = migrated_connection.execute(
        "INSERT INTO concept (slug, tags) VALUES ('token', '[]')"
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO concept_translation
                (concept_id, language, technical_definition, simple_explanation, example,
                 why_it_matters, one_liner)
            VALUES (?, 'de', 'x', 'x', 'x', 'x', 'x')
            """,
            (concept_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO edition (edition_number, date, language, status, created_at)
            VALUES (1, '2026-01-01', 'fr', 'draft', ?)
            """,
            (_TIMESTAMP,),
        )


# --- composite primary keys -------------------------------------------------


def test_event_content_composite_primary_key_rejects_duplicates(
    migrated_connection: sqlite3.Connection,
) -> None:
    event_id = _insert_event(migrated_connection)
    migrated_connection.execute(
        "INSERT INTO event_content (event_id, language, title, summary) VALUES (?, 'it', 't', 's')",
        (event_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            "INSERT INTO event_content (event_id, language, title, summary) "
            "VALUES (?, 'it', 't2', 's2')",
            (event_id,),
        )


def test_event_category_composite_primary_key_rejects_duplicates(
    migrated_connection: sqlite3.Connection,
) -> None:
    event_id = _insert_event(migrated_connection)
    category_id = migrated_connection.execute("SELECT id FROM category LIMIT 1").fetchone()[0]
    migrated_connection.execute(
        "INSERT INTO event_category (event_id, category_id, is_primary) VALUES (?, ?, 1)",
        (event_id, category_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            "INSERT INTO event_category (event_id, category_id, is_primary) VALUES (?, ?, 0)",
            (event_id, category_id),
        )


def test_concept_translation_composite_primary_key_rejects_duplicates(
    migrated_connection: sqlite3.Connection,
) -> None:
    concept_id = migrated_connection.execute(
        "INSERT INTO concept (slug, tags) VALUES ('rag', '[]')"
    ).lastrowid
    insert_sql = """
        INSERT INTO concept_translation
            (concept_id, language, technical_definition, simple_explanation, example,
             why_it_matters, one_liner)
        VALUES (?, 'it', 'x', 'x', 'x', 'x', 'x')
    """
    migrated_connection.execute(insert_sql, (concept_id,))
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(insert_sql, (concept_id,))


# --- nullable columns --------------------------------------------------


def test_article_nullable_fields_accept_null(migrated_connection: sqlite3.Connection) -> None:
    source_id = _insert_source(migrated_connection)
    migrated_connection.execute(
        """
        INSERT INTO article (source_id, title, url, published_at, fetched_at, raw_excerpt)
        VALUES (?, 'Title', 'https://example.com/nullable', ?, ?, 'excerpt')
        """,
        (source_id, _TIMESTAMP, _TIMESTAMP),
    )

    row = migrated_connection.execute(
        "SELECT event_id, normalized_text, content_hash, language FROM article WHERE url = ?",
        ("https://example.com/nullable",),
    ).fetchone()
    assert row == (None, None, None, None)


def test_edition_nullable_fields_accept_null(migrated_connection: sqlite3.Connection) -> None:
    migrated_connection.execute(
        """
        INSERT INTO edition (edition_number, date, language, status, created_at)
        VALUES (1, '2026-01-01', 'it', 'draft', ?)
        """,
        (_TIMESTAMP,),
    )

    row = migrated_connection.execute(
        "SELECT pdf_path, concept_deep_dive_id, concept_term_id FROM edition "
        "WHERE edition_number = 1"
    ).fetchone()
    assert row == (None, None, None)


# --- UNIQUE constraints ------------------------------------------------


def test_article_url_is_unique(migrated_connection: sqlite3.Connection) -> None:
    source_id = _insert_source(migrated_connection)
    insert_sql = """
        INSERT INTO article (source_id, title, url, published_at, fetched_at, raw_excerpt)
        VALUES (?, 'Title', 'https://example.com/dup', ?, ?, 'excerpt')
    """
    migrated_connection.execute(insert_sql, (source_id, _TIMESTAMP, _TIMESTAMP))
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(insert_sql, (source_id, _TIMESTAMP, _TIMESTAMP))


def test_category_slug_is_unique(migrated_connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            "INSERT INTO category (slug, canonical_name) VALUES ('top_stories', 'DUPLICATE')"
        )


def test_edition_number_is_unique(migrated_connection: sqlite3.Connection) -> None:
    insert_sql = """
        INSERT INTO edition (edition_number, date, language, status, created_at)
        VALUES (1, ?, 'it', 'draft', ?)
    """
    migrated_connection.execute(insert_sql, ("2026-01-01", _TIMESTAMP))
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(insert_sql, ("2026-01-02", _TIMESTAMP))
