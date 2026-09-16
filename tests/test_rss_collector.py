"""Tests for `RssCollector` (TASK-007).

All HTTP access is mocked with `responses` — no test depends on a real,
live feed (TASK-007 spec §16). Uses the same migrated in-memory SQLite
fixture pattern as `tests/test_source_repository.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
import responses

from app.collectors.rss import RssCollector
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

# Every fixed feed date below ("01/02 Sep 2026") is evaluated against this
# reference date, chosen to sit right at the most recent of those dates so
# the default `lookback_days` (2, see `app.config.settings`) never excludes
# them -- these tests are about parsing/selection, not freshness (TASK-028
# has its own dedicated tests below).
_REFERENCE_DATE = date(2026, 9, 2)

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>First Article</title>
      <link>https://example.com/first</link>
      <description>First summary</description>
      <pubDate>Tue, 01 Sep 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Article</title>
      <link>https://example.com/second</link>
      <description>Second summary</description>
      <pubDate>Wed, 02 Sep 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Feed</title>
  <link href="https://example.com/"/>
  <id>https://example.com/</id>
  <updated>2026-09-01T10:00:00Z</updated>
  <entry>
    <title>Atom Article</title>
    <link href="https://example.com/atom-article"/>
    <id>https://example.com/atom-article</id>
    <updated>2026-09-01T10:00:00Z</updated>
    <summary>Atom summary</summary>
  </entry>
</feed>
"""

FEED_WITHOUT_DATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>No Date Article</title>
      <link>https://example.com/no-date</link>
      <description>No date summary</description>
    </item>
  </channel>
</rss>
"""

FEED_WITHOUT_URL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>No URL Article</title>
      <description>No url summary</description>
    </item>
    <item>
      <title>Valid Article</title>
      <link>https://example.com/valid</link>
      <description>Valid summary</description>
    </item>
  </channel>
</rss>
"""

MALFORMED_FEED = "this is not a valid feed"


def _make_source(**overrides: object) -> Source:
    values: dict[str, object] = {
        "name": "Example Source",
        "type": "rss",
        "url": "https://example.com/feed",
        "tier": 1,
        "categories": ["models"],
        "reliability_weight": 1.0,
        "is_active": True,
    }
    values.update(overrides)
    return Source(**values)  # type: ignore[arg-type]


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def source_repository(connection: sqlite3.Connection) -> SourceRepository:
    run_migrations(connection)
    return SourceRepository(connection)


@pytest.fixture
def article_repository(connection: sqlite3.Connection) -> ArticleRepository:
    return ArticleRepository(connection)


@pytest.fixture
def collector(
    source_repository: SourceRepository, article_repository: ArticleRepository
) -> RssCollector:
    return RssCollector(source_repository, article_repository)


# --- feed parsing ----------------------------------------------------------


