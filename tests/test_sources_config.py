"""Tests for `app.config.sources` (TASK-006).

Covers `load_sources_config` (YAML parsing/validation) and `sync_sources`
(reconciliation into the `source` table via `SourceRepository`). Uses the
same migrated-in-memory-connection fixture pattern as
`tests/test_source_repository.py` for the sync tests.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import ConfigurationError
from app.config.sources import DEFAULT_SOURCES_PATH, load_sources_config, sync_sources
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

_VALID_YAML = """
sources:
  - name: OpenAI
    type: rss
    url: https://openai.com/news/rss.xml
    tier: 1
    categories:
      - models
      - business
    reliability_weight: 1.0
    is_active: true
  - name: Reddit - r/MachineLearning
    type: rss
    url: https://www.reddit.com/r/MachineLearning/.rss
    tier: 4
    categories:
      - community
    reliability_weight: 0.3
    is_active: true
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(content, encoding="utf-8")
    return path


# --- load_sources_config: happy path -----------------------------------


def test_valid_yaml_with_multiple_sources_loads(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_YAML)

    sources = load_sources_config(path)

    assert [source.name for source in sources] == ["OpenAI", "Reddit - r/MachineLearning"]


def test_loaded_source_fields_are_converted_correctly(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_YAML)

    sources = load_sources_config(path)
    openai = sources[0]

    assert openai.id is None
    assert openai.type == "rss"
    assert openai.url == "https://openai.com/news/rss.xml"
    assert openai.tier == 1
    assert openai.categories == ["models", "business"]
    assert openai.reliability_weight == 1.0
    assert openai.is_active is True


