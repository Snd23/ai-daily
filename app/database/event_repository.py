"""SQLite repository for the `event` table (TASK-011).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same pattern as `SourceRepository`/`ArticleRepository`. Translates between
`Event` model instances and rows of the `event` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`); the schema itself is
not modified here.

Only `create` and `get_by_id` are implemented: the minimum needed to
persist and read back an `Event` (approved TASK-011 spec). No other method
has a caller yet -- `list_*`/`update` are added by whichever future task
actually needs them, same as `SourceRepository`/`ArticleRepository` grew
incrementally task by task.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.event import Event

_SELECT_COLUMNS = (
    "id, verification_status, confidence_score, importance_score, event_type, "
    "future_date, created_at"
)


class EventRepository:
    """Typed data access for the `event` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, event: Event) -> Event:
        """Insert `event` and return it with its assigned `id`.

        `event.id` is ignored (the column is `AUTOINCREMENT`); pass an
        already-persisted `Event` and this still inserts a new row.
        """
        cursor = self._connection.execute(
            """
            INSERT INTO event
                (verification_status, confidence_score, importance_score, event_type,
                 future_date, created_at)
            VALUES
                (:verification_status, :confidence_score, :importance_score, :event_type,
                 :future_date, :created_at)
            """,
            {
                "verification_status": event.verification_status,
                "confidence_score": event.confidence_score,
                "importance_score": event.importance_score,
                "event_type": event.event_type,
                "future_date": event.future_date,
                "created_at": event.created_at,
            },
        )
        self._connection.commit()
        assert cursor.lastrowid is not None
        return event.model_copy(update={"id": cursor.lastrowid})

    def get_by_id(self, event_id: int) -> Event | None:
        """Return the `Event` with `event_id`, or `None` if it doesn't exist."""
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM event WHERE id = ?", (event_id,)
        ).fetchone()
        return _from_row(row) if row is not None else None

    def list_by_created_date(self, date: str) -> list[Event]:
        """Return every `Event` created on `date` (an ISO `YYYY-MM-DD` day), by `id`.

        `created_at` is stored as a full ISO-8601 timestamp, so the day is
        matched on its first ten characters. This is the selection one
        day's edition is composed from (TASK-024): it includes events
        created by an earlier run of the same day, which is what makes
        re-running generation reproduce the same edition rather than an
        empty one (docs/ARCHITECTURE.md §4.14).
        """
        rows = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM event WHERE substr(created_at, 1, 10) = ? ORDER BY id",
            (date,),
        ).fetchall()
        return [_from_row(row) for row in rows]


def _from_row(row: Any) -> Event:
    # `sqlite3.Cursor.fetchone` is typed `Any` by typeshed (a plain tuple at
    # runtime, given the connection's default row_factory); `Event(...)`
    # below re-validates every field's actual type.
    (
        id_,
        verification_status,
        confidence_score,
        importance_score,
        event_type,
        future_date,
        created_at,
    ) = row
    return Event(
        id=id_,
        verification_status=verification_status,
        confidence_score=confidence_score,
        importance_score=importance_score,
        event_type=event_type,
        future_date=future_date,
        created_at=created_at,
    )
