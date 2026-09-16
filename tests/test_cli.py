"""Tests for the `ai-daily` CLI (TASK-023).

Uses `typer.testing.CliRunner` against the real `app.cli.main.app`. Every
test runs in an isolated temporary working directory (`monkeypatch.chdir`)
with its own `config/sources.yaml` and its own file-based SQLite database
(via `DATABASE_URL`), so tests never touch the repository's real
`config/sources.yaml` or `data/ai_daily.db`, and never make a real HTTP
request (`responses`, already a dev dependency for
`tests/test_rss_collector.py`).

A file-based database (not `sqlite:///:memory:`) is required here: each CLI
invocation opens its own connection (`app.cli.main.collect`/`process`), so
an in-memory database would not survive between two separate `CliRunner.
invoke()` calls the way it does within a single test's shared fixture
connection in `tests/test_rss_collector.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
import responses
from typer.testing import CliRunner

from app.cli.main import app
from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

runner = CliRunner()

_SOURCES_YAML = """
sources:
  - name: Example Source
    type: rss
    url: https://example.com/feed
    tier: 1
    categories:
      - models
    reliability_weight: 1.0
    is_active: true
"""

_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>First Article</title>
      <link>https://example.com/first</link>
      <description>&lt;p&gt;First summary&lt;/p&gt;</description>
      <pubDate>Tue, 01 Sep 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Article</title>
      <link>https://example.com/second</link>
      <description>&lt;p&gt;Second summary&lt;/p&gt;</description>
      <pubDate>Wed, 02 Sep 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated CWD with its own `config/sources.yaml` and `DATABASE_URL`."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    # collect/process never touch the LLM provider; cleared so a developer's
    # real .env (if ever found) cannot leak into or break these tests.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    yield db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = get_connection(f"sqlite:///{db_path.as_posix()}")
    run_migrations(connection)
    return connection


# --- CLI surface -------------------------------------------------------


def test_help_lists_all_four_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("collect", "process", "generate", "run"):
        assert command in result.output


@pytest.mark.parametrize("command", ["collect", "process", "generate", "run"])
def test_each_command_has_working_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])

    assert result.exit_code == 0
    assert "Usage" in result.output


# --- collect -------------------------------------------------------------


@responses.activate
def test_collect_persists_sources_and_articles(workspace: Path) -> None:
    responses.add(responses.GET, "https://example.com/feed", body=_RSS_FEED, status=200)

    result = runner.invoke(app, ["collect"])

    assert result.exit_code == 0, result.output
    assert "2 new article" in result.output

    connection = _connect(workspace)
    try:
        source = SourceRepository(connection).get_by_url("https://example.com/feed")
        assert source is not None
        assert source.name == "Example Source"

        article_repository = ArticleRepository(connection)
        first = article_repository.get_by_url("https://example.com/first")
        second = article_repository.get_by_url("https://example.com/second")
        assert first is not None
        assert second is not None
        assert first.status == "pending"
    finally:
        connection.close()


@responses.activate
def test_collect_does_not_make_unmocked_requests(workspace: Path) -> None:
    """`responses` raises on any request that was not explicitly registered."""
    result = runner.invoke(app, ["collect"])

    # The unmocked request is caught inside RssCollector.collect_source
    # (TASK-007 resilience) and reported as a failed source, not a crash.
    assert result.exit_code == 0, result.output
    assert "1 source(s) failed" in result.output


# --- process ---------------------------------------------------------------


def test_process_normalizes_and_deduplicates(workspace: Path) -> None:
    connection = _connect(workspace)
    try:
        source_repository = SourceRepository(connection)
        source = source_repository.create(
            Source(
                name="Example Source",
                type="rss",
                url="https://example.com/feed",
                tier=1,
                categories=["models"],
                reliability_weight=1.0,
                is_active=True,
            )
        )
        assert source.id is not None

        article_repository = ArticleRepository(connection)
        article_repository.create(
            Article(
                source_id=source.id,
                title="Same Story A",
                url="https://example.com/a",
                fetched_at="2026-09-01T00:00:00+00:00",
                raw_excerpt="<p>Identical content</p>",
            )
        )
        article_repository.create(
            Article(
                source_id=source.id,
                title="Same Story B",
                url="https://example.com/b",
                fetched_at="2026-09-01T00:00:00+00:00",
                raw_excerpt="<p>Identical content</p>",
            )
        )
    finally:
        connection.close()

    result = runner.invoke(app, ["process"])

    assert result.exit_code == 0, result.output
    assert "Normalized 2 article" in result.output
    assert "1 duplicate(s) marked" in result.output

    connection = _connect(workspace)
    try:
        article_repository = ArticleRepository(connection)
        refreshed_first = article_repository.get_by_url("https://example.com/a")
        refreshed_second = article_repository.get_by_url("https://example.com/b")
        assert refreshed_first is not None
        assert refreshed_second is not None
        assert refreshed_first.content_hash is not None
        assert refreshed_second.content_hash is not None

        statuses = {refreshed_first.status, refreshed_second.status}
        assert statuses == {"pending", "discarded"}
        discarded = refreshed_first if refreshed_first.status == "discarded" else refreshed_second
        canonical = refreshed_second if discarded is refreshed_first else refreshed_first
        assert discarded.duplicate_of == canonical.id
    finally:
        connection.close()


# --- generate / run stubs ---------------------------------------------------


def test_generate_is_a_stub_that_fails_explicitly(workspace: Path) -> None:
    result = runner.invoke(app, ["generate"])

    assert result.exit_code != 0
    assert "not implemented yet" in result.output
    assert "TASK-024" in result.output
    assert not (workspace).exists()  # no database was ever created


def test_run_is_a_stub_that_fails_explicitly(workspace: Path) -> None:
    result = runner.invoke(app, ["run"])

    assert result.exit_code != 0
    assert "not implemented yet" in result.output
    assert "TASK-024" in result.output
    assert not (workspace).exists()  # no database was ever created


# --- error handling ----------------------------------------------------


def test_collect_reports_missing_sources_file_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no config/sources.yaml here
    db_path = tmp_path / "data" / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    result = runner.invoke(app, ["collect"])

    assert result.exit_code == 1
    assert "collect failed" in result.output
    assert "Sources file not found" in result.output
    # no traceback leaked to the user
    assert "Traceback" not in result.output
