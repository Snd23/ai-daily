"""Sources configuration loader and database sync (TASK-006).

Loads and validates `config/sources.yaml` (docs/PRD.md §6): a list of
configured news sources, one YAML mapping per `Source` (docs/ARCHITECTURE.md
§3, TASK-005). Reuses `Source`'s own pydantic validation directly instead
of a parallel config/DTO model — every field understood here is a `Source`
field, validated the same way regardless of whether it came from YAML or
from the database.

`sync_sources` reconciles a loaded configuration into the `source` table
via `SourceRepository` (TASK-005), using `url` as the identity key (the
`source` table has no UNIQUE constraint on `url`; identity is established
here, at the application level, not by the schema). `sources.yaml` is
treated as the source of truth: a configured source with no matching row
is created, one that matches an existing row updates every configurable
field on it (or is left alone if nothing actually changed), and a database
row whose `url` is no longer configured is deactivated — never
hard-deleted, consistent with `SourceRepository.deactivate`.

The whole reconciliation is one atomic transaction (`SourceRepository.
transaction()`): if any write fails partway through, every write already
made by this call is rolled back, never left partially applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.errors import ConfigurationError
from app.database.source import Source
from app.database.source_repository import SourceRepository

DEFAULT_SOURCES_PATH = Path("config/sources.yaml")

_CONFIGURABLE_FIELDS_EXCLUDED_FROM_COMPARISON = {"id", "last_fetched_at"}


@dataclass
class SyncResult:
    """Outcome of one `sync_sources` call, bucketed by what happened to each source.

    Every `Source` in `configured` ends up in exactly one of `created`,
    `updated` or `unchanged`; every pre-existing row not present in
    `configured` ends up in `deactivated`. Each list holds the resulting
    `Source` (post-write), in encounter order within its bucket.
    """

    created: list[Source] = field(default_factory=list)
    updated: list[Source] = field(default_factory=list)
    deactivated: list[Source] = field(default_factory=list)
    unchanged: list[Source] = field(default_factory=list)


def load_sources_config(path: str | Path = DEFAULT_SOURCES_PATH) -> list[Source]:
    """Load and validate the sources configuration file into `Source` objects.

    A single invalid entry fails the entire load — there is no partial
    loading: `sources.yaml` is either entirely trustworthy or not used at
    all (CLAUDE.md §41).

    Raises:
        ConfigurationError: if the file is missing, is not valid YAML,
            does not map to `{"sources": [...]}`, contains an entry that
            is not a mapping or fails `Source` validation (missing
            required field, invalid `type`/`tier`/`reliability_weight`/
            etc.), or has two entries with the same `url`.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"Sources file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Invalid YAML in sources file {path}: {exc}") from exc

    if not isinstance(raw, dict) or "sources" not in raw:
        raise ConfigurationError(
            f"Sources file {path} must be a mapping with a top-level 'sources' key"
        )

    entries = raw["sources"]
    if not isinstance(entries, list):
        raise ConfigurationError(
            f"'sources' in {path} must be a list, got {type(entries).__name__}"
        )

    sources: list[Source] = []
    seen_urls: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigurationError(
                f"Entry {index} in {path} must be a mapping, got {type(entry).__name__}"
            )

        try:
            source = Source(**entry)
        except ValidationError as exc:
            raise ConfigurationError(f"Invalid source entry {index} in {path}: {exc}") from exc

        if source.url in seen_urls:
            raise ConfigurationError(
                f"Duplicate url {source.url!r} in {path} "
                f"(entries {seen_urls[source.url]} and {index})"
            )
        seen_urls[source.url] = index
        sources.append(source)

    return sources


def sync_sources(repository: SourceRepository, configured: list[Source]) -> SyncResult:
    """Reconcile `configured` sources into the database, using `url` as identity.

    `configured` (typically the result of `load_sources_config`) is treated
    as the source of truth:

    - a configured source whose `url` has no matching database row is
      created;
    - a configured source whose `url` matches an existing row, and whose
      configurable fields (`name`, `type`, `url`, `tier`, `categories`,
      `reliability_weight`, `is_active`) differ from that row, updates it
      in place — the row's `id` and `last_fetched_at` (runtime state, not
      configuration) are preserved; if nothing actually differs, the row is
      left untouched;
    - an existing row whose `url` is absent from `configured` is
      deactivated. It is never hard-deleted.

    The whole call is one atomic transaction: if any write fails partway
    through, every write already made by this call is rolled back and the
    database is left exactly as it was before the call.

    Running this twice with the same `configured` list is idempotent: no
    duplicate rows are created, and a second run reports everything as
    `unchanged`/`deactivated` again rather than writing anything new.

    Raises:
        ConfigurationError: if two entries in `configured` share the same
            `url` (checked independently of `load_sources_config`, before
            any database access, so a duplicate never touches the
            database).
    """
    _reject_duplicate_urls(configured)

    result = SyncResult()
    with repository.transaction():
        existing_by_url = {source.url: source for source in repository.list_all()}
        configured_urls = {source.url for source in configured}

        for source in configured:
            existing = existing_by_url.get(source.url)
            if existing is None:
                result.created.append(repository.create(source, commit=False))
                continue

            candidate = source.model_copy(
                update={"id": existing.id, "last_fetched_at": existing.last_fetched_at}
            )
            if _configurable_fields_equal(candidate, existing):
                result.unchanged.append(existing)
            else:
                repository.update(candidate, commit=False)
                result.updated.append(candidate)

        for url, existing in existing_by_url.items():
            if url in configured_urls:
                continue
            assert existing.id is not None  # rows from list_all() always have a persisted id
            repository.deactivate(existing.id, commit=False)
            result.deactivated.append(existing.model_copy(update={"is_active": False}))

    return result


def _reject_duplicate_urls(configured: list[Source]) -> None:
    seen: dict[str, int] = {}
    for index, source in enumerate(configured):
        if source.url in seen:
            raise ConfigurationError(
                f"Duplicate url {source.url!r} passed to sync_sources "
                f"(entries {seen[source.url]} and {index})"
            )
        seen[source.url] = index


def _configurable_fields_equal(a: Source, b: Source) -> bool:
    """Compare two `Source`s ignoring `id`/`last_fetched_at` (runtime state)."""
    exclude = _CONFIGURABLE_FIELDS_EXCLUDED_FROM_COMPARISON
    return a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)
