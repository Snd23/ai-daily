"""RSS/Atom collector (TASK-007).

Fetches every active `Source` of `type == "rss"` (docs/PRD.md §6) over
HTTP, parses the feed with `feedparser`, and persists each entry as an
`Article` via `ArticleRepository`:

    SourceRepository -> RssCollector -> Article -> ArticleRepository -> SQLite

`RssCollector` owns retrieval and parsing only; all persistence goes
through `ArticleRepository` (docs/ARCHITECTURE.md §2, §9 separation of
responsibilities). It does not normalize, deduplicate, classify or rank —
those are later pipeline stages (TASK-008 onward).

Resilience (CLAUDE.md §33-34, docs/PRD.md §24): a source that fails to
fetch or fails to parse is logged and skipped; it never aborts collection
of the remaining sources. An entry within an otherwise-valid feed that is
missing required data (no usable URL, no usable title) is skipped the same
way. A database failure is not caught here: it is treated as a genuinely
critical infrastructure failure that should propagate (TASK-007 spec §14).

Freshness (TASK-028, docs/ARCHITECTURE.md §4.15): an entry whose
`published_at` is older than `lookback_days` before `reference_date` is
never persisted -- the ingestion-gate half of the FILTER stage's recency
requirement. `reference_date` is always supplied by the caller (the CLI's
`collect` command, from the same `datetime.now(APP_TIMEZONE).date()`
expression `app.pipeline.generation.generate_edition` already uses for
`edition_day`) rather than computed here, so this module has no independent
notion of "now" and stays fully deterministic/testable. An entry with no
usable `published_at` is never excluded on that basis alone (CLAUDE.md §17:
absence of a date is not evidence of staleness).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import feedparser
import requests
from pydantic import ValidationError

from app.config.settings import DEFAULT_NEWS_LOOKBACK_DAYS
from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.source import Source
from app.database.source_repository import SourceRepository

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass
class SourceCollectionResult:
    """Outcome of collecting one RSS source.

    `error` is `None` on success. On success, `created` holds every
    `Article` newly persisted (in feed order), `skipped_duplicates` counts
    entries whose `url` already existed and were left untouched, and
    `skipped_stale` counts entries whose `published_at` was older than the
    configured lookback window (TASK-028).
    """

    source: Source
    created: list[Article] = field(default_factory=list)
    skipped_duplicates: int = 0
    skipped_stale: int = 0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class RssCollector:
    """Collects articles from active RSS sources into the database."""

    def __init__(
        self,
        source_repository: SourceRepository,
        article_repository: ArticleRepository,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        lookback_days: int = DEFAULT_NEWS_LOOKBACK_DAYS,
    ) -> None:
        self._source_repository = source_repository
        self._article_repository = article_repository
        self._timeout_seconds = timeout_seconds
        self._lookback_days = lookback_days

    def collect_all(self, *, reference_date: date) -> list[SourceCollectionResult]:
        """Collect every active `type == "rss"` source, one by one.

        A source whose fetch or parse fails is recorded as a failed
        `SourceCollectionResult` (logged) and does not stop the remaining
        sources from being collected (TASK-007 spec §14). Inactive
        sources, and active sources of type `api` or `html`, are not
        fetched at all — `RssCollector` handles `rss` only (TASK-007
        spec §4).

        Args:
            reference_date: "today", against which each entry's freshness
                is measured (TASK-028). Required, not defaulted, so this
                module never computes its own notion of "now" — the caller
                (the CLI) is the single place that does.
        """
        rss_sources = [
            source for source in self._source_repository.list_active() if source.type == "rss"
        ]
        return [
            self.collect_source(source, reference_date=reference_date) for source in rss_sources
        ]

    def collect_source(self, source: Source, *, reference_date: date) -> SourceCollectionResult:
        """Fetch, parse and persist articles for a single RSS source.

        `Source.last_fetched_at` is updated to the collection time only
        when the fetch and parse succeed (TASK-007 spec §12); it is left
        untouched on failure.

        Args:
            reference_date: see `collect_all`.

        Raises:
            ValueError: if `source.type` is not `"rss"` — `RssCollector`
                does not handle `api` or `html` sources (TASK-007 spec §4).
        """
        if source.type != "rss":
            raise ValueError(f"RssCollector only handles type='rss' sources, got {source.type!r}")
        assert source.id is not None  # sources from list_active() always have a persisted id

        try:
            response = requests.get(source.url, timeout=self._timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to fetch source %r (%s): %s", source.name, source.url, exc)
            return SourceCollectionResult(source=source, error=str(exc))

        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Failed to parse feed for source %r (%s): %s",
                source.name,
                source.url,
                parsed.get("bozo_exception"),
            )
            return SourceCollectionResult(source=source, error="Malformed feed")

        fetched_at = _utc_now_iso()
        result = SourceCollectionResult(source=source)
        for entry in parsed.entries:
            article = _entry_to_article(entry, source_id=source.id, fetched_at=fetched_at)
            if article is None:
                logger.debug("Skipping unusable entry from source %r (%s)", source.name, source.url)
                continue

            if self._article_repository.get_by_url(article.url) is not None:
                result.skipped_duplicates += 1
                continue

            if _is_too_old(article.published_at, reference_date, self._lookback_days):
                result.skipped_stale += 1
                continue

            result.created.append(self._article_repository.create(article))

        self._source_repository.update(source.model_copy(update={"last_fetched_at": fetched_at}))
        logger.info(
            "Collected source %r: %d new, %d duplicates skipped, %d stale skipped",
            source.name,
            len(result.created),
            result.skipped_duplicates,
            result.skipped_stale,
        )
        return result


def _entry_to_article(entry: Any, *, source_id: int, fetched_at: str) -> Article | None:
    """Build an `Article` from one feedparser entry, or `None` if unusable.

    An entry with no usable `url` (or otherwise failing `Article`
    validation, e.g. no usable `title`) cannot become an `Article`
    (TASK-007 spec §9) and is reported as `None` for the caller to skip.
    """
    url = entry.get("link")
    if not url:
        return None

    try:
        return Article(
            source_id=source_id,
            title=entry.get("title"),
            url=url,
            published_at=_entry_published_at(entry),
            fetched_at=fetched_at,
            raw_excerpt=_entry_raw_excerpt(entry),
        )
    except ValidationError:
        return None


def _entry_published_at(entry: Any) -> str | None:
    """Return the entry's publication date as UTC ISO-8601, or `None`.

    `feedparser` exposes a successfully parsed date as a UTC
    `time.struct_time` in `published_parsed` (falling back to
    `updated_parsed`). Absence is preserved rather than invented
    (TASK-007 spec §9): an entry with neither returns `None`.
    """
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time is None:
        return None
    year, month, day, hour, minute, second = parsed_time[:6]
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC).isoformat()


def _is_too_old(published_at: str | None, reference_date: date, lookback_days: int) -> bool:
    """Return whether `published_at` is older than `lookback_days` before `reference_date`.

    Mirrors `app.pipeline.ranking_factors._novelty`'s own day-level
    comparison (compare calendar dates, not exact instants -- consistent
    with the precision already accepted elsewhere in this codebase). `None`
    or an unparsable `published_at` is never "too old": absence of a date
    is unknown, not evidence of staleness (CLAUDE.md §17), so such an entry
    is always kept by this check.
    """
    if published_at is None:
        return False
    try:
        published_date = datetime.fromisoformat(published_at).date()
    except ValueError:
        return False
    return (reference_date - published_date).days > lookback_days


def _entry_raw_excerpt(entry: Any) -> str:
    """Return the entry's raw summary/description/content, or `""`.

    `feedparser` normalizes RSS `description` and Atom `summary` into
    `entry.summary`; Atom `content` (full-text entries without a separate
    summary) is exposed separately as a list. No rewriting or
    normalization is applied (TASK-007 spec §9).
    """
    summary = entry.get("summary")
    if summary:
        return str(summary)

    content = entry.get("content")
    if content:
        value = content[0].get("value")
        if value:
            return str(value)

    return ""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
