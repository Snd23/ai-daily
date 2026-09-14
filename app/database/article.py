"""The `Article` model (TASK-007).

Mirrors the `article` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`) and widened in TASK-007
(`app/database/migrations/0002_article_published_at_nullable.sql`) to allow
`published_at` to be absent, following the same pattern as `Source`
(`app/database/source.py`, TASK-005).

`event_id`, `normalized_text`, `content_hash` and `language` are modeled
here because the underlying columns already exist (TASK-004), but nothing
in TASK-007 populates them: they belong to later pipeline stages
(clustering, normalization) and stay `None` on every `Article` the RSS
collector produces.
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

    @field_validator("title", "url", "fetched_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
