"""Tests for `ArticleRepository` (TASK-007; extended TASK-008, TASK-009).

Exercises the repository against a real, migrated in-memory SQLite
database (same fixture pattern as `tests/test_source_repository.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta

import pytest

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

# `_make_article`'s default `published_at` is same-day as this reference
# date, so every pre-existing `list_clusterable` test below (none of which
# is about freshness) stays decoupled from TASK-028's window with
# `lookback_days=0`.
_REFERENCE_DATE = date(2026, 9, 1)


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


def test_update_normalization_does_not_modify_duplicate_of(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type, list-item]

    repository.update_normalization(
        duplicate.id,  # type: ignore[arg-type]
        normalized_text="clean text",
        content_hash="abc123",
        language="en",
    )

    fetched = repository.get_by_url(duplicate.url)
    assert fetched is not None
    assert fetched.duplicate_of == canonical.id
    assert fetched.status == "discarded"


# --- duplicate_of / create (TASK-009 spec §5, §6) --------------------------


def test_create_leaves_duplicate_of_null(repository: ArticleRepository, source_id: int) -> None:
    created = repository.create(_make_article(source_id=source_id))

    assert created.duplicate_of is None
    fetched = repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.duplicate_of is None


# --- list_deduplication_candidates (TASK-009 spec §4, §8) -------------------


def _normalize(
    repository: ArticleRepository,
    article_id: int,
    *,
    content_hash: str,
    normalized_text: str = "normalized text",
) -> None:
    repository.update_normalization(
        article_id, normalized_text=normalized_text, content_hash=content_hash, language="en"
    )


def test_list_deduplication_candidates_groups_by_content_hash(
    repository: ArticleRepository, source_id: int
) -> None:
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _normalize(repository, first.id, content_hash="hash-1")  # type: ignore[arg-type]
    _normalize(repository, second.id, content_hash="hash-1")  # type: ignore[arg-type]

    result = repository.list_deduplication_candidates()

    assert [article.id for article in result] == [first.id, second.id]


def test_list_deduplication_candidates_excludes_hash_shared_by_only_one_article(
    repository: ArticleRepository, source_id: int
) -> None:
    only = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    _normalize(repository, only.id, content_hash="unique-hash")  # type: ignore[arg-type]

    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_excludes_null_content_hash(
    repository: ArticleRepository, source_id: int
) -> None:
    # Two never-normalized articles: content_hash is NULL for both, but SQL
    # NULL is never equal to NULL, so they must never be grouped together.
    repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_excludes_empty_content_hash(
    repository: ArticleRepository, source_id: int
) -> None:
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _normalize(repository, first.id, content_hash="")  # type: ignore[arg-type]
    _normalize(repository, second.id, content_hash="")  # type: ignore[arg-type]

    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_excludes_null_normalized_text(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    # normalized_text NULL with a non-NULL content_hash cannot happen through
    # update_normalization (both are always written together), but the
    # schema itself allows it -- the filter must exclude it defensively.
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    connection.execute(
        "UPDATE article SET content_hash = 'hash-1' WHERE id IN (?, ?)", (first.id, second.id)
    )
    connection.commit()

    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_excludes_empty_normalized_text(
    repository: ArticleRepository, source_id: int
) -> None:
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _normalize(repository, first.id, content_hash="hash-1", normalized_text="")  # type: ignore[arg-type]
    _normalize(repository, second.id, content_hash="hash-1", normalized_text="")  # type: ignore[arg-type]

    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_excludes_non_pending_status(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    first = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    second = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _normalize(repository, first.id, content_hash="hash-1")  # type: ignore[arg-type]
    _normalize(repository, second.id, content_hash="hash-1")  # type: ignore[arg-type]
    _set_status(connection, second.id, "processed")  # type: ignore[arg-type]

    # Only one 'pending' article remains for that hash, so the group no
    # longer has 2+ pending members and is excluded entirely.
    assert repository.list_deduplication_candidates() == []


def test_list_deduplication_candidates_orders_by_hash_then_id(
    repository: ArticleRepository, source_id: int
) -> None:
    a = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    b = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    c = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    d = repository.create(_make_article(source_id=source_id, url="https://example.com/d"))
    _normalize(repository, d.id, content_hash="hash-b")  # type: ignore[arg-type]
    _normalize(repository, c.id, content_hash="hash-b")  # type: ignore[arg-type]
    _normalize(repository, b.id, content_hash="hash-a")  # type: ignore[arg-type]
    _normalize(repository, a.id, content_hash="hash-a")  # type: ignore[arg-type]

    result = repository.list_deduplication_candidates()

    assert [article.id for article in result] == [a.id, b.id, c.id, d.id]


# --- mark_duplicates (TASK-009 spec §5, §9) ---------------------------------


def test_mark_duplicates_discards_duplicates_and_sets_duplicate_of(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    dup1 = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    dup2 = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))

    repository.mark_duplicates(canonical.id, [dup1.id, dup2.id])  # type: ignore[arg-type, list-item]

    fetched1 = repository.get_by_url(dup1.url)
    fetched2 = repository.get_by_url(dup2.url)
    assert fetched1 is not None
    assert fetched1.status == "discarded"
    assert fetched1.duplicate_of == canonical.id
    assert fetched2 is not None
    assert fetched2.status == "discarded"
    assert fetched2.duplicate_of == canonical.id


def test_mark_duplicates_leaves_canonical_untouched(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type, list-item]

    fetched = repository.get_by_url(canonical.url)
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.duplicate_of is None


def test_mark_duplicates_does_not_modify_other_columns(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(
        _make_article(
            source_id=source_id,
            url="https://example.com/b",
            title="Duplicate Title",
            raw_excerpt="Duplicate raw excerpt",
        )
    )
    repository.update_normalization(
        duplicate.id,  # type: ignore[arg-type]
        normalized_text="dup text",
        content_hash="hash-1",
        language="en",
    )
    before = repository.get_by_url(duplicate.url)
    assert before is not None

    repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type, list-item]

    after = repository.get_by_url(duplicate.url)
    assert after is not None
    assert after.title == before.title
    assert after.url == before.url
    assert after.raw_excerpt == before.raw_excerpt
    assert after.published_at == before.published_at
    assert after.fetched_at == before.fetched_at
    assert after.source_id == before.source_id
    assert after.event_id == before.event_id
    assert after.normalized_text == before.normalized_text
    assert after.content_hash == before.content_hash
    assert after.language == before.language


def test_mark_duplicates_is_atomic_when_a_duplicate_id_does_not_exist(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    with pytest.raises(ValueError, match="Expected to mark"):
        repository.mark_duplicates(canonical.id, [duplicate.id, 999_999])  # type: ignore[arg-type, list-item]

    # Rollback: `duplicate` must NOT have been marked, even though it alone
    # matched the UPDATE's WHERE clause before the row-count check failed.
    fetched_duplicate = repository.get_by_url(duplicate.url)
    fetched_canonical = repository.get_by_url(canonical.url)
    assert fetched_duplicate is not None
    assert fetched_duplicate.status == "pending"
    assert fetched_duplicate.duplicate_of is None
    assert fetched_canonical is not None
    assert fetched_canonical.status == "pending"


def test_mark_duplicates_raises_for_nonexistent_canonical(
    repository: ArticleRepository, source_id: int
) -> None:
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    with pytest.raises(ValueError, match="No article found"):
        repository.mark_duplicates(999_999, [duplicate.id])  # type: ignore[list-item]

    fetched = repository.get_by_url(duplicate.url)
    assert fetched is not None
    assert fetched.status == "pending"


def test_mark_duplicates_raises_when_canonical_is_not_pending(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _set_status(connection, canonical.id, "processed")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="not eligible as canonical"):
        repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type, list-item]


def test_mark_duplicates_raises_when_canonical_is_already_a_duplicate(
    repository: ArticleRepository, source_id: int
) -> None:
    a = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    b = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    c = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    repository.mark_duplicates(a.id, [b.id])  # type: ignore[arg-type, list-item]

    with pytest.raises(ValueError, match="not eligible as canonical"):
        repository.mark_duplicates(b.id, [c.id])  # type: ignore[arg-type, list-item]


def test_mark_duplicates_raises_for_empty_duplicate_ids(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id))

    with pytest.raises(ValueError, match="must not be empty"):
        repository.mark_duplicates(canonical.id, [])  # type: ignore[arg-type]


def test_mark_duplicates_raises_when_canonical_is_in_duplicate_ids(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    with pytest.raises(ValueError, match="must not contain canonical_id"):
        repository.mark_duplicates(canonical.id, [duplicate.id, canonical.id])  # type: ignore[arg-type, list-item]


def test_mark_duplicates_raises_for_repeated_duplicate_ids(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))

    with pytest.raises(ValueError, match="repeated ids"):
        repository.mark_duplicates(canonical.id, [duplicate.id, duplicate.id])  # type: ignore[arg-type, list-item]


# --- list_pending_matches_for_established_canonicals (TASK-009 spec, A8) ---


def _establish_canonical(
    repository: ArticleRepository, *, canonical: Article, duplicate: Article, content_hash: str
) -> None:
    # Shared setup: normalize both articles to the same hash and mark the
    # duplicate, so `duplicate` becomes an already-established canonical's
    # follower for `content_hash` -- exactly the state
    # `list_pending_matches_for_established_canonicals` looks for.
    _normalize(repository, canonical.id, content_hash=content_hash)  # type: ignore[arg-type]
    _normalize(repository, duplicate.id, content_hash=content_hash)  # type: ignore[arg-type]
    repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type, list-item]


def test_list_pending_matches_for_established_canonicals_empty_when_nothing_marked(
    repository: ArticleRepository,
) -> None:
    assert repository.list_pending_matches_for_established_canonicals() == {}


def test_list_pending_matches_for_established_canonicals_finds_new_pending_with_same_hash(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    old_duplicate = repository.create(
        _make_article(source_id=source_id, url="https://example.com/b")
    )
    _establish_canonical(
        repository, canonical=canonical, duplicate=old_duplicate, content_hash="hash-1"
    )

    new_pending = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    _normalize(repository, new_pending.id, content_hash="hash-1")  # type: ignore[arg-type]

    matches = repository.list_pending_matches_for_established_canonicals()

    assert matches == {canonical.id: [new_pending.id]}


def test_list_pending_matches_for_established_canonicals_excludes_the_canonical_itself(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://example.com/b"))
    _establish_canonical(
        repository, canonical=canonical, duplicate=duplicate, content_hash="hash-1"
    )

    # The canonical is still 'pending' and trivially shares its own hash --
    # it must never be reported as a match of itself.
    assert repository.list_pending_matches_for_established_canonicals() == {}


def test_list_pending_matches_for_established_canonicals_groups_multiple_new_pending(
    repository: ArticleRepository, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    old_duplicate = repository.create(
        _make_article(source_id=source_id, url="https://example.com/b")
    )
    _establish_canonical(
        repository, canonical=canonical, duplicate=old_duplicate, content_hash="hash-1"
    )

    first_new = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    second_new = repository.create(_make_article(source_id=source_id, url="https://example.com/d"))
    _normalize(repository, second_new.id, content_hash="hash-1")  # type: ignore[arg-type]
    _normalize(repository, first_new.id, content_hash="hash-1")  # type: ignore[arg-type]

    matches = repository.list_pending_matches_for_established_canonicals()

    assert matches == {canonical.id: [first_new.id, second_new.id]}


def test_list_pending_matches_for_established_canonicals_ignores_non_pending_articles(
    repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    old_duplicate = repository.create(
        _make_article(source_id=source_id, url="https://example.com/b")
    )
    _establish_canonical(
        repository, canonical=canonical, duplicate=old_duplicate, content_hash="hash-1"
    )

    processed = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    _normalize(repository, processed.id, content_hash="hash-1")  # type: ignore[arg-type]
    _set_status(connection, processed.id, "processed")  # type: ignore[arg-type]

    assert repository.list_pending_matches_for_established_canonicals() == {}


def test_list_pending_matches_for_established_canonicals_requires_matching_hash(
    repository: ArticleRepository, source_id: int
) -> None:
    # A pending article must never be attached to an unrelated established
    # canonical just because *some* duplicate_of exists elsewhere in the
    # table -- only a matching content_hash makes it eligible (TASK-009
    # spec, A8 revision: "non fare affidamento soltanto sull'esistenza di
    # un duplicate_of senza verificare la corrispondenza dell'hash").
    canonical = repository.create(_make_article(source_id=source_id, url="https://example.com/a"))
    old_duplicate = repository.create(
        _make_article(source_id=source_id, url="https://example.com/b")
    )
    _establish_canonical(
        repository, canonical=canonical, duplicate=old_duplicate, content_hash="hash-1"
    )

    unrelated = repository.create(_make_article(source_id=source_id, url="https://example.com/c"))
    _normalize(repository, unrelated.id, content_hash="hash-2")  # type: ignore[arg-type]

    assert repository.list_pending_matches_for_established_canonicals() == {}


# --- TASK-024: clustering selection and event attachment ---------------------


def test_list_clusterable_returns_only_normalized_pending_articles(
    repository: ArticleRepository, source_id: int
) -> None:
    normalized = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    _normalize(repository, normalized.id, content_hash="hash-1")  # type: ignore[arg-type]
    # Not yet normalized: no content_hash.
    repository.create(_make_article(source_id=source_id, url="https://a.test/2"))

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=0)

    assert [article.id for article in clusterable] == [normalized.id]


def test_list_clusterable_excludes_discarded_duplicates(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    canonical = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    duplicate = repository.create(_make_article(source_id=source_id, url="https://a.test/2"))
    _normalize(repository, canonical.id, content_hash="hash-1")  # type: ignore[arg-type]
    _normalize(repository, duplicate.id, content_hash="hash-1")  # type: ignore[arg-type]
    repository.mark_duplicates(canonical.id, [duplicate.id])  # type: ignore[arg-type]

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=0)
    assert [article.id for article in clusterable] == [canonical.id]


# --- freshness (TASK-028) ---------------------------------------------------


def test_list_clusterable_includes_an_article_within_the_lookback_window(
    repository: ArticleRepository, source_id: int
) -> None:
    one_day_before = (_REFERENCE_DATE - timedelta(days=1)).isoformat() + "T10:00:00+00:00"
    article = repository.create(
        _make_article(source_id=source_id, url="https://a.test/1", published_at=one_day_before)
    )
    _normalize(repository, article.id, content_hash="hash-1")  # type: ignore[arg-type]

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=2)

    assert [a.id for a in clusterable] == [article.id]


def test_list_clusterable_includes_an_article_exactly_on_the_lookback_boundary(
    repository: ArticleRepository, source_id: int
) -> None:
    """Exactly `lookback_days` (2) days before `reference_date`: inclusive boundary."""
    on_boundary = (_REFERENCE_DATE - timedelta(days=2)).isoformat() + "T10:00:00+00:00"
    article = repository.create(
        _make_article(source_id=source_id, url="https://a.test/1", published_at=on_boundary)
    )
    _normalize(repository, article.id, content_hash="hash-1")  # type: ignore[arg-type]

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=2)

    assert [a.id for a in clusterable] == [article.id]


def test_list_clusterable_excludes_an_article_older_than_the_lookback_window(
    repository: ArticleRepository, source_id: int
) -> None:
    """One day past the boundary (3 days before `reference_date`): excluded."""
    too_old = (_REFERENCE_DATE - timedelta(days=3)).isoformat() + "T10:00:00+00:00"
    article = repository.create(
        _make_article(source_id=source_id, url="https://a.test/1", published_at=too_old)
    )
    _normalize(repository, article.id, content_hash="hash-1")  # type: ignore[arg-type]

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=2)

    assert clusterable == []


def test_list_clusterable_never_excludes_an_article_with_no_published_at(
    repository: ArticleRepository, source_id: int
) -> None:
    """Absence of `published_at` is unknown, never treated as staleness
    (CLAUDE.md §17) -- true even under the tightest possible window."""
    article = repository.create(
        _make_article(source_id=source_id, url="https://a.test/1", published_at=None)
    )
    _normalize(repository, article.id, content_hash="hash-1")  # type: ignore[arg-type]

    clusterable = repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=0)

    assert [a.id for a in clusterable] == [article.id]


def test_assign_event_attaches_articles_and_marks_them_processed(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    event_id = _create_event(connection)
    first = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    second = repository.create(_make_article(source_id=source_id, url="https://a.test/2"))
    _normalize(repository, first.id, content_hash="hash-1")  # type: ignore[arg-type]
    _normalize(repository, second.id, content_hash="hash-2")  # type: ignore[arg-type]

    repository.assign_event(event_id, [first.id, second.id])  # type: ignore[list-item]

    attached = repository.list_by_event(event_id)
    assert [article.id for article in attached] == [first.id, second.id]
    assert all(article.status == "processed" for article in attached)
    # Attached articles leave the clusterable pool, so a rerun creates no
    # second event for them (TASK-024 rerun policy).
    assert repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=0) == []


def test_assign_event_rejects_an_empty_or_repeated_id_list(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    event_id = _create_event(connection)

    with pytest.raises(ValueError, match="must not be empty"):
        repository.assign_event(event_id, [])
    with pytest.raises(ValueError, match="repeated ids"):
        repository.assign_event(event_id, [1, 1])


def test_assign_event_is_atomic_when_one_article_is_not_pending(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    event_id = _create_event(connection)
    pending = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    already_processed = repository.create(
        _make_article(source_id=source_id, url="https://a.test/2")
    )
    _set_status(connection, already_processed.id, "processed")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="only 1 row"):
        repository.assign_event(event_id, [pending.id, already_processed.id])  # type: ignore[list-item]

    # Rolled back: the pending article was not attached either.
    refreshed = repository.get_by_url("https://a.test/1")
    assert refreshed is not None
    assert refreshed.event_id is None
    assert refreshed.status == "pending"


def test_mark_not_relevant_discards_articles_without_a_duplicate_link(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    article = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    _normalize(repository, article.id, content_hash="hash-1")  # type: ignore[arg-type]

    repository.mark_not_relevant([article.id])  # type: ignore[list-item]

    refreshed = repository.get_by_url("https://a.test/1")
    assert refreshed is not None
    assert refreshed.status == "discarded"
    assert refreshed.duplicate_of is None
    assert refreshed.event_id is None
    # Discarded articles leave the clusterable pool (TASK-039).
    assert repository.list_clusterable(reference_date=_REFERENCE_DATE, lookback_days=0) == []


def test_mark_not_relevant_rejects_an_empty_or_repeated_id_list(
    repository: ArticleRepository,
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        repository.mark_not_relevant([])
    with pytest.raises(ValueError, match="repeated ids"):
        repository.mark_not_relevant([1, 1])


def test_mark_not_relevant_is_atomic_when_one_article_is_not_pending(
    repository: ArticleRepository, source_id: int, connection: sqlite3.Connection
) -> None:
    pending = repository.create(_make_article(source_id=source_id, url="https://a.test/1"))
    already_processed = repository.create(
        _make_article(source_id=source_id, url="https://a.test/2")
    )
    _set_status(connection, already_processed.id, "processed")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="only 1 row"):
        repository.mark_not_relevant([pending.id, already_processed.id])  # type: ignore[list-item]

    refreshed = repository.get_by_url("https://a.test/1")
    assert refreshed is not None
    assert refreshed.status == "pending"


def test_list_by_event_returns_nothing_for_an_unknown_event(
    repository: ArticleRepository,
) -> None:
    assert repository.list_by_event(999) == []


def _create_event(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        """
        INSERT INTO event
            (verification_status, confidence_score, importance_score, event_type, created_at)
        VALUES ('VERIFIED', 8.0, 7.0, 'standard', '2026-09-16T07:00:00+02:00')
        """
    )
    connection.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid
