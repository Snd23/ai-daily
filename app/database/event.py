"""The `Event` model (TASK-011).

Mirrors the `event` table created in TASK-004
(`app/database/migrations/0001_initial_schema.sql`), following the same
pattern as `Source` (`app/database/source.py`, TASK-005) and `Article`
(`app/database/article.py`, TASK-007): a pydantic model whose fields and
constraints match the columns and CHECK constraints already in the schema.
No new column, migration or state is introduced here.

TASK-011 is scoped to persistence only (approved TASK-011 spec: "sola
persistenza Event"). `verification_status` and `confidence_score` are
therefore plain, caller-supplied fields with no computation behind them --
this module does not decide, derive or corroborate anything. Determining
their actual value for a real `Event` (source-reliability-weighted
corroboration across an event's articles, hedging-language detection, etc.
per CLAUDE.md §14/§15, docs/PRD.md §4/§5) is explicitly deferred to a future
verification task, which is also where `article.event_id` will first be
populated (event clustering -- see `app/database/article.py`'s docstring:
"nothing populates it yet"). Until that task exists, an `Event` here is
simply a validated row a caller constructs directly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerificationStatus = Literal["VERIFIED", "PARTIALLY_VERIFIED", "DEVELOPING", "UNVERIFIED"]
EventType = Literal["standard", "research", "developer_relevant"]


class Event(BaseModel):
    """A clustered news event (docs/ARCHITECTURE.md §3, docs/PRD.md §20)."""

    id: int | None = None
    verification_status: VerificationStatus
    confidence_score: float = Field(ge=0.0, le=10.0)
    importance_score: float = Field(ge=0.0, le=10.0)
    event_type: EventType
    future_date: str | None = None
    created_at: str
