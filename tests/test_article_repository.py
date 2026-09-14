"""Tests for `ArticleRepository` (TASK-007; extended TASK-008).

Exercises the repository against a real, migrated in-memory SQLite
database (same fixture pattern as `tests/test_source_repository.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository


def _make_article(**overrides: object) -> Article:
    values: dict[str, object] = {
        "source_id": 1,
        "title": "OpenAI ships a new model",
        "url": "https://openai.com/news/example",
        "published_at": "2026-09-01T10:00:00+00:00",
        "fetched_at": "2026-09-01T12:00:00+00:00",
        "raw_excerpt": "A short summary of the announcement.",
    }
    values.update(overrides)
    return Article(**values)  # type: ignore[arg-type]


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> ArticleRepository:
    run_migrations(connection)
    return ArticleRepository(connection)


@pytest.fixture
def source_id(connection: sqlite3.Connection) -> int:
    # article.source_id is a foreign key: every test needs a real source row.
    created = SourceRepository(connection).create(
        Source(
            name="OpenAI",
            type="rss",
            url="https://openai.com/news/rss.xml",
            tier=1,
            categories=["models"],
            reliability_weight=1.0,
            is_active=True,
        )
    )
    assert created.id is not None
    return created.id


# --- create / get_by_url -------------------------------------------------


def test_create_persists_and_returns_assigned_id(
    repository: ArticleRepository, source_id: int
) -> None:
    created = repository.create(_make_article(source_id=source_id))

    assert created.id is not None
    fetched = repository.get_by_url(created.url)
    assert fetched == created


def test_create_defaults_status_to_pending(repository: ArticleRepository, source_id: int) -> None:
    created = repository.create(_make_article(source_id=source_id))

    assert created.status == "pending"


def test_create_preserves_missing_published_at(
    repository: ArticleRepository, source_id: int
) -> None:
    created = repository.create(_make_article(source_id=source_id, published_at=None))

    fetched = repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.published_at is None


def test_get_by_url_returns_none_when_not_found(repository: ArticleRepository) -> None:
    assert repository.get_by_url("https://example.com/missing") is None


# --- duplicate url handling (TASK-007 spec §11) ---------------------------


def test_existing_article_url_is_detected_via_get_by_url(
    repository: ArticleRepository, source_id: int
) -> None:
    created = repository.create(_make_article(source_id=source_id))

    assert repository.get_by_url(created.url) is not None


def test_create_raises_on_duplicate_url(repository: ArticleRepository, source_id: int) -> None:
    repository.create(_make_article(source_id=source_id))

    with pytest.raises(sqlite3.IntegrityError):
        repository.create(_make_article(source_id=source_id))


def test_check_then_create_pattern_skips_duplicate_without_a_second_row(
    repository: ArticleRepository, source_id: int
) -> None:
    # This is the exact pattern RssCollector uses (get_by_url, then create
    # only if nothing was found) — proving the two approved primitives are
    # sufficient to avoid ever creating a duplicate row.
    article = _make_article(source_id=source_id)
    first_id: int | None = None

    for _ in range(2):
        existing = repository.get_by_url(article.url)
        if existing is None:
            first_id = repository.create(article).id
        else:
            assert existing.id == first_id  # second pass finds the same row, creates nothing


# --- list_pending (TASK-008 spec §7) ---------------------------------------


def _set_status(connection: sqlite3.Connection, article_id: int, status: str) -> None:
    # ArticleRepository deliberately provides no way to write `status`
    # (TASK-008 must never touch it) -- raw SQL is the only way to get a
    # non-'pending' row into the DB for these tests.
    connection.execute("UPDATE article SET status = ? WHERE id = ?", (status, article_id))
    connection.commit()


def test_list_pending_returns_only_pending_articles(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    pending = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    processed = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _set_status(connection, processed.id, "processed")  # type: ignore[arg-type]

    result = repository.list_pending()

    assert [a.id for a in result] == [pending.id]


def test_list_pending_excludes_every_non_pending_status(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    for status in ("processed", "discarded", "error"):
        article = repository.create(
            _make_article(source_id=source_id, url=f"https://x.example/{status}")
        )
        _set_status(connection, article.id, status)  # type: ignore[arg-type]

    assert repository.list_pending() == []


def test_list_pending_orders_by_id(repository: ArticleRepository, source_id: int) -> None:
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/first"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/second"))

    result = repository.list_pending()

    assert [a.id for a in result] == [first.id, second.id]


def test_list_pending_returns_empty_list_when_nothing_pending(
    repository: ArticleRepository,
) -> None:
    assert repository.list_pending() == []


# --- update_normalization (TASK-008 spec §8) -------------------------------


def test_update_normalization_persists_the_three_fields(
    repository: ArticleRepository, source_id: int
) -> None:
    created = repository.create(_make_article(source_id=source_id))

    repository.update_normalization(
        created.id,  # type: ignore[arg-type]
        normalized_text="clean text",
        content_hash="abc123",
        language="en",
    )

    fetched = repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.normalized_text == "clean text"
    assert fetched.content_hash == "abc123"
    assert fetched.language == "en"


def test_update_normalization_accepts_null_language(
    repository: ArticleRepository, source_id: int
) -> None:
    created = repository.create(_make_article(source_id=source_id))

    repository.update_normalization(
        created.id,  # type: ignore[arg-type]
        normalized_text="clean text",
        content_hash="abc123",
        language=None,
    )

    fetched = repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.language is None


def test_update_normalization_does_not_modify_other_fields(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    created = repository.create(
        _make_article(
            source_id=source_id,
            title="Original Title",
            url="https://example.com/untouched",
            published_at="2026-09-01T10:00:00+00:00",
            fetched_at="2026-09-01T12:00:00+00:00",
            raw_excerpt="Original raw excerpt",
        )
    )
    # Simulate later pipeline stages having already set event_id/status,
    # so the test can prove update_normalization truly leaves them alone
    # rather than merely leaving already-NULL/default values untouched.
    connection.execute(
        "INSERT INTO event (verification_status, confidence_score, importance_score, "
        "event_type, created_at) VALUES ('VERIFIED', 5.0, 5.0, 'standard', "
        "'2026-09-01T00:00:00+00:00')"
    )
    connection.commit()
    event_id = connection.execute("SELECT id FROM event").fetchone()[0]
    connection.execute(
        "UPDATE article SET event_id = ?, status = 'processed' WHERE id = ?",
        (event_id, created.id),
    )
    connection.commit()

    repository.update_normalization(
        created.id,  # type: ignore[arg-type]
        normalized_text="clean text",
        content_hash="abc123",
        language="en",
    )

    fetched = repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.status == "processed"
    assert fetched.event_id == event_id
    assert fetched.published_at == "2026-09-01T10:00:00+00:00"
    assert fetched.fetched_at == "2026-09-01T12:00:00+00:00"
    assert fetched.raw_excerpt == "Original raw excerpt"
    assert fetched.title == "Original Title"
    assert fetched.url == "https://example.com/untouched"
    assert fetched.source_id == source_id


def test_update_normalization_raises_for_nonexistent_article(
    repository: ArticleRepository,
) -> None:
    with pytest.raises(ValueError, match="No article found"):
        repository.update_normalization(
            999_999, normalized_text="x", content_hash="y", language=None
        )
