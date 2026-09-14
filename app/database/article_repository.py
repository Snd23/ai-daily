"""SQLite repository for the `article` table (TASK-007).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same pattern as `SourceRepository` (TASK-005). Translates between `Article`
model instances and rows of the `article` table (TASK-004, widened by
TASK-007's `0002_article_published_at_nullable.sql`); the schema itself is
not modified here.

Only the two operations `RssCollector` actually needs are provided:
`create` and `get_by_url` (TASK-007 spec §7). Deciding what to do about an
already-known `url` — skip it rather than erroring or overwriting it
(TASK-007 spec §11) — is the collector's responsibility, not this
repository's: it calls `get_by_url` before `create`, mirroring how
`SourceRepository` already leaves url-uniqueness policy to its caller
(TASK-005).

`status` is intentionally left out of the INSERT column list so the
database's own `DEFAULT 'pending'` applies (TASK-007 spec §8) instead of
duplicating that value here.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.article import Article

_SELECT_COLUMNS = (
    "id, source_id, event_id, title, url, published_at, fetched_at, raw_excerpt, "
    "normalized_text, content_hash, language, status"
)


class ArticleRepository:
    """Typed data access for the `article` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, article: Article) -> Article:
        """Insert `article` and return it with its assigned `id`.

        `article.id` is ignored (the column is `AUTOINCREMENT`); pass an
        already-persisted `Article` and this still inserts a new row.
        `article.status` is ignored too: the database's own
        `DEFAULT 'pending'` applies (see module docstring).

        Raises:
            sqlite3.IntegrityError: if `article.url` already exists
                (`url` is UNIQUE). Callers must check `get_by_url` first if
                a duplicate should be skipped instead of raising.
        """
        cursor = self._connection.execute(
            """
            INSERT INTO article
                (source_id, event_id, title, url, published_at, fetched_at, raw_excerpt,
                 normalized_text, content_hash, language)
            VALUES
                (:source_id, :event_id, :title, :url, :published_at, :fetched_at, :raw_excerpt,
                 :normalized_text, :content_hash, :language)
            """,
            {
                "source_id": article.source_id,
                "event_id": article.event_id,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at,
                "fetched_at": article.fetched_at,
                "raw_excerpt": article.raw_excerpt,
                "normalized_text": article.normalized_text,
                "content_hash": article.content_hash,
                "language": article.language,
            },
        )
        self._connection.commit()
        assert cursor.lastrowid is not None
        return article.model_copy(update={"id": cursor.lastrowid, "status": "pending"})

    def get_by_url(self, url: str) -> Article | None:
        """Return the `Article` whose `url` matches, or `None` if none does.

        `url` is UNIQUE in the schema, so at most one row can ever match.
        """
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM article WHERE url = ?", (url,)
        ).fetchone()
        return _from_row(row) if row is not None else None


def _from_row(row: Any) -> Article:
    # `sqlite3.Cursor.fetchone` is typed `Any` by typeshed (a plain tuple at
    # runtime, given the connection's default row_factory); `Article(...)`
    # below re-validates every field's actual type.
    (
        id_,
        source_id,
        event_id,
        title,
        url,
        published_at,
        fetched_at,
        raw_excerpt,
        normalized_text,
        content_hash,
        language,
        status,
    ) = row
    return Article(
        id=id_,
        source_id=source_id,
        event_id=event_id,
        title=title,
        url=url,
        published_at=published_at,
        fetched_at=fetched_at,
        raw_excerpt=raw_excerpt,
        normalized_text=normalized_text,
        content_hash=content_hash,
        language=language,
        status=status,
    )
