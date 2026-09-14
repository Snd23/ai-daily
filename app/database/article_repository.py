"""SQLite repository for the `article` table (TASK-007, extended TASK-008).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same pattern as `SourceRepository` (TASK-005). Translates between `Article`
model instances and rows of the `article` table (TASK-004, widened by
TASK-007's `0002_article_published_at_nullable.sql`); the schema itself is
not modified here.

TASK-007 needs `create` and `get_by_url` (TASK-007 spec §7). TASK-008 adds
`list_pending` and `update_normalization` (TASK-008 spec §8) -- the minimum
needed to select pending articles and write back normalization results
without ever touching `status`, `published_at`, `event_id`, `raw_excerpt`,
`title`, `url`, `source_id` or `fetched_at`.

`status` is intentionally left out of the `create` INSERT column list so
the database's own `DEFAULT 'pending'` applies (TASK-007 spec §8) instead
of duplicating that value here. `update_normalization` deliberately writes
only `normalized_text`/`content_hash`/`language`, unlike `SourceRepository.
update` which overwrites every mutable field of a `Source` -- a narrower
UPDATE column list makes it structurally impossible for this method to
touch any other column (TASK-008 spec §8), rather than relying on callers
not to pass a modified value for them.
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

    def list_pending(self) -> list[Article]:
        """Return every `Article` with `status = 'pending'`, ordered by `id`.

        This is the selection TASK-008's normalization stage operates on
        (TASK-008 spec §7); mirrors `SourceRepository.list_active`'s
        naming and shape.
        """
        rows = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM article WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [_from_row(row) for row in rows]

    def update_normalization(
        self,
        article_id: int,
        *,
        normalized_text: str,
        content_hash: str,
        language: str | None,
    ) -> None:
        """Persist the normalization result for the article with `article_id`.

        Writes *only* `normalized_text`, `content_hash` and `language`;
        every other column (`status` included) is left exactly as it was
        (TASK-008 spec §8). `language=None` is stored as SQL `NULL` -- a
        legitimate result (TASK-008 spec §7), not an error.

        Raises:
            ValueError: if no row has `article_id`.
        """
        cursor = self._connection.execute(
            """
            UPDATE article
            SET normalized_text = :normalized_text,
                content_hash = :content_hash,
                language = :language
            WHERE id = :id
            """,
            {
                "id": article_id,
                "normalized_text": normalized_text,
                "content_hash": content_hash,
                "language": language,
            },
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"No article found with id={article_id}")


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
