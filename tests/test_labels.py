"""Tests for app.config.labels (TASK-002).

Covers: loading the real `config/labels.yaml`, and error handling for a
missing file, invalid structure, missing languages and mismatched keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import SUPPORTED_LANGUAGES, ConfigurationError
from app.config.labels import DEFAULT_LABELS_PATH, load_labels


def test_default_labels_file_loads_and_covers_all_approved_keys() -> None:
    labels = load_labels(DEFAULT_LABELS_PATH)

    approved_keys = {
        "top_stories",
        "models_llm",
        "big_tech_business",
        "ai_research",
        "ai_developers",
        "robotics",
        "regulation",
        "society",
        "hardware",
        "startups",
        "ai_senza_sbatti",
        "termine_del_giorno",
        "what_to_watch",
    }

    for language in SUPPORTED_LANGUAGES:
        for key in approved_keys:
            assert labels.get(key, language)


def test_approved_label_values_match_prd(tmp_path: Path) -> None:
    labels = load_labels(DEFAULT_LABELS_PATH)

    assert labels.get("ai_senza_sbatti", "it") == "AI SENZA SBATTI"
    assert labels.get("ai_senza_sbatti", "en") == "AI MADE SIMPLE"
    assert labels.get("termine_del_giorno", "it") == "TERMINE DEL GIORNO"
    assert labels.get("termine_del_giorno", "en") == "TERM OF THE DAY"
    assert labels.get("top_stories", "it") == "TOP STORIES"
    assert labels.get("top_stories", "en") == "TOP STORIES"


def test_missing_labels_file_raises(tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist.yaml"

    with pytest.raises(ConfigurationError, match="not found"):
        load_labels(missing_path)


def test_labels_file_missing_a_language_raises(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("it:\n  top_stories: TOP STORIES\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="missing languages"):
        load_labels(path)


def test_labels_file_with_mismatched_keys_raises(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text(
        "it:\n  top_stories: TOP STORIES\nen:\n  top_stories: TOP STORIES\n  extra_key: EXTRA\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="mismatched keys"):
        load_labels(path)


def test_labels_file_with_invalid_structure_raises(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("it: not-a-mapping\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid labels file"):
        load_labels(path)


def test_labels_file_that_is_not_a_mapping_raises(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_labels(path)


def test_get_unknown_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text(
        "it:\n  top_stories: TOP STORIES\nen:\n  top_stories: TOP STORIES\n", encoding="utf-8"
    )
    labels = load_labels(path)

    with pytest.raises(ConfigurationError, match="Missing label"):
        labels.get("unknown_key", "it")


def test_get_unsupported_language_raises() -> None:
    labels = load_labels(DEFAULT_LABELS_PATH)

    with pytest.raises(ConfigurationError, match="Unsupported language"):
        labels.get("top_stories", "fr")
