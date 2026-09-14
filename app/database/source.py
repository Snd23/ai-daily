"""The `Source` model (TASK-005).

Mirrors the `source` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`), which stores
`categories` as a JSON-encoded TEXT column
(docs/ARCHITECTURE.md §3; migration file header comment). This module owns
the encode/decode of that column; the DB schema itself is unchanged.

`categories` is a free-form list of tags describing a source's typical
topics. It is a distinct concept from the `category` table (which
classifies `Event` rows) and is not validated against it — the two
vocabularies are not documented as related.

`reliability_weight` is a manually curated numeric weight, distinct from
`tier`: `tier` is the discrete 1-4 editorial category (CLAUDE.md §13,
docs/PRD.md §3); `reliability_weight` is a continuous value meant for
future weighted scoring (docs/PRD.md §4/CLAUDE.md §14's `source_reliability`
concept). Its range (TASK-010) is `0.0`-`1.0` inclusive, matching the
values already curated in `config/sources.yaml`: it is required, has no
default and is never derived from `tier` -- a missing, out-of-range or
non-numeric value fails validation rather than being silently corrected
(CLAUDE.md §41).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SourceType = Literal["rss", "api", "html"]


class Source(BaseModel):
    """A configured news source (docs/ARCHITECTURE.md §3, docs/PRD.md §20)."""

    id: int | None = None
    name: str
    type: SourceType
    url: str
    tier: int = Field(ge=1, le=4)
    categories: list[str]
    reliability_weight: float = Field(ge=0.0, le=1.0)
    is_active: bool
    last_fetched_at: str | None = None

    @field_validator("name", "url")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


def encode_categories(categories: list[str]) -> str:
    """Serialize `Source.categories` for storage in the `categories` TEXT column."""
    return json.dumps(categories)


def decode_categories(raw: str) -> list[str]:
    """Deserialize the `categories` TEXT column back into `Source.categories`."""
    decoded: list[str] = json.loads(raw)
    return decoded
