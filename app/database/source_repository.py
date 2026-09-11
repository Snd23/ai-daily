"""SQLite repository for the `source` table (TASK-005).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2). Translates
between `Source` model instances and rows of the `source` table created in
TASK-004; the schema itself is not modified here.

`source.url` and `source.name` have no UNIQUE constraint (a deliberate
decision — see TASK-005 spec discussion): `get_by_url` may match at most
one row today, but nothing here prevents a caller from `create`-ing a
duplicate. Preventing duplicates during a `sources.yaml` sync is TASK-006's
responsibility, not this repository's.

Deleting a `source` is intentionally not supported: `article.source_id`
references `source.id` with foreign keys enforced, and no requirement
documents a need to hard-delete a source. `deactivate` (`is_active = 0`) is
the documented mechanism for retiring a source without losing history.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.source import Source, decode_categories, encode_categories

_COLUMNS = (
    "id",
    "name",
    "type",
    "url",
    "tier",
    "categories",
    "reliability_weight",
    "is_active",
    "last_fetched_at",
)
_SELECT_COLUMNS = ", ".join(_COLUMNS)


class SourceRepository:
    """Typed data access for the `source` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, source: Source) -> Source:
        """Insert `source` and return it with its assigned `id`.

        `source.id` is ignored (the column is `AUTOINCREMENT`); pass an
        already-persisted `Source` and this still inserts a new row.
        """
        cursor = self._connection.execute(
            """
            INSERT INTO source
                (name, type, url, tier, categories, reliability_weight, is_active,
                 last_fetched_at)
            VALUES
                (:name, :type, :url, :tier, :categories, :reliability_weight, :is_active,
                 :last_fetched_at)
            """,
            {
                "name": source.name,
                "type": source.type,
                "url": source.url,
                "tier": source.tier,
                "categories": encode_categories(source.categories),
                "reliability_weight": source.reliability_weight,
                "is_active": int(source.is_active),
                "last_fetched_at": source.last_fetched_at,
            },
        )
        self._connection.commit()
        assert cursor.lastrowid is not None
        return source.model_copy(update={"id": cursor.lastrowid})

    def get_by_id(self, source_id: int) -> Source | None:
        """Return the `Source` with `source_id`, or `None` if it doesn't exist."""
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM source WHERE id = ?", (source_id,)
        ).fetchone()
        return _from_row(row) if row is not None else None

    def get_by_url(self, url: str) -> Source | None:
        """Return the `Source` whose `url` matches, or `None` if none does.

        `url` is not UNIQUE in the schema; if duplicates exist, the row
        returned is whichever SQLite's default row order picks first.
        """
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM source WHERE url = ?", (url,)
        ).fetchone()
        return _from_row(row) if row is not None else None

    def list_active(self) -> list[Source]:
        """Return every `Source` with `is_active = True`, ordered by `id`."""
        rows = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM source WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return [_from_row(row) for row in rows]

    def list_all(self) -> list[Source]:
        """Return every `Source`, active or not, ordered by `id`."""
        rows = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM source ORDER BY id"
        ).fetchall()
        return [_from_row(row) for row in rows]

    def update(self, source: Source) -> None:
        """Persist every mutable field of `source` (matched by `source.id`).

        Raises:
            ValueError: if `source.id` is `None`, or no row has that `id`.
        """
        if source.id is None:
            raise ValueError("Cannot update a Source that has no id")

        cursor = self._connection.execute(
            """
            UPDATE source
            SET name = :name,
                type = :type,
                url = :url,
                tier = :tier,
                categories = :categories,
                reliability_weight = :reliability_weight,
                is_active = :is_active,
                last_fetched_at = :last_fetched_at
            WHERE id = :id
            """,
            {
                "id": source.id,
                "name": source.name,
                "type": source.type,
                "url": source.url,
                "tier": source.tier,
                "categories": encode_categories(source.categories),
                "reliability_weight": source.reliability_weight,
                "is_active": int(source.is_active),
                "last_fetched_at": source.last_fetched_at,
            },
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"No source found with id={source.id}")

    def deactivate(self, source_id: int) -> None:
        """Set `is_active = False` for the source with `source_id`.

        Raises:
            ValueError: if no row has that `id`.
        """
        cursor = self._connection.execute(
            "UPDATE source SET is_active = 0 WHERE id = ?", (source_id,)
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"No source found with id={source_id}")


def _from_row(row: Any) -> Source:
    # `sqlite3.Cursor.fetchone`/`fetchall` are typed `Any` by typeshed (a
    # plain tuple at runtime, given the connection's default row_factory);
    # `Source(...)` below re-validates every field's actual type.
    (
        id_,
        name,
        type_,
        url,
        tier,
        categories_json,
        reliability_weight,
        is_active,
        last_fetched_at,
    ) = row
    return Source(
        id=id_,
        name=name,
        type=type_,
        url=url,
        tier=tier,
        categories=decode_categories(categories_json),
        reliability_weight=reliability_weight,
        is_active=bool(is_active),
        last_fetched_at=last_fetched_at,
    )
