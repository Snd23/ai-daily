"""The `EventContent` model (TASK-024).

Mirrors the `event_content` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`), following the same
pattern as `Event` (`app/database/event.py`, TASK-011): a pydantic model
whose fields and constraints match the columns already in the schema. No
new column, migration or state is introduced here.

One row per `(event_id, language)` (composite primary key): the generated,
reader-facing text of an event in one editorial language, so the same
language-neutral `Event` can serve both `it` and `en` without re-running
verification, category assignment or ranking (docs/PRD.md §38,
docs/ARCHITECTURE.md §3).

`structured_content` holds the JSON-encoded Developer Impact for this
`(event, language)` pair when one was produced. Its structure was left
unspecified until this task (docs/ARCHITECTURE.md §3) and is now defined
by `app.pipeline.generation`: `{"developer_impact": {...}}`, where the
inner object is a `DeveloperImpact` minus its `usage` field (token counts
are per-call telemetry, not editorial content). `None` means no Developer
Impact was produced for this event -- a normal outcome (docs/PRD.md §43),
not an error.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from app.config.settings import SUPPORTED_LANGUAGES


class EventContent(BaseModel):
    """The generated content of one event in one language."""

    event_id: int
    language: str
    title: str
    summary: str
    structured_content: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}, got {value!r}")
        return value

    @field_validator("title", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
