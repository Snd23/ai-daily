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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import responses
from typer.testing import CliRunner

from app.cli import main as cli_main
from app.cli.main import app
from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider

runner = CliRunner()

_SUMMARY_RESPONSE = "TITLE: Example Story\nSUMMARY: Something happened on Monday."

# Resolved from this file, not from the working directory: the `workspace`
# fixture chdirs away from the repository root.
_REPOSITORY_LABELS = Path(__file__).resolve().parent.parent / "config" / "labels.yaml"

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

def _rfc822(days_ago: int) -> str:
    """An RFC-822 `pubDate` string `days_ago` days before real "now".

    Computed relative to the real clock (not a fixed calendar date): TASK-028's
    `collect` command filters entries by age against `datetime.now(APP_TIMEZONE)`,
    so a fixed date would eventually fall outside the default lookback window
    and start failing these date-agnostic collection tests for an unrelated
    reason.
    """
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _rss_feed() -> str:
    """Two entries, both well within the default `NEWS_LOOKBACK_DAYS` (2)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>First Article</title>
      <link>https://example.com/first</link>
      <description>&lt;p&gt;First summary&lt;/p&gt;</description>
      <pubDate>{_rfc822(0)}</pubDate>
    </item>
    <item>
      <title>Second Article</title>
      <link>https://example.com/second</link>
      <description>&lt;p&gt;Second summary&lt;/p&gt;</description>
      <pubDate>{_rfc822(1)}</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated CWD with its own `config/` directory and `DATABASE_URL`.

    `config/labels.yaml` is copied from the repository rather than
    rewritten here: `generate` resolves section labels through
    `app.config.labels.load_labels`, which reads that path relative to the
    working directory, exactly as `collect` reads `config/sources.yaml`.
    Copying the real file keeps the test honest instead of asserting
    against a private, drifting copy of the labels.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    (tmp_path / "config" / "labels.yaml").write_text(
        _REPOSITORY_LABELS.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    # collect/process never touch the LLM provider; cleared so a developer's
    # real .env (if ever found) cannot leak into or break these tests.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    yield db_path


@pytest.fixture
def fake_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the CLI's provider factory so no real API client is built.

    Only this one boundary is faked: `generate` still runs the real
    clustering, verification, ranking, editorial and rendering stages
    against the real SQLite database (they are covered end-to-end in
    `tests/test_pipeline_generation.py`).
    """

    class _FakeProvider(LLMProvider):
        def complete(self, request: CompletionRequest) -> CompletionResponse:
            text = "\n".join(message.content for message in request.messages)
            if "HAS_DEVELOPER_IMPACT" in text:
                return CompletionResponse(text="HAS_DEVELOPER_IMPACT: no")
            return CompletionResponse(text=_SUMMARY_RESPONSE)

    monkeypatch.setattr(cli_main, "create_llm_provider", lambda settings: _FakeProvider())


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
    responses.add(responses.GET, "https://example.com/feed", body=_rss_feed(), status=200)

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
def test_collect_skips_an_article_older_than_the_lookback_window(workspace: Path) -> None:
    stale_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>Old Article</title>
      <link>https://example.com/old</link>
      <description>Old summary</description>
      <pubDate>{_rfc822(30)}</pubDate>
    </item>
  </channel>
</rss>
"""
    responses.add(responses.GET, "https://example.com/feed", body=stale_feed, status=200)

    result = runner.invoke(app, ["collect"])

    assert result.exit_code == 0, result.output
    assert "0 new article" in result.output
    assert "1 stale skipped" in result.output

    connection = _connect(workspace)
    try:
        assert ArticleRepository(connection).get_by_url("https://example.com/old") is None
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


# --- generate ---------------------------------------------------------------


def _seed_one_article(db_path: Path) -> None:
    """Persist one already-normalized article, ready to be clustered.

    `published_at` is "now" (not a fixed calendar date): `generate` defaults
    `edition_day` to the real current date, and TASK-028's `list_clusterable`
    safety net filters on age against it, so a fixed date would eventually
    fall outside the default lookback window for a reason unrelated to what
    these tests actually exercise.
    """
    connection = _connect(db_path)
    try:
        source = SourceRepository(connection).create(
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
        now = datetime.now(UTC).isoformat()
        ArticleRepository(connection).create(
            Article(
                source_id=source.id,
                title="Example Story",
                url="https://example.com/story",
                published_at=now,
                fetched_at=now,
                raw_excerpt="<p>Something happened.</p>",
                normalized_text="Something happened.",
                content_hash="hash-story",
                language="en",
            )
        )
    finally:
        connection.close()


def test_generate_writes_a_pdf_and_reports_it(
    workspace: Path, fake_llm_provider: None
) -> None:
    _seed_one_article(workspace)

    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 0, result.output
    assert "1 event(s)" in result.output
    pdf_path = workspace.parent / "editions" / f"{date.today().isoformat()}-it.pdf"
    assert pdf_path.exists()
    assert str(pdf_path) in result.output


def test_generate_uses_the_configured_default_language(
    workspace: Path, fake_llm_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEFAULT_LANGUAGE", "en")
    _seed_one_article(workspace)

    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 0, result.output
    assert (workspace.parent / "editions" / f"{date.today().isoformat()}-en.pdf").exists()


def test_generate_accepts_an_explicit_language(
    workspace: Path, fake_llm_provider: None
) -> None:
    _seed_one_article(workspace)

    result = runner.invoke(app, ["generate", "--language", "en"])

    assert result.exit_code == 0, result.output
    assert (workspace.parent / "editions" / f"{date.today().isoformat()}-en.pdf").exists()


def test_generate_rejects_an_unsupported_language(
    workspace: Path, fake_llm_provider: None
) -> None:
    result = runner.invoke(app, ["generate", "--language", "fr"])

    assert result.exit_code == 1
    assert "generate failed" in result.output
    assert "Traceback" not in result.output


def test_generate_reports_a_missing_api_key_cleanly(workspace: Path) -> None:
    """No provider is patched here: the real factory must fail cleanly."""
    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 1
    assert "generate failed" in result.output
    assert "Traceback" not in result.output


# --- run ---------------------------------------------------------------------


@responses.activate
def test_run_executes_collect_process_and_generate(
    workspace: Path, fake_llm_provider: None
) -> None:
    responses.add(responses.GET, "https://example.com/feed", body=_rss_feed(), status=200)

    result = runner.invoke(app, ["run", "--language", "en"])

    assert result.exit_code == 0, result.output
    # collect
    assert "2 new article" in result.output
    # process
    assert "Normalized 2 article" in result.output
    # generate
    assert (workspace.parent / "editions" / f"{date.today().isoformat()}-en.pdf").exists()


def test_run_stops_at_the_first_failing_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no config/sources.yaml here
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'data' / 'db').as_posix()}")

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "collect failed" in result.output
    # generate never ran, so no edition directory was created
    assert not (tmp_path / "data" / "editions").exists()


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
