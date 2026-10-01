"""`ai-daily` command-line interface (TASK-023).

Implements the command surface of docs/PRD.md §32
(`collect` / `process` / `generate` / `run`), wired to the already-existing,
already-tested pipeline stages:

    collect   -> load_sources_config + sync_sources + RssCollector.collect_all
    process   -> normalize_pending_articles + deduplicate_pending_articles
    generate  -> app.pipeline.generate_edition (TASK-024)
    run       -> collect, then process, then generate

This module stays a thin adapter (docs/ARCHITECTURE.md §4.13): it loads
settings, opens one connection per invocation, builds the LLM provider and
reports results. Stage sequencing and every domain decision live in
`app/pipeline/` (§4.14), not here -- `run` simply calls the other three
command functions in order, so it duplicates none of their wiring and
stops at the first one that fails.

Every command shares one bootstrap: `configure_logging()` runs once, in
the app-level Typer callback, before any command body executes.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import typer

from app.collectors.rss import RssCollector
from app.config import (
    APP_TIMEZONE,
    DEFAULT_SOURCES_PATH,
    ConfigurationError,
    Settings,
    load_settings,
    load_sources_config,
    sync_sources,
)
from app.config.settings import SUPPORTED_LANGUAGES
from app.database import ArticleRepository, SourceRepository, get_connection, run_migrations
from app.deduplication import deduplicate_pending_articles
from app.llm import RetryingProvider, create_llm_provider
from app.logging_config import configure_logging
from app.normalization import normalize_pending_articles
from app.pipeline import generate_edition

logger = logging.getLogger(__name__)

_SQLITE_URL_PREFIX = "sqlite:///"
_EDITIONS_DIRNAME = "editions"

app = typer.Typer(
    name="ai-daily",
    help="AI Daily -- automated AI news intelligence & newspaper generator.",
    no_args_is_help=True,
)

# Critical, global failure modes a command must report cleanly instead of
# letting a raw traceback reach the terminal (CLAUDE.md §32): invalid/missing
# configuration and genuine SQLite/filesystem infrastructure failures. Any
# other exception is an unanticipated programming error and is left to
# propagate, per CLAUDE.md §32 ("do not hide errors").
_CRITICAL_ERRORS = (ConfigurationError, sqlite3.Error, OSError)

def _editions_dir(settings: Settings) -> Path:
    """Return the directory generated PDFs are written to.

    Derived from the already-configured `DATABASE_URL` rather than from a
    new setting: editions live next to the database that describes them
    (`sqlite:///data/ai_daily.db` -> `data/editions`). An in-memory
    database has no directory of its own, so the default `data/` location
    is used.
    """
    path = settings.database_url.removeprefix(_SQLITE_URL_PREFIX)
    if path == ":memory:":
        return Path("data") / _EDITIONS_DIRNAME
    return Path(path).parent / _EDITIONS_DIRNAME


@app.callback()
def main() -> None:
    """AI Daily CLI."""
    configure_logging()


@app.command()
def collect() -> None:
    """Fetch active RSS sources into the database (docs/PRD.md, section 6)."""
    settings = load_settings()
    connection = get_connection(settings.database_url)
    try:
        run_migrations(connection)
        source_repository = SourceRepository(connection)
        article_repository = ArticleRepository(connection)

        configured = load_sources_config(DEFAULT_SOURCES_PATH)
        sync_result = sync_sources(source_repository, configured)
        logger.info(
            "Sources synced: %d created, %d updated, %d deactivated, %d unchanged",
            len(sync_result.created),
            len(sync_result.updated),
            len(sync_result.deactivated),
            len(sync_result.unchanged),
        )

        collector = RssCollector(
            source_repository, article_repository, lookback_days=settings.news_lookback_days
        )
        # Same "today" expression `generate_edition` defaults `edition_day`
        # to (TASK-028, docs/ARCHITECTURE.md §4.15) -- the one place this
        # process asks "what day is it", so collect's freshness gate and
        # generate's safety net stay consistent without sharing state.
        reference_date = datetime.now(APP_TIMEZONE).date()
        results = collector.collect_all(reference_date=reference_date)
    except _CRITICAL_ERRORS as exc:
        typer.echo(f"collect failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        connection.close()

    created = sum(len(result.created) for result in results)
    duplicates = sum(result.skipped_duplicates for result in results)
    stale = sum(result.skipped_stale for result in results)
    failed = [result for result in results if not result.succeeded]

    logger.info(
        "Collect complete: %d source(s) processed, %d new article(s), "
        "%d duplicate(s) skipped, %d stale skipped, %d source(s) failed",
        len(results),
        created,
        duplicates,
        stale,
        len(failed),
    )
    typer.echo(
        f"Collected {len(results)} source(s): {created} new article(s), "
        f"{duplicates} duplicate(s) skipped, {stale} stale skipped, "
        f"{len(failed)} source(s) failed."
    )
    for result in failed:
        typer.echo(f"  - {result.source.name}: {result.error}", err=True)


@app.command()
def process() -> None:
    """Normalize and deduplicate pending articles (docs/PRD.md, sections 7-8)."""
    settings = load_settings()
    connection = get_connection(settings.database_url)
    try:
        run_migrations(connection)
        article_repository = ArticleRepository(connection)
        source_repository = SourceRepository(connection)

        normalization_result = normalize_pending_articles(article_repository)
        deduplication_result = deduplicate_pending_articles(
            article_repository, source_repository
        )
    except _CRITICAL_ERRORS as exc:
        typer.echo(f"process failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        connection.close()

    logger.info(
        "Process complete: %d article(s) normalized (%d failed), "
        "%d duplicate(s) marked (%d new group(s), %d reattachment(s))",
        len(normalization_result.succeeded),
        len(normalization_result.failed),
        deduplication_result.duplicates_marked,
        len(deduplication_result.succeeded),
        len(deduplication_result.reattached),
    )
    typer.echo(
        f"Normalized {len(normalization_result.succeeded)} article(s) "
        f"({len(normalization_result.failed)} failed)."
    )
    typer.echo(
        f"Deduplication: {deduplication_result.duplicates_marked} duplicate(s) marked "
        f"({len(deduplication_result.succeeded)} new group(s), "
        f"{len(deduplication_result.reattached)} reattachment(s))."
    )


@app.command()
def generate(
    language: str | None = typer.Option(
        None,
        "--language",
        help=(
            "Edition language "
            f"({', '.join(SUPPORTED_LANGUAGES)}); defaults to DEFAULT_LANGUAGE."
        ),
    ),
) -> None:
    """Generate one edition from already-collected articles and write its PDF."""
    settings = load_settings()
    edition_language = language or settings.default_language
    if edition_language not in SUPPORTED_LANGUAGES:
        typer.echo(
            f"generate failed: language must be one of {SUPPORTED_LANGUAGES}, "
            f"got {edition_language!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    connection = get_connection(settings.database_url)
    try:
        run_migrations(connection)
        result = generate_edition(
            connection,
            RetryingProvider(
                create_llm_provider(settings),
                min_interval_seconds=settings.llm_min_interval_seconds,
            ),
            language=edition_language,
            output_dir=_editions_dir(settings),
            lookback_days=settings.news_lookback_days,
        )
    except _CRITICAL_ERRORS as exc:
        typer.echo(f"generate failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        connection.close()

    typer.echo(
        f"Edition {result.edition_number} ({result.edition_date.isoformat()}, "
        f"{result.language}): {result.events_in_edition} event(s), "
        f"{result.events_created} created this run, "
        f"{len(result.failed_events)} skipped."
    )
    typer.echo(f"PDF written to {result.pdf_path} ({result.pdf_bytes} bytes).")
    for event_id, error in result.failed_events:
        typer.echo(f"  - event {event_id}: {error}", err=True)


@app.command()
def run(
    language: str | None = typer.Option(
        None,
        "--language",
        help=(
            "Edition language "
            f"({', '.join(SUPPORTED_LANGUAGES)}); defaults to DEFAULT_LANGUAGE."
        ),
    ),
) -> None:
    """Run the full pipeline: collect, then process, then generate."""
    collect()
    process()
    generate(language=language)
