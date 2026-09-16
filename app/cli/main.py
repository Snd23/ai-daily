"""`ai-daily` command-line interface (TASK-023).

Implements the command surface planned by docs/PRD.md §32
(`collect` / `process` / `generate` / `run`), wired to the already-existing,
already-tested pipeline stages:

    collect  -> load_sources_config + sync_sources + RssCollector.collect_all
    process  -> normalize_pending_articles + deduplicate_pending_articles

`generate` and `run` are deliberate stubs: the stages they would need
(CLASSIFY, `Event`/`event_content` persistence integration, editorial
assembly wired to real data, PDF rendering wired to a persisted `Edition`)
are not implemented yet (docs/ARCHITECTURE.md §4.7, ambiguities #8/#9 in
§6) and are explicitly out of scope for this task -- see TODO.md,
TASK-024 ("Full pipeline"). They exist as commands (so the CLI surface
already matches PRD §32) but do no work and never reach a database
connection or any downstream stage.

Every command shares one bootstrap: `configure_logging()` runs once, in
the app-level Typer callback, before any command body executes.
"""

from __future__ import annotations

import logging
import sqlite3

import typer

from app.collectors.rss import RssCollector
from app.config import (
    DEFAULT_SOURCES_PATH,
    ConfigurationError,
    load_settings,
    load_sources_config,
    sync_sources,
)
from app.database import ArticleRepository, SourceRepository, get_connection, run_migrations
from app.deduplication import deduplicate_pending_articles
from app.logging_config import configure_logging
from app.normalization import normalize_pending_articles

logger = logging.getLogger(__name__)

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

_NOT_IMPLEMENTED_MESSAGE = (
    "'{command}' is not implemented yet: the full pipeline (clustering, "
    "verification, ranking, summarization, editorial assembly and PDF "
    "rendering wired end-to-end) is TASK-024, not TASK-023. "
    "See TODO.md and docs/ARCHITECTURE.md (sections 4.7 and 6)."
)


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

        results = RssCollector(source_repository, article_repository).collect_all()
    except _CRITICAL_ERRORS as exc:
        typer.echo(f"collect failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        connection.close()

    created = sum(len(result.created) for result in results)
    duplicates = sum(result.skipped_duplicates for result in results)
    failed = [result for result in results if not result.succeeded]

    logger.info(
        "Collect complete: %d source(s) processed, %d new article(s), "
        "%d duplicate(s) skipped, %d source(s) failed",
        len(results),
        created,
        duplicates,
        len(failed),
    )
    typer.echo(
        f"Collected {len(results)} source(s): {created} new article(s), "
        f"{duplicates} duplicate(s) skipped, {len(failed)} source(s) failed."
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
def generate() -> None:
    """Generate the PDF edition -- not implemented yet (see TASK-024)."""
    typer.echo(_NOT_IMPLEMENTED_MESSAGE.format(command="generate"), err=True)
    raise typer.Exit(code=1)


@app.command()
def run() -> None:
    """Run the full pipeline end-to-end -- not implemented yet (see TASK-024)."""
    typer.echo(_NOT_IMPLEMENTED_MESSAGE.format(command="run"), err=True)
    raise typer.Exit(code=1)
