"""The `Article` model (TASK-007).

Mirrors the `article` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`), widened in TASK-007
(`app/database/migrations/0002_article_published_at_nullable.sql`) to allow
`published_at` to be absent, and again in TASK-009
(`app/database/migrations/0003_article_duplicate_of.sql`) to add
`duplicate_of` -- following the same pattern as `Source`
(`app/database/source.py`, TASK-005).

`event_id` is modeled here because the underlying column already exists
(TASK-004), but nothing populates it yet: it belongs to a later pipeline
stage (event clustering) and stays `None` on every `Article`.

`normalized_text`, `content_hash` and `language` are populated by TASK-008's
normalization stage. `duplicate_of` is populated by TASK-009's
deduplication stage: `None` means the article is not a duplicate (either
not yet evaluated, or kept as canonical); a persisted `id` means the
article was discarded as a duplicate of that other `Article`. An article
with `status = 'discarded'` and no `duplicate_of` was discarded as not about
AI (TASK-039).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

ArticleStatus = Literal["pending", "processed", "discarded", "error"]


class Article(BaseModel):
    """A single collected news article (docs/ARCHITECTURE.md §3, docs/PRD.md §20)."""

    id: int | None = None
    source_id: int
    event_id: int | None = None
    title: str
    url: str
    published_at: str | None = None
    fetched_at: str
    raw_excerpt: str
    normalized_text: str | None = None
    content_hash: str | None = None
    language: str | None = None
    status: ArticleStatus = "pending"
    duplicate_of: int | None = None

    @field_validator("title", "url", "fetched_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
