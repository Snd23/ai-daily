"""SQLite repository for the `article` table (TASK-007, extended TASK-008,
TASK-009).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same pattern as `SourceRepository` (TASK-005). Translates between `Article`
model instances and rows of the `article` table (TASK-004, widened by
TASK-007's `0002_article_published_at_nullable.sql` and TASK-009's
`0003_article_duplicate_of.sql`); the schema itself is not modified here.

TASK-007 needs `create` and `get_by_url`. TASK-008 adds `list_pending` and
`update_normalization` -- the minimum needed to select pending articles and
write back normalization results without ever touching `status`,
`published_at`, `event_id`, `raw_excerpt`, `title`, `url`, `source_id` or
`fetched_at`. TASK-009 adds `list_deduplication_candidates`, `mark_
duplicates` and `list_pending_matches_for_established_canonicals` -- the
minimum needed to select deduplication candidates, persist a deduplication
decision without ever touching any other column, and find new `pending`
articles that must attach to an already-established canonical instead of
competing for the role again.

`status` is intentionally left out of the `create` INSERT column list so
the database's own `DEFAULT 'pending'` applies instead of duplicating that
value here; `duplicate_of` is left out the same way so it defaults to
`NULL`. `update_normalization` deliberately writes only `normalized_text`/
`content_hash`/`language`, unlike `SourceRepository.update` which
overwrites every mutable field of a `Source` -- a narrower UPDATE column
list makes it structurally impossible for this method to touch any other
column, rather than relying on callers not to pass a modified value for
them. `mark_duplicates` follows the same principle: it writes only
`status`/`duplicate_of` for the rows it is given.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from app.database.article import Article

_SELECT_COLUMNS = (
    "id, source_id, event_id, title, url, published_at, fetched_at, raw_excerpt, "
    "normalized_text, content_hash, language, status, duplicate_of"
)


class ArticleRepository:
    """Typed data access for the `article` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, article: Article) -> Article:
        """Insert `article` and return it with its assigned `id`.

        `article.id` is ignored (the column is `AUTOINCREMENT`); pass an
        already-persisted `Article` and this still inserts a new row.
        `article.status` and `article.duplicate_of` are ignored too: the
        database's own `DEFAULT 'pending'` and `NULL` apply (see module
        docstring).

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
        return article.model_copy(
            update={"id": cursor.lastrowid, "status": "pending", "duplicate_of": None}
        )

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

    def list_deduplication_candidates(self) -> list[Article]:
        """Return every `Article` eligible for deduplication (TASK-009).

        A candidate has `status = 'pending'`, a non-empty `normalized_text`
        and a non-empty `content_hash`, *and* shares its `content_hash`
        with at least one other candidate -- rows whose `content_hash` is
        unique among candidates are not returned, since there is nothing to
        deduplicate them against. Ordered by `(content_hash, id)`, which is
        the order `app.deduplication.article_deduplicator.plan_deduplication`
        expects for its grouping to be independent of any other order.

        An article that is not yet normalized (`content_hash IS NULL`) or
        whose normalized content is empty is left out entirely: it is
        neither read further nor written to by this stage (TASK-009 spec
        §4).
        """
        rows = self._connection.execute(
            f"""
            SELECT {_SELECT_COLUMNS} FROM article
            WHERE status = 'pending'
              AND normalized_text IS NOT NULL AND normalized_text != ''
              AND content_hash IS NOT NULL AND content_hash != ''
              AND content_hash IN (
                  SELECT content_hash FROM article
                  WHERE status = 'pending'
                    AND normalized_text IS NOT NULL AND normalized_text != ''
                    AND content_hash IS NOT NULL AND content_hash != ''
                  GROUP BY content_hash
                  HAVING COUNT(*) > 1
              )
            ORDER BY content_hash, id
            """
        ).fetchall()
        return [_from_row(row) for row in rows]

    def mark_duplicates(self, canonical_id: int, duplicate_ids: Sequence[int]) -> None:
        """Mark every article in `duplicate_ids` as a duplicate of `canonical_id`.

        Runs as a single atomic transaction: every row in `duplicate_ids`
        is set to `status = 'discarded'`, `duplicate_of = canonical_id`, or
        none of them are (TASK-009 spec §9 "Transazioni"). The canonical
        article itself is never written to by this method -- it keeps
        whatever `status` it already had (TASK-009 spec §12: still
        `'pending'` after deduplication).

        Args:
            canonical_id: id of the `Article` kept as canonical. Must
                already exist, have `status = 'pending'` and
                `duplicate_of IS NULL`.
            duplicate_ids: ids of the `Article` rows to mark as duplicates.
                Must be non-empty, must not contain `canonical_id`, and
                must not contain repeated ids.

        Raises:
            ValueError: if `duplicate_ids` is empty, contains
                `canonical_id`, or contains a repeated id -- checked before
                any write. Also raised, after a rollback, if `canonical_id`
                does not exist / is not `pending` / is already a duplicate,
                or if any id in `duplicate_ids` does not exist or is no
                longer `pending` (the number of rows actually updated does
                not match `len(duplicate_ids)`).
            sqlite3.Error: propagated after a rollback for any underlying
                database failure.
        """
        if not duplicate_ids:
            raise ValueError("duplicate_ids must not be empty")
        if canonical_id in duplicate_ids:
            raise ValueError(f"duplicate_ids must not contain canonical_id={canonical_id}")
        if len(set(duplicate_ids)) != len(duplicate_ids):
            raise ValueError(f"duplicate_ids must not contain repeated ids: {duplicate_ids!r}")

        try:
            canonical_row = self._connection.execute(
                "SELECT status, duplicate_of FROM article WHERE id = ?", (canonical_id,)
            ).fetchone()
            if canonical_row is None:
                raise ValueError(f"No article found with id={canonical_id}")
            canonical_status, canonical_duplicate_of = canonical_row
            if canonical_status != "pending" or canonical_duplicate_of is not None:
                raise ValueError(
                    f"Article id={canonical_id} is not eligible as canonical "
                    f"(status={canonical_status!r}, duplicate_of={canonical_duplicate_of!r})"
                )

            placeholders = ", ".join("?" for _ in duplicate_ids)
            cursor = self._connection.execute(
                f"""
                UPDATE article
                SET status = 'discarded', duplicate_of = ?
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                (canonical_id, *duplicate_ids),
            )
            if cursor.rowcount != len(duplicate_ids):
                raise ValueError(
                    f"Expected to mark {len(duplicate_ids)} duplicate(s) of "
                    f"id={canonical_id}, but only {cursor.rowcount} row(s) matched "
                    f"(a duplicate id may not exist or may no longer be 'pending')"
                )
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def list_pending_matches_for_established_canonicals(self) -> dict[int, list[int]]:
        """Return, per already-established canonical, the new `pending`
        articles that share its `content_hash`.

        An "established canonical" is an article already referenced by
        another row's `duplicate_of` -- i.e. a previous `mark_duplicates`
        call already chose it as canonical for some `content_hash`.
        TASK-009 spec (approved A8, "no canonical re-election") requires
        that such an article keep that role forever: a newly-arrived
        `pending` article sharing its `content_hash` must attach directly
        to it, without ever competing on `(source.tier, id)` the way a
        brand-new group does (`app.deduplication.article_deduplicator.
        plan_deduplication`).

        The match is made on `content_hash` equality between the candidate
        `pending` row and an existing `duplicate_of`-bearing row -- not
        merely on the existence of some `duplicate_of` value elsewhere in
        the table -- so a `pending` article is never attached to an
        unrelated canonical that happens to exist for a different hash.
        The canonical article itself is never included as its own match
        (its own `content_hash` trivially equals its own).

        Returns:
            `{canonical_id: [pending_id, ...]}`, one entry per canonical
            that has at least one new pending match (a canonical with no
            new match is simply absent, never mapped to an empty list).
            Each `pending_id` list is sorted by `id`.
        """
        rows = self._connection.execute(
            """
            SELECT matched.duplicate_of AS canonical_id, pending.id AS pending_id
            FROM article AS pending
            JOIN (
                SELECT DISTINCT content_hash, duplicate_of
                FROM article
                WHERE duplicate_of IS NOT NULL
            ) AS matched
              ON matched.content_hash = pending.content_hash
            WHERE pending.status = 'pending'
              AND pending.content_hash IS NOT NULL AND pending.content_hash != ''
              AND pending.id != matched.duplicate_of
            ORDER BY canonical_id, pending_id
            """
        ).fetchall()

        result: dict[int, list[int]] = {}
        for canonical_id, pending_id in rows:
            result.setdefault(canonical_id, []).append(pending_id)
        return result


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
        duplicate_of,
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
        duplicate_of=duplicate_of,
    )