@responses.activate
def test_valid_rss_feed_produces_correct_articles(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=RSS_FEED, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert [a.title for a in result.created] == ["First Article", "Second Article"]
    assert result.created[0].url == "https://example.com/first"
    assert result.created[0].published_at == "2026-09-01T10:00:00+00:00"


@responses.activate
def test_valid_atom_feed_produces_correct_articles(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=ATOM_FEED, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert len(result.created) == 1
    article = result.created[0]
    assert article.title == "Atom Article"
    assert article.url == "https://example.com/atom-article"
    assert article.raw_excerpt == "Atom summary"


@responses.activate
def test_multiple_entries_produce_multiple_articles(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=RSS_FEED, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert len(result.created) == 2


@responses.activate
def test_missing_publication_date_is_not_invented(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=FEED_WITHOUT_DATE, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert len(result.created) == 1
    assert result.created[0].published_at is None


@responses.activate
def test_entry_without_usable_url_is_skipped(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=FEED_WITHOUT_URL, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert [a.title for a in result.created] == ["Valid Article"]


@responses.activate
def test_http_error_fails_the_source_without_raising(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, status=500)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert not result.succeeded
    assert result.error is not None
    assert not result.created


@responses.activate
def test_malformed_feed_is_handled_safely(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=MALFORMED_FEED, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert not result.succeeded
    assert not result.created


# --- freshness (TASK-028) ---------------------------------------------------


def _rfc822(day: date) -> str:
    """Format `day` (at a fixed time of day) as an RFC-822 `pubDate` string."""
    return datetime(day.year, day.month, day.day, 10, 0, 0, tzinfo=UTC).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )


def _feed_with_pub_date(pub_date: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com</link>
    <description>Example</description>
    <item>
      <title>Freshness Article</title>
      <link>https://example.com/freshness</link>
      <description>Freshness summary</description>
      <pubDate>{pub_date}</pubDate>
    </item>
  </channel>
</rss>
"""


@responses.activate
def test_article_within_the_lookback_window_is_collected(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    """`collector` defaults to `lookback_days=2` (Settings' own default)."""
    source = source_repository.create(_make_source())
    one_day_before = _REFERENCE_DATE - timedelta(days=1)
    body = _feed_with_pub_date(_rfc822(one_day_before))
    responses.add(responses.GET, source.url, body=body, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert len(result.created) == 1
    assert result.skipped_stale == 0


@responses.activate
def test_article_exactly_on_the_lookback_boundary_is_collected(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    """Exactly `lookback_days` (2) days before `reference_date`: inclusive boundary."""
    source = source_repository.create(_make_source())
    on_boundary = _REFERENCE_DATE - timedelta(days=2)
    body = _feed_with_pub_date(_rfc822(on_boundary))
    responses.add(responses.GET, source.url, body=body, status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert len(result.created) == 1
    assert result.skipped_stale == 0


@responses.activate
def test_article_older_than_the_lookback_window_is_skipped(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    """One day past the boundary (3 days before `reference_date`): excluded."""
    source = source_repository.create(_make_source())
    too_old = _REFERENCE_DATE - timedelta(days=3)
    responses.add(responses.GET, source.url, body=_feed_with_pub_date(_rfc822(too_old)), status=200)

    result = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert result.created == []
    assert result.skipped_stale == 1


@responses.activate
def test_article_with_no_publication_date_is_never_excluded_as_stale(
    source_repository: SourceRepository, article_repository: ArticleRepository
) -> None:
    """Absence of `published_at` is unknown, never treated as staleness
    (CLAUDE.md §17) -- true even under the tightest possible window."""
    strict_collector = RssCollector(source_repository, article_repository, lookback_days=0)
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=FEED_WITHOUT_DATE, status=200)

    result = strict_collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert result.succeeded
    assert len(result.created) == 1
    assert result.created[0].published_at is None
    assert result.skipped_stale == 0


# --- source selection ------------------------------------------------------


@responses.activate
def test_collect_all_only_fetches_active_rss_sources(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    active = source_repository.create(_make_source(name="Active", url="https://a.example/feed"))
    source_repository.create(
        _make_source(name="Inactive", url="https://b.example/feed", is_active=False)
    )
    responses.add(responses.GET, active.url, body=RSS_FEED, status=200)

    results = collector.collect_all(reference_date=_REFERENCE_DATE)

    assert [r.source.name for r in results] == ["Active"]


@responses.activate
def test_collect_all_skips_html_sources(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source_repository.create(
        _make_source(name="HTML Source", type="html", url="https://c.example/news")
    )

    results = collector.collect_all(reference_date=_REFERENCE_DATE)

    assert results == []


@responses.activate
def test_collect_all_skips_api_sources(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source_repository.create(
        _make_source(name="API Source", type="api", url="https://d.example/api")
    )

    results = collector.collect_all(reference_date=_REFERENCE_DATE)

    assert results == []


def test_collect_source_rejects_non_rss_source(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source(type="html", url="https://e.example/news"))

    with pytest.raises(ValueError, match="only handles type='rss'"):
        collector.collect_source(source, reference_date=_REFERENCE_DATE)


# --- last_fetched_at ---------------------------------------------------


@responses.activate
def test_last_fetched_at_is_updated_after_successful_collection(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=RSS_FEED, status=200)

    collector.collect_source(source, reference_date=_REFERENCE_DATE)

    updated = source_repository.get_by_id(source.id)  # type: ignore[arg-type]
    assert updated is not None
    assert updated.last_fetched_at is not None


@responses.activate
def test_last_fetched_at_is_not_updated_after_failed_collection(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, status=500)

    collector.collect_source(source, reference_date=_REFERENCE_DATE)

    updated = source_repository.get_by_id(source.id)  # type: ignore[arg-type]
    assert updated is not None
    assert updated.last_fetched_at is None


# --- integration behavior ------------------------------------------------


@responses.activate
def test_one_failing_source_does_not_prevent_others_from_being_processed(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    good_a = source_repository.create(_make_source(name="Good A", url="https://a.example/feed"))
    bad = source_repository.create(_make_source(name="Bad", url="https://b.example/feed"))
    good_c = source_repository.create(_make_source(name="Good C", url="https://c.example/feed"))
    responses.add(responses.GET, good_a.url, body=RSS_FEED, status=200)
    responses.add(responses.GET, bad.url, status=500)
    responses.add(responses.GET, good_c.url, body=ATOM_FEED, status=200)

    results = collector.collect_all(reference_date=_REFERENCE_DATE)

    by_name = {r.source.name: r for r in results}
    assert by_name["Good A"].succeeded
    assert not by_name["Bad"].succeeded
    assert by_name["Good C"].succeeded


@responses.activate
def test_rerunning_the_same_feed_does_not_create_duplicate_articles(
    collector: RssCollector, source_repository: SourceRepository
) -> None:
    source = source_repository.create(_make_source())
    responses.add(responses.GET, source.url, body=RSS_FEED, status=200)
    responses.add(responses.GET, source.url, body=RSS_FEED, status=200)

    first = collector.collect_source(source, reference_date=_REFERENCE_DATE)
    second = collector.collect_source(source, reference_date=_REFERENCE_DATE)

    assert len(first.created) == 2
    assert len(second.created) == 0
    assert second.skipped_duplicates == 2