def test_categories_are_not_validated_against_category_slugs(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 1
            categories:
              - not_a_real_category_slug
              - another_made_up_tag
            reliability_weight: 1.0
            is_active: true
        """,
    )

    sources = load_sources_config(path)

    assert sources[0].categories == ["not_a_real_category_slug", "another_made_up_tag"]


def test_real_sources_yaml_loads(tmp_path: Path) -> None:
    # Smoke test against the actual shipped configuration.
    sources = load_sources_config(DEFAULT_SOURCES_PATH)

    assert len(sources) > 0
    assert all(source.url for source in sources)


# --- load_sources_config: error handling --------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_sources_config(tmp_path / "does-not-exist.yaml")


def test_empty_file_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "")

    with pytest.raises(ConfigurationError, match="top-level 'sources' key"):
        load_sources_config(path)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "sources: [this is: not, valid: yaml")

    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        load_sources_config(path)


def test_missing_sources_key_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "not_sources: []\n")

    with pytest.raises(ConfigurationError, match="top-level 'sources' key"):
        load_sources_config(path)


def test_sources_not_a_list_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "sources:\n  name: OpenAI\n")

    with pytest.raises(ConfigurationError, match="must be a list"):
        load_sources_config(path)


def test_entry_that_is_not_a_mapping_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "sources:\n  - just a string\n")

    with pytest.raises(ConfigurationError, match="must be a mapping"):
        load_sources_config(path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            tier: 1
            categories: []
            reliability_weight: 1.0
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_invalid_type_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: ftp
            url: https://example.com/feed
            tier: 1
            categories: []
            reliability_weight: 1.0
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_invalid_tier_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 5
            categories: []
            reliability_weight: 1.0
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_reliability_weight_out_of_range_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 1
            categories: []
            reliability_weight: 1.01
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_reliability_weight_missing_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 1
            categories: []
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_reliability_weight_non_numeric_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 1
            categories: []
            reliability_weight: "high"
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_invalid_categories_shape_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example
            type: rss
            url: https://example.com/feed
            tier: 1
            categories: "not-a-list"
            reliability_weight: 1.0
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Invalid source entry 0"):
        load_sources_config(path)


def test_duplicate_url_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        sources:
          - name: Example One
            type: rss
            url: https://example.com/feed
            tier: 1
            categories: []
            reliability_weight: 1.0
            is_active: true
          - name: Example Two
            type: rss
            url: https://example.com/feed
            tier: 2
            categories: []
            reliability_weight: 0.5
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError, match="Duplicate url"):
        load_sources_config(path)


def test_single_invalid_entry_fails_the_entire_load(tmp_path: Path) -> None:
    # The first entry is valid; the second is not. Nothing should be
    # returned/partially loaded.
    path = _write(
        tmp_path,
        """
        sources:
          - name: Valid
            type: rss
            url: https://example.com/valid
            tier: 1
            categories: []
            reliability_weight: 1.0
            is_active: true
          - name: Invalid
            type: not-a-real-type
            url: https://example.com/invalid
            tier: 1
            categories: []
            reliability_weight: 1.0
            is_active: true
        """,
    )

    with pytest.raises(ConfigurationError):
        load_sources_config(path)


# --- sync_sources --------------------------------------------------------


def _source(**overrides: object) -> Source:
    values: dict[str, object] = {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/news/rss.xml",
        "tier": 1,
        "categories": ["models"],
        "reliability_weight": 1.0,
        "is_active": True,
    }
    values.update(overrides)
    return Source(**values)


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SourceRepository:
    run_migrations(connection)
    return SourceRepository(connection)


def test_sync_creates_new_sources(repository: SourceRepository) -> None:
    result = sync_sources(repository, [_source()])

    assert len(result.created) == 1
    assert result.created[0].id is not None
    assert not result.updated
    assert not result.deactivated
    assert not result.unchanged
    assert repository.get_by_url("https://openai.com/news/rss.xml") is not None


def test_sync_updates_existing_source_matched_by_url(repository: SourceRepository) -> None:
    sync_sources(repository, [_source(name="OpenAI", tier=1, reliability_weight=1.0)])

    renamed = _source(
        name="OpenAI (renamed)", tier=2, categories=["models", "business"], reliability_weight=0.8
    )
    result = sync_sources(repository, [renamed])

    updated = repository.get_by_url("https://openai.com/news/rss.xml")
    assert updated is not None
    assert updated.name == "OpenAI (renamed)"
    assert updated.tier == 2
    assert updated.categories == ["models", "business"]
    assert updated.reliability_weight == 0.8
    assert len(result.updated) == 1
    assert result.updated[0].id == updated.id
    assert not result.created
    assert not result.unchanged


def test_sync_preserves_last_fetched_at_on_update(repository: SourceRepository) -> None:
    created = repository.create(_source())
    repository.update(created.model_copy(update={"last_fetched_at": "2026-01-01T00:00:00+00:00"}))

    sync_sources(repository, [_source(reliability_weight=0.5)])

    updated = repository.get_by_id(created.id)  # type: ignore[arg-type]
    assert updated is not None
    assert updated.last_fetched_at == "2026-01-01T00:00:00+00:00"
    assert updated.reliability_weight == 0.5


def test_sync_is_idempotent(repository: SourceRepository) -> None:
    configured = [_source(), _source(name="Reddit", url="https://reddit.com/r/x/.rss", tier=4)]

    sync_sources(repository, configured)
    sync_sources(repository, configured)

    assert len(repository.list_all()) == 2


def test_sync_deactivates_source_removed_from_configuration(repository: SourceRepository) -> None:
    sync_sources(
        repository,
        [_source(), _source(name="Reddit", url="https://reddit.com/r/x/.rss", tier=4)],
    )

    sync_sources(repository, [_source()])  # Reddit no longer configured

    reddit = repository.get_by_url("https://reddit.com/r/x/.rss")
    assert reddit is not None
    assert reddit.is_active is False
    assert reddit not in repository.list_active()


def test_sync_never_hard_deletes(repository: SourceRepository) -> None:
    sync_sources(
        repository,
        [_source(), _source(name="Reddit", url="https://reddit.com/r/x/.rss", tier=4)],
    )

    sync_sources(repository, [_source()])

    assert len(repository.list_all()) == 2


def test_sync_reactivates_a_source_that_reappears_in_configuration(
    repository: SourceRepository,
) -> None:
    reddit = _source(name="Reddit", url="https://reddit.com/r/x/.rss", tier=4)

    sync_sources(repository, [_source(), reddit])
    sync_sources(repository, [_source()])  # Reddit removed -> deactivated
    sync_sources(repository, [_source(), reddit])  # Reddit reconfigured -> reactivated

    assert repository.get_by_url("https://reddit.com/r/x/.rss").is_active is True  # type: ignore[union-attr]


# --- SyncResult -----------------------------------------------------------


def test_sync_result_reports_created_updated_unchanged_and_deactivated(
    repository: SourceRepository,
) -> None:
    repository.create(_source(name="A", url="https://a.example/feed", tier=1))
    repository.create(_source(name="B", url="https://b.example/feed", tier=1))
    repository.create(_source(name="D", url="https://d.example/feed", tier=1))

    configured = [
        _source(name="A", url="https://a.example/feed", tier=1),  # identical -> unchanged
        _source(name="B (renamed)", url="https://b.example/feed", tier=2),  # changed -> updated
        _source(name="C", url="https://c.example/feed", tier=1),  # new -> created
        # D is not configured -> deactivated
    ]

    result = sync_sources(repository, configured)

    assert [s.url for s in result.created] == ["https://c.example/feed"]
    assert [s.url for s in result.updated] == ["https://b.example/feed"]
    assert [s.url for s in result.unchanged] == ["https://a.example/feed"]
    assert [s.url for s in result.deactivated] == ["https://d.example/feed"]
    assert result.deactivated[0].is_active is False


def test_sync_result_unchanged_when_nothing_differs(repository: SourceRepository) -> None:
    sync_sources(repository, [_source()])

    result = sync_sources(repository, [_source()])

    assert not result.created
    assert not result.updated
    assert len(result.unchanged) == 1


# --- atomicity / rollback --------------------------------------------------


def test_sync_rejects_duplicate_urls_in_input_without_touching_database(
    repository: SourceRepository,
) -> None:
    repository.create(_source())  # pre-existing state that must remain untouched

    duplicated = [
        _source(name="One", url="https://dup.example/feed", tier=1),
        _source(name="Two", url="https://dup.example/feed", tier=2),
    ]

    with pytest.raises(ConfigurationError, match="Duplicate url"):
        sync_sources(repository, duplicated)

    assert len(repository.list_all()) == 1
    assert repository.get_by_url("https://dup.example/feed") is None


def test_sync_rolls_back_entirely_when_a_later_write_fails(
    repository: SourceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = repository.create(_source(name="Existing", tier=1))

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(repository, "update", _boom)

    configured = [
        # Processed first: a real create() call succeeds (uncommitted).
        _source(name="New", url="https://new.example/feed", tier=2),
        # Processed second: matches `existing` by url, so update() is
        # attempted -> raises via the monkeypatch above.
        _source(name="Existing (changed)", tier=3),
    ]

    with pytest.raises(RuntimeError, match="simulated failure"):
        sync_sources(repository, configured)

    # The create() from step 1 must have been rolled back too: nothing
    # partially applied.
    assert repository.get_by_url("https://new.example/feed") is None
    unchanged = repository.get_by_id(existing.id)  # type: ignore[arg-type]
    assert unchanged == existing
    assert len(repository.list_all()) == 1
