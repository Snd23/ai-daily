"""Persistence for `EventContent` (TASK-024).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same shape as `EventRepository` (`app/database/event_repository.py`).

`upsert` rather than `create`: the `(event_id, language)` primary key is
the natural identity of an event's content in one language, so re-running
generation for the same event and language replaces that row instead of
failing or duplicating it (TASK-024 rerun policy, docs/ARCHITECTURE.md
§4.14).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.event_content import EventContent

_SELECT_COLUMNS = "event_id, language, title, summary, structured_content"


class EventContentRepository:
    """Reads and writes `event_content` rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, content: EventContent) -> EventContent:
        """Insert `content`, replacing any existing row for its `(event_id, language)`."""
        self._connection.execute(
            """
            INSERT INTO event_content (event_id, language, title, summary, structured_content)
            VALUES (:event_id, :language, :title, :summary, :structured_content)
            ON CONFLICT (event_id, language) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                structured_content = excluded.structured_content
            """,
            content.model_dump(),
        )
        self._connection.commit()
        return content

    def get(self, event_id: int, language: str) -> EventContent | None:
        """Return the content of `event_id` in `language`, or `None` if absent."""
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM event_content WHERE event_id = ? AND language = ?",
            (event_id, language),
        ).fetchone()
        return _from_row(row) if row is not None else None


def _from_row(row: Any) -> EventContent:
    return EventContent(
        event_id=row[0],
        language=row[1],
        title=row[2],
        summary=row[3],
        structured_content=row[4],
    )
