"""Deterministic category assignment for an event (TASK-024).

Replaces the CLASSIFY stage (docs/PRD.md §7) for the MVP with a
deterministic mapping, with no LLM call: the editorial category of an
event is derived from the `categories` tags already configured for the
sources that reported it (`config/sources.yaml`, `Source.categories`).

This is a deliberate, approved scope decision for TASK-024, not a
substitute implementation of the LLM classifier originally sketched in
docs/ARCHITECTURE.md §2: it introduces no new taxonomy (both sides of the
mapping already exist -- free-form source tags on one side, the nine
`EditorialCategory` slugs of `app.editorial.edition` and the `category`
table's seeded slugs on the other) and no new prompt or AI call.

Source tags are a property of the *source*, not of the individual article,
so this assignment expresses "which desk would normally cover a story from
these outlets", not "what this story is about". That limitation is
inherent to using source-level tags and is the reason a real CLASSIFY
stage remains a future task.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.database.event import EventType
from app.database.source import Source
from app.editorial.edition import EditorialCategory

# Free-form `Source.categories` tag -> editorial category slug. Every tag
# actually used in `config/sources.yaml` is covered except `community`,
# which describes the nature of a source (Tier 4 forums/social), not an
# editorial topic, and therefore maps to nothing.
_TAG_TO_CATEGORY: dict[str, EditorialCategory] = {
    "models": "models_llm",
    "business": "big_tech_business",
    "research": "ai_research",
    "developer": "ai_developers",
    "robotics": "robotics",
    "regulation": "regulation",
    "society": "society",
    "hardware": "hardware",
    "startups": "startups",
}

# Used only when no source of an event carries a single mappable tag.
# `EditorialCategory` is a closed set of nine slugs (`app.editorial.
# edition`, matching the `category` table seeded in TASK-004 and the
# labels approved in docs/PRD.md §40); there is no `other` slug in it, in
# `config/labels.yaml` or in the database, and inventing one would create
# a new taxonomy and an unapproved reader-facing label. `big_tech_business`
# is used instead as the documented default: it is the broadest of the
# nine for general AI industry news.
_FALLBACK_CATEGORY: EditorialCategory = "big_tech_business"

# Canonical order, used only to break ties deterministically.
_CATEGORY_ORDER: tuple[EditorialCategory, ...] = (
    "models_llm",
    "big_tech_business",
    "ai_research",
    "ai_developers",
    "robotics",
    "regulation",
    "society",
    "hardware",
    "startups",
)


def assign_category(sources: Iterable[Source]) -> EditorialCategory:
    """Return the editorial category for an event reported by `sources`.

    Selection rule for an event whose articles come from several sources:

    1. every *distinct* source contributes each of its mappable tags once
       (a source reporting an event with three articles does not outweigh
       a source reporting it with one, consistent with how
       `app.verification.event_verifier` counts sources rather than
       articles);
    2. the category with the most contributions wins;
    3. ties are broken by the canonical category order above, so the
       result never depends on iteration or insertion order;
    4. if no source carries a mappable tag, the documented fallback
       category is used.

    Pure and deterministic: no I/O, no mutation of `sources`.
    """
    counts: Counter[EditorialCategory] = Counter()
    for source in _distinct_by_id(sources):
        for tag in dict.fromkeys(source.categories):
            category = _TAG_TO_CATEGORY.get(tag)
            if category is not None:
                counts[category] += 1

    if not counts:
        return _FALLBACK_CATEGORY

    return min(counts, key=lambda category: (-counts[category], _CATEGORY_ORDER.index(category)))


def assign_event_type(category: EditorialCategory) -> EventType:
    """Return the `Event.event_type` implied by an event's editorial category.

    `event_type` is a required column of the `event` table with only three
    allowed values (`app/database/event.py`). Rather than introducing a
    second, independent heuristic, it is derived from the category already
    assigned above: an event filed under AI RESEARCH is `research`, one
    filed under AI FOR DEVELOPERS is `developer_relevant`, and everything
    else is `standard`.

    This is unrelated to the Developer Impact stage (docs/ARCHITECTURE.md
    §4.10, which explicitly neither reads nor writes `event_type`).

    Verified during the Post-Implementation Review (Finding 5): `event_type`
    has no reader anywhere in the codebase besides this write and its own
    round-trip through `EventRepository`/tests -- no editorial, ranking or
    rendering logic branches on it, and no PRD/ARCHITECTURE text defines
    how it should be assigned (it was originally "assigned by CLASSIFY,
    which is not implemented"). With no real consumer and no rule to
    contradict, this category-derived mapping is kept as the minimal,
    explicit, documented placeholder rather than introducing a second,
    independent heuristic or a new taxonomy.
    """
    if category == "ai_research":
        return "research"
    if category == "ai_developers":
        return "developer_relevant"
    return "standard"


def _distinct_by_id(sources: Iterable[Source]) -> list[Source]:
    """Deduplicate `sources` by `id`, preserving first-seen order."""
    seen: dict[int | None, Source] = {}
    for source in sources:
        seen.setdefault(source.id, source)
    return list(seen.values())
