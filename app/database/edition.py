"""The `EditionRecord` model (TASK-024).

Mirrors the `edition` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`), following the same
pattern as `Event` (`app/database/event.py`, TASK-011). No new column,
migration or state is introduced here.

Deliberately named `EditionRecord`, not `Edition`: `app.editorial.edition.
Edition` (TASK-020) is the in-memory *composition* of a newspaper (Top
Stories, sections, What to Watch) and has no persistent identity, while
this model is the persisted publication record of one edition -- its
sequential number, its date, its language, and where its PDF was written.
Keeping the two names distinct avoids conflating the editorial structure
with its publication metadata (docs/ARCHITECTURE.md §4.11 already
establishes that edition numbering and the publication date are
publication-time concerns, not editorial content).

`concept_deep_dive_id`, `concept_term_id` and `stats` are modeled because
the columns exist, but nothing populates them: concept selection remains
undecided (docs/ARCHITECTURE.md §6, ambiguities #1 and #6) and edition
statistics are not a TASK-024 requirement.

`content` (TASK-043) is the composed `app.editorial.edition.Edition`,
serialized as JSON when the edition is published: the same structure the
PDF was rendered from.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from app.config.settings import SUPPORTED_LANGUAGES

EditionStatus = Literal["draft", "published", "failed"]


class EditionRecord(BaseModel):
    """One persisted newspaper edition (docs/ARCHITECTURE.md §3, docs/PRD.md §20)."""

    id: int | None = None
    edition_number: int
    date: str
    language: str
    pdf_path: str | None = None
    status: EditionStatus = "draft"
    concept_deep_dive_id: int | None = None
    concept_term_id: int | None = None
    stats: str | None = None
    created_at: str
    content: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}, got {value!r}")
        return value
