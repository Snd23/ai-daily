"""Newspaper layout composition (TASK-020): NEWSPAPER LAYOUT (partial).

Composes several already-assembled `EditorialContent` (TASK-019, one per
event/language) into a single immutable `Edition`: Top Stories selection,
grouping into the nine editorial category sections, What to Watch
selection, and section-label resolution from `config/labels.yaml`. Pure
and in-memory (MODEL B, approved TASK-020 decision D-013): no database
access, no `Edition`/`EventContent` persistence, no `LLMProvider` call, no
PDF rendering (approved decision D-005 -- that is TASK-021's job).

`category` and `importance_score` are caller-supplied (approved decision
D-006): CLASSIFY and RANK are not implemented here and are not invoked by
this module -- `EventForEdition` simply carries their already-computed
results alongside the corresponding `EditorialContent`. `future_date` is
also caller-supplied and is never computed, parsed, validated or inferred
here (approved decision D-010): the only rule this module applies is
`future_date is not None` (approved decision D-014 -- `UNVERIFIED` is not
excluded from What to Watch).

Section labels are resolved once, from the project's real
`config/labels.yaml` via `app.config.labels.load_labels` (the primitive
that module's docstring already designates for this purpose), memoized
after the first call so `assemble_edition` itself performs no repeated
filesystem access and contains no hardcoded label text (approved decision
in FASE 2, resolving the tension between "resolve labels from
config/labels.yaml" and "assemble_edition must not depend on the
filesystem": the dependency is paid once, at first use, exactly like every
other consumer of `app.config.labels` already does).
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config.labels import Labels, load_labels
from app.config.settings import SUPPORTED_LANGUAGES
from app.editorial.event_editorial import EditorialContent

EditorialCategory = Literal[
    "models_llm",
    "big_tech_business",
    "ai_research",
    "ai_developers",
    "robotics",
    "regulation",
    "society",
    "hardware",
    "startups",
]

# Canonical section order (docs/PRD.md §17, matching config/labels.yaml's key
# order). `top_stories` and `what_to_watch` are cross-cutting containers, not
# category sections (approved decision D-007), and are therefore not part of
# this tuple -- they are separate fields of `Edition`.
_EDITORIAL_CATEGORIES: tuple[EditorialCategory, ...] = get_args(EditorialCategory)


@lru_cache(maxsize=1)
def _section_labels() -> Labels:
    """Load `config/labels.yaml` once and memoize it for the process lifetime."""
    return load_labels()


class EventForEdition(BaseModel):
    """One event's already-produced content, category and ranking, for TASK-020.

    Immutable. A thin, caller-supplied bundle -- not a new generation stage:
    `category` (CLASSIFY output) and `importance_score` (RANK output,
    `app.ranking.event_ranker.RankedEvent`) are neither computed nor
    reinterpreted here (approved decision D-006). `future_date` is likewise
    caller-supplied and untouched (approved decision D-010).

    `selection_rank` is the caller's position for the event in its own
    best-first ordering (TASK-040); it only breaks ties between equal
    `importance_score` values. Either every event has one or none has: events
    left at `None` fall back to `event_id`.
    """

    model_config = ConfigDict(frozen=True)

    content: EditorialContent
    category: EditorialCategory
    importance_score: float = Field(ge=0.0, le=10.0)
    selection_rank: int | None = Field(default=None, ge=0)
    future_date: str | None = None


class EditionSection(BaseModel):
    """One editorial category section of an `Edition`.

    Immutable. `label` is the string already resolved from
    `config/labels.yaml` for the edition's language -- never hardcoded here.
    `entries` may be empty (approved decision D-012): every one of the nine
    categories is always represented, whether or not it has content.
    """

    model_config = ConfigDict(frozen=True)

    slug: EditorialCategory
    label: str
    entries: tuple[EditorialContent, ...]


class Edition(BaseModel):
    """The composed structure of one newspaper edition, in one language.

    Immutable. Plain data composition (approved TASK-020 output contract):
    no rendering, typography, pagination or PDF-specific structure --
    that is TASK-021's responsibility (approved decision D-005).
    """

    model_config = ConfigDict(frozen=True)

    language: str
    top_stories: tuple[EditorialContent, ...]
    sections: tuple[EditionSection, ...]
    what_to_watch: tuple[EditorialContent, ...]

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}, got {value!r}")
        return value


def _sort_key(event: EventForEdition) -> tuple[float, int, int]:
    """Deterministic ordering (approved decision D-011): score desc, event_id asc.

    Ties on the score are first broken by the caller's `selection_rank` (TASK-040).
    """
    rank = event.selection_rank if event.selection_rank is not None else 0
    return (-event.importance_score, rank, event.content.event_id)


def assemble_edition(
    language: str,
    events: Sequence[EventForEdition],
    max_top_stories: int,
) -> Edition:
    """Compose the `Edition` structure for `language` from `events`.

    Validates that every event's content is consistent with `language` and
    that no `event_id` is duplicated, then:

    - selects Top Stories: events with `content.verification_status !=
      "UNVERIFIED"`, ordered by `importance_score` descending /
      `selection_rank` ascending / `event_id` ascending, truncated to
      `max_top_stories` (approved decisions D-008/D-009/D-011, TASK-040);
    - groups every event that is not a Top Story into its `category`
      section, in the fixed canonical order, each internally ordered the
      same way (approved decision D-011; a Top Story is not repeated in its
      section, TASK-041); `UNVERIFIED` events are retained in their section
      (D-009 excludes them only from Top Stories);
    - selects What to Watch: events with `future_date is not None`, in the
      same order, with no other criterion and no exclusion of `UNVERIFIED`
      (approved decisions D-010/D-014).

    Args:
        language: the edition's language; must be one of
            `SUPPORTED_LANGUAGES`.
        events: the candidate events for this edition. May be empty: an
            empty `Edition` (empty Top Stories/What to Watch, all nine
            sections present with `entries == ()`) is a valid result, not
            an error.
        max_top_stories: maximum number of Top Stories to select. Must be
            `>= 0` (`0` is valid and yields an empty Top Stories); there is
            no default (approved decision D-008 -- not to be invented).

    Returns:
        The composed `Edition`.

    Raises:
        ValueError: if `language` is not one of `SUPPORTED_LANGUAGES`, if
            `max_top_stories < 0`, if any `event.content.language` does not
            match `language`, or if two events share the same
            `content.event_id`.

    Pure: no I/O beyond the one-time, memoized `config/labels.yaml` load
    (see `_section_labels`); no mutation of `events` or any of its
    elements; no database, LLM, ranking or classification call. Order
    of `events` has no effect on the result.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}, got {language!r}")
    if max_top_stories < 0:
        raise ValueError(f"max_top_stories must be >= 0, got {max_top_stories!r}")

    seen_event_ids: set[int] = set()
    for event in events:
        if event.content.language != language:
            raise ValueError(
                f"event content.language ({event.content.language!r}) does not match"
                f" language ({language!r}) for event_id {event.content.event_id!r}"
            )
        if event.content.event_id in seen_event_ids:
            raise ValueError(f"duplicate event_id: {event.content.event_id!r}")
        seen_event_ids.add(event.content.event_id)

    top_story_candidates = [
        event for event in events if event.content.verification_status != "UNVERIFIED"
    ]
    top_story_events = sorted(top_story_candidates, key=_sort_key)[:max_top_stories]
    top_stories = tuple(event.content for event in top_story_events)
    top_story_ids = {event.content.event_id for event in top_story_events}

    labels = _section_labels()
    sections = tuple(
        EditionSection(
            slug=category,
            label=labels.get(category, language),
            entries=tuple(
                event.content
                for event in sorted(
                    (
                        event
                        for event in events
                        if event.category == category
                        and event.content.event_id not in top_story_ids
                    ),
                    key=_sort_key,
                )
            ),
        )
        for category in _EDITORIAL_CATEGORIES
    )

    what_to_watch = tuple(
        event.content
        for event in sorted(
            (event for event in events if event.future_date is not None), key=_sort_key
        )
    )

    return Edition(
        language=language,
        top_stories=top_stories,
        sections=sections,
        what_to_watch=what_to_watch,
    )
