"""Persistence for `EditionRecord` (TASK-024).

Plain stdlib `sqlite3`, no ORM (docs/ARCHITECTURE.md §1.2), following the
same shape as `EventRepository` (`app/database/event_repository.py`).

This repository exists because TASK-024 needs two things that have no
other source in the repository: a real, non-invented sequential
`edition_number` for `NewspaperMetadata` (`app/newspaper/renderer.py`,
which requires `edition_number >= 1`), and somewhere to record the path
the generated PDF was written to (`edition.pdf_path`). Both are columns
of the `edition` table created in TASK-004.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.edition import EditionRecord, EditionStatus

_SELECT_COLUMNS = (
    "id, edition_number, date, language, pdf_path, status,"
    " concept_deep_dive_id, concept_term_id, stats, created_at"
)


class EditionRepository:
    """Reads and writes `edition` rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def next_edition_number(self) -> int:
        """Return the next sequential edition number (1 when no edition exists yet).

        `edition.edition_number` is `UNIQUE NOT NULL`, so numbering is
        global and monotonic across languages: an `it` and an `en` edition
        of the same day are two distinct publications with two distinct
        numbers.
        """
        row = self._connection.execute(
            "SELECT COALESCE(MAX(edition_number), 0) FROM edition"
        ).fetchone()
        return int(row[0]) + 1

    def create(self, record: EditionRecord) -> EditionRecord:
        """Insert `record` and return it with its assigned `id`."""
        cursor = self._connection.execute(
            """
            INSERT INTO edition (
                edition_number, date, language, pdf_path, status,
                concept_deep_dive_id, concept_term_id, stats, created_at
            )
            VALUES (
                :edition_number, :date, :language, :pdf_path, :status,
                :concept_deep_dive_id, :concept_term_id, :stats, :created_at
            )
            """,
            record.model_dump(exclude={"id"}),
        )
        self._connection.commit()
        return record.model_copy(update={"id": cursor.lastrowid})

    def get_by_date_and_language(self, date: str, language: str) -> EditionRecord | None:
        """Return the edition published for `date` in `language`, or `None`.

        This is the lookup that makes re-running generation for the same
        day and language reuse the existing edition instead of allocating
        a second `edition_number` for the same publication.
        """
        row = self._connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM edition WHERE date = ? AND language = ?",
            (date, language),
        ).fetchone()
        return _from_row(row) if row is not None else None

    def update_pdf_path(self, edition_id: int, pdf_path: str, status: EditionStatus) -> None:
        """Record where this edition's PDF was written, and its resulting status.

        Raises:
            ValueError: if no row has `edition_id`.
        """
        cursor = self._connection.execute(
            "UPDATE edition SET pdf_path = :pdf_path, status = :status WHERE id = :id",
            {"id": edition_id, "pdf_path": pdf_path, "status": status},
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"No edition found with id={edition_id}")


def _from_row(row: Any) -> EditionRecord:
    return EditionRecord(
        id=row[0],
        edition_number=row[1],
        date=row[2],
        language=row[3],
        pdf_path=row[4],
        status=row[5],
        concept_deep_dive_id=row[6],
        concept_term_id=row[7],
        stats=row[8],
        created_at=row[9],
    )
