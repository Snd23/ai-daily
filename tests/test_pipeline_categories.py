"""Tests for `app.pipeline.categories` (TASK-024).

Pure functions: no database, no network, no LLM.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from app.config.sources import DEFAULT_SOURCES_PATH
from app.database.source import Source
from app.editorial.edition import EditorialCategory
from app.pipeline.categories import assign_category, assign_event_type


def _make_source(**overrides: Any) -> Source:
    values: dict[str, Any] = {
        "id": 1,
        "name": "Example",
        "type": "rss",
        "url": "https://example.com/feed",
        "tier": 1,
        "categories": ["models"],
        "reliability_weight": 1.0,
        "is_active": True,
    }
    values.update(overrides)
    return Source(**values)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("models", "models_llm"),
        ("business", "big_tech_business"),
        ("research", "ai_research"),
        ("developer", "ai_developers"),
        ("robotics", "robotics"),
        ("regulation", "regulation"),
        ("society", "society"),
        ("hardware", "hardware"),
        ("startups", "startups"),
    ],
)
def test_each_source_tag_maps_to_its_editorial_category(tag: str, expected: str) -> None:
    assert assign_category([_make_source(categories=[tag])]) == expected


def test_unmappable_tags_fall_back_to_the_documented_default() -> None:
    # `community` describes the nature of a Tier 4 source, not a topic.
    assert assign_category([_make_source(categories=["community"])]) == "big_tech_business"


def test_no_sources_falls_back_to_the_documented_default() -> None:
    assert assign_category([]) == "big_tech_business"


def test_the_most_supported_category_wins_across_sources() -> None:
    sources = [
        _make_source(id=1, categories=["research"]),
        _make_source(id=2, categories=["research"]),
        _make_source(id=3, categories=["hardware"]),
    ]

    assert assign_category(sources) == "ai_research"


def test_a_source_is_counted_once_however_many_times_it_is_passed() -> None:
    """Repeating one source (once per article) must not outweigh another source."""
    hardware = _make_source(id=1, categories=["hardware"])
    research = _make_source(id=2, categories=["research"])

    # One hardware source and one research source tie at one vote each,
    # whether hardware is passed once or three times; the tie resolves by
    # canonical order, not by how many articles that source contributed.
    assert assign_category([hardware, research]) == "ai_research"
    assert assign_category([hardware, hardware, hardware, research]) == "ai_research"

    # Two *distinct* hardware sources do legitimately outweigh one research source.
    assert (
        assign_category(
            [
                _make_source(id=1, categories=["hardware"]),
                _make_source(id=3, categories=["hardware"]),
                research,
            ]
        )
        == "hardware"
    )


def test_ties_are_broken_by_canonical_order_not_input_order() -> None:
    models = _make_source(id=1, categories=["models"])
    startups = _make_source(id=2, categories=["startups"])

    assert assign_category([models, startups]) == "models_llm"
    assert assign_category([startups, models]) == "models_llm"


def test_result_is_independent_of_tag_order_within_a_source() -> None:
    forward = assign_category([_make_source(categories=["research", "models", "business"])])
    backward = assign_category([_make_source(categories=["business", "models", "research"])])

    assert forward == backward


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("ai_research", "research"),
        ("ai_developers", "developer_relevant"),
        ("models_llm", "standard"),
        ("big_tech_business", "standard"),
        ("robotics", "standard"),
        ("regulation", "standard"),
        ("society", "standard"),
        ("hardware", "standard"),
        ("startups", "standard"),
    ],
)
def test_event_type_is_derived_from_the_assigned_category(
    category: EditorialCategory, expected: str
) -> None:
    assert assign_event_type(category) == expected


def test_every_tag_used_in_the_real_sources_config_is_handled() -> None:
    """The mapping must cover the tags actually configured, or fall back cleanly.

    Guards against `config/sources.yaml` gaining a tag that silently sends
    every event of that source to the fallback category.
    """
    raw = yaml.safe_load(DEFAULT_SOURCES_PATH.read_text(encoding="utf-8"))
    configured_tags = {tag for entry in raw["sources"] for tag in entry["categories"]}

    unmapped = {
        tag for tag in configured_tags if assign_category([_make_source(categories=[tag])]) is None
    }
    assert unmapped == set()

    # `community` is the one known, deliberately unmapped tag; every other
    # configured tag must resolve to something other than the fallback.
    non_fallback = {
        tag
        for tag in configured_tags
        if assign_category([_make_source(categories=[tag])]) != "big_tech_business"
    }
    assert configured_tags - non_fallback == {"community", "business"}
