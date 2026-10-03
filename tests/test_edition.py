"""Tests for `app.editorial.edition` (TASK-020).

No network, no database and no LLM: `assemble_edition` is a pure
composition function over already-assembled `EditorialContent` plus
caller-supplied category/ranking/future_date data.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.editorial.edition import (
    _EDITORIAL_CATEGORIES,
    EventForEdition,
    assemble_edition,
)
from app.editorial.event_editorial import EditorialContent

_ALL_SECTION_SLUGS = set(_EDITORIAL_CATEGORIES)


def _content(**overrides: object) -> EditorialContent:
    values: dict[str, object] = {
        "event_id": 1,
        "language": "en",
        "verification_status": "VERIFIED",
        "title": "OpenAI announces X",
        "summary": "OpenAI announced X on Monday.",
        "developer_impact": None,
        "concept_explanation": None,
        "articles": (),
    }
    values.update(overrides)
    return EditorialContent.model_validate(values)


def _event(**overrides: object) -> EventForEdition:
    values: dict[str, object] = {
        "content": _content(),
        "category": "models_llm",
        "importance_score": 5.0,
        "future_date": None,
    }
    values.update(overrides)
    return EventForEdition.model_validate(values)


# --- EventForEdition -------------------------------------------------------------------


def test_event_for_edition_accepts_a_valid_object() -> None:
    event = _event()

    assert event.content.event_id == 1
    assert event.category == "models_llm"
    assert event.importance_score == 5.0
    assert event.future_date is None


def test_event_for_edition_is_frozen() -> None:
    event = _event()

    with pytest.raises(ValidationError):
        event.importance_score = 9.0  # type: ignore[misc]


def test_event_for_edition_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError):
        _event(category="not_a_real_category")


def test_event_for_edition_rejects_negative_importance_score() -> None:
    with pytest.raises(ValidationError):
        _event(importance_score=-0.1)


def test_event_for_edition_rejects_importance_score_above_ten() -> None:
    with pytest.raises(ValidationError):
        _event(importance_score=10.1)


def test_event_for_edition_accepts_a_future_date() -> None:
    event = _event(future_date="2026-03-01")

    assert event.future_date == "2026-03-01"


def test_event_for_edition_future_date_defaults_to_none() -> None:
    event = EventForEdition.model_validate(
        {"content": _content(), "category": "models_llm", "importance_score": 5.0}
    )

    assert event.future_date is None


# --- assemble_edition: basic contract ---------------------------------------------------


def test_assembles_an_empty_edition() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    assert edition.language == "en"
    assert edition.top_stories == ()
    assert edition.what_to_watch == ()
    assert len(edition.sections) == 9
    for section in edition.sections:
        assert section.entries == ()


def test_rejects_language_mismatch() -> None:
    with pytest.raises(ValueError, match="language"):
        assemble_edition(
            language="en",
            events=[_event(content=_content(language="it"))],
            max_top_stories=3,
        )


def test_rejects_duplicate_event_id() -> None:
    with pytest.raises(ValueError, match="duplicate event_id"):
        assemble_edition(
            language="en",
            events=[
                _event(content=_content(event_id=1)),
                _event(content=_content(event_id=1), category="ai_research"),
            ],
            max_top_stories=3,
        )


def test_rejects_negative_max_top_stories() -> None:
    with pytest.raises(ValueError, match="max_top_stories"):
        assemble_edition(language="en", events=[], max_top_stories=-1)


def test_rejects_unsupported_edition_language() -> None:
    with pytest.raises(ValueError, match="language"):
        assemble_edition(language="fr", events=[], max_top_stories=3)


# --- Top Stories -------------------------------------------------------------------------


def test_max_top_stories_zero_yields_no_top_stories() -> None:
    edition = assemble_edition(
        language="en",
        events=[_event(content=_content(event_id=1))],
        max_top_stories=0,
    )

    assert edition.top_stories == ()


def test_fewer_eligible_events_than_limit_returns_all_of_them() -> None:
    events = [
        _event(content=_content(event_id=1), importance_score=8.0),
        _event(content=_content(event_id=2), importance_score=6.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert len(edition.top_stories) == 2


def test_exact_limit_returns_every_eligible_event() -> None:
    events = [
        _event(content=_content(event_id=1), importance_score=8.0),
        _event(content=_content(event_id=2), importance_score=6.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=2)

    assert len(edition.top_stories) == 2


def test_more_events_than_limit_truncates_to_the_limit() -> None:
    events = [
        _event(content=_content(event_id=i), importance_score=float(i)) for i in range(1, 6)
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=2)

    assert len(edition.top_stories) == 2


def test_top_stories_are_sorted_by_importance_score_descending() -> None:
    events = [
        _event(content=_content(event_id=1), importance_score=3.0),
        _event(content=_content(event_id=2), importance_score=9.0),
        _event(content=_content(event_id=3), importance_score=6.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=3)

    assert [content.event_id for content in edition.top_stories] == [2, 3, 1]


def test_top_stories_tie_break_is_event_id_ascending() -> None:
    events = [
        _event(content=_content(event_id=5), importance_score=7.0),
        _event(content=_content(event_id=2), importance_score=7.0),
        _event(content=_content(event_id=9), importance_score=7.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=3)

    assert [content.event_id for content in edition.top_stories] == [2, 5, 9]


def test_selection_rank_breaks_ties_before_event_id() -> None:
    events = [
        _event(content=_content(event_id=2), importance_score=7.0, selection_rank=2),
        _event(content=_content(event_id=9), importance_score=7.0, selection_rank=1),
        _event(content=_content(event_id=5), importance_score=8.0, selection_rank=3),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=3)

    # The score still comes first; the rank only orders equal scores (TASK-040).
    assert [content.event_id for content in edition.top_stories] == [5, 9, 2]
    section = next(section for section in edition.sections if section.slug == "models_llm")
    assert [content.event_id for content in section.entries] == [5, 9, 2]


def test_unverified_events_are_excluded_from_top_stories() -> None:
    events = [
        _event(
            content=_content(event_id=1, verification_status="UNVERIFIED"),
            importance_score=10.0,
        ),
        _event(
            content=_content(event_id=2, verification_status="VERIFIED"),
            importance_score=1.0,
        ),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert [content.event_id for content in edition.top_stories] == [2]


def test_unverified_events_are_retained_in_their_section() -> None:
    events = [
        _event(
            content=_content(event_id=1, verification_status="UNVERIFIED"),
            category="ai_research",
        ),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    ai_research = next(section for section in edition.sections if section.slug == "ai_research")
    assert [content.event_id for content in ai_research.entries] == [1]


# --- Section grouping ----------------------------------------------------------------------


def test_all_nine_sections_are_present() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    assert {section.slug for section in edition.sections} == _ALL_SECTION_SLUGS
    assert len(edition.sections) == 9


def test_sections_follow_the_canonical_order() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    assert [section.slug for section in edition.sections] == list(_EDITORIAL_CATEGORIES)


def test_section_labels_are_resolved_for_italian() -> None:
    edition = assemble_edition(language="it", events=[], max_top_stories=3)

    labels = {section.slug: section.label for section in edition.sections}
    assert labels["models_llm"] == "MODELLI & LLM"
    assert labels["startups"] == "STARTUP"


def test_section_labels_are_resolved_for_english() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    labels = {section.slug: section.label for section in edition.sections}
    assert labels["models_llm"] == "MODELS & LLMs"
    assert labels["startups"] == "STARTUPS"


def test_events_are_grouped_into_their_declared_category() -> None:
    events = [
        _event(content=_content(event_id=1), category="robotics"),
        _event(content=_content(event_id=2), category="hardware"),
        _event(content=_content(event_id=3), category="robotics"),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    robotics = next(section for section in edition.sections if section.slug == "robotics")
    hardware = next(section for section in edition.sections if section.slug == "hardware")
    assert {content.event_id for content in robotics.entries} == {1, 3}
    assert {content.event_id for content in hardware.entries} == {2}


def test_section_entries_are_sorted_by_importance_score_descending() -> None:
    events = [
        _event(content=_content(event_id=1), category="startups", importance_score=2.0),
        _event(content=_content(event_id=2), category="startups", importance_score=8.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    startups = next(section for section in edition.sections if section.slug == "startups")
    assert [content.event_id for content in startups.entries] == [2, 1]


# --- What to Watch -------------------------------------------------------------------------


def test_events_with_future_date_are_selected_for_what_to_watch() -> None:
    events = [_event(content=_content(event_id=1), future_date="2026-03-01")]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert [content.event_id for content in edition.what_to_watch] == [1]


def test_events_without_future_date_are_excluded_from_what_to_watch() -> None:
    events = [_event(content=_content(event_id=1), future_date=None)]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert edition.what_to_watch == ()


def test_unverified_events_with_future_date_are_retained_in_what_to_watch() -> None:
    events = [
        _event(
            content=_content(event_id=1, verification_status="UNVERIFIED"),
            future_date="2026-03-01",
        ),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert [content.event_id for content in edition.what_to_watch] == [1]


def test_what_to_watch_is_sorted_deterministically() -> None:
    events = [
        _event(content=_content(event_id=1), future_date="2026-03-01", importance_score=2.0),
        _event(content=_content(event_id=2), future_date="2026-04-01", importance_score=8.0),
    ]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert [content.event_id for content in edition.what_to_watch] == [2, 1]


# --- Determinism / input-order independence -----------------------------------------------


def test_result_is_independent_of_input_order() -> None:
    a = _event(content=_content(event_id=1), category="robotics", importance_score=3.0)
    b = _event(content=_content(event_id=2), category="hardware", importance_score=9.0)
    c = _event(
        content=_content(event_id=3), category="robotics", importance_score=6.0, future_date="d"
    )

    edition_1 = assemble_edition(language="en", events=[a, b, c], max_top_stories=2)
    edition_2 = assemble_edition(language="en", events=[c, a, b], max_top_stories=2)

    assert edition_1 == edition_2


# --- Immutability / no side effects ---------------------------------------------------------


def test_edition_is_frozen() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    with pytest.raises(ValidationError):
        edition.language = "it"  # type: ignore[misc]


def test_edition_section_is_frozen() -> None:
    edition = assemble_edition(language="en", events=[], max_top_stories=3)

    with pytest.raises(ValidationError):
        edition.sections[0].label = "Changed"  # type: ignore[misc]


def test_edition_collections_are_tuples() -> None:
    events = [_event(content=_content(event_id=1), future_date="2026-03-01")]

    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    assert isinstance(edition.top_stories, tuple)
    assert isinstance(edition.sections, tuple)
    assert isinstance(edition.what_to_watch, tuple)
    assert isinstance(edition.sections[0].entries, tuple)


def test_does_not_mutate_the_supplied_events_sequence() -> None:
    events = [_event(content=_content(event_id=1)), _event(content=_content(event_id=2))]
    original = list(events)

    assemble_edition(language="en", events=events, max_top_stories=5)

    assert events == original


def test_preserves_the_original_editorial_content_objects() -> None:
    content = _content(event_id=1)
    event = _event(content=content, category="ai_research")

    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    ai_research = next(section for section in edition.sections if section.slug == "ai_research")
    assert ai_research.entries[0] is content
