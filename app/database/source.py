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

No range or default is enforced on `reliability_weight`: its semantics and
any bound are the responsibility of the later source-reliability task, not
this one.
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
    reliability_weight: float
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
