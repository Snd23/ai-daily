"""Integration and end-to-end tests for `app.pipeline.generation` (TASK-024).

Uses a real, file-based SQLite database and the real clustering,
verification, ranking, category assignment, editorial and PDF-rendering
stages: only the `LLMProvider` is a fake, since it is the one boundary
that would otherwise make a network call. Nothing internal is mocked.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from app.config.settings import DEFAULT_NEWS_LOOKBACK_DAYS
from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.edition_repository import EditionRepository
from app.database.event import Event, VerificationStatus
from app.database.event_content_repository import EventContentRepository
from app.database.event_repository import EventRepository
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository
from app.editorial.edition import Edition
from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Usage
from app.pipeline import generation as generation_module
from app.pipeline.generation import EmptyEditionError, generate_edition

_EDITION_DATE = date(2026, 9, 16)
_SUMMARY_RESPONSE = "TITLE: OpenAI ships Model X\nSUMMARY: OpenAI released Model X on Monday."
_DEVELOPER_IMPACT_RESPONSE = (
    "HAS_DEVELOPER_IMPACT: yes\n"
    "IMPACT_SUMMARY: A new endpoint is available.\n"
    "TECHNICAL_AREA: api, sdk\n"
    "BREAKING_CHANGE: no"
)


class _FakeLLMProvider(LLMProvider):
    """Answers each stage with a valid canned response for its own contract."""

    def __init__(
        self,
        *,
        summary_response: str = _SUMMARY_RESPONSE,
        developer_impact_response: str = _DEVELOPER_IMPACT_RESPONSE,
        fail_with: Exception | None = None,
    ) -> None:
        self.summary_response = summary_response
        self.developer_impact_response = developer_impact_response
        self.fail_with = fail_with
        # Content generation calls only; the analysis-phase calls (cluster merge,
        # AI relevance filter) are recorded apart in `analysis_requests`.
        self.requests: list[CompletionRequest] = []
        self.analysis_requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        text = "\n".join(message.content for message in request.messages)
        is_analysis = "event grouping stage" in text or "relevance filter stage" in text
        (self.analysis_requests if is_analysis else self.requests).append(request)
        if self.fail_with is not None:
            raise self.fail_with
        if is_analysis:
            return CompletionResponse(text="NONE")
        if "HAS_DEVELOPER_IMPACT" in text:
            return CompletionResponse(text=self.developer_impact_response)
        return CompletionResponse(text=self.summary_response)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(f"sqlite:///{(tmp_path / 'ai_daily.db').as_posix()}")
    run_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "editions"


def _add_source(connection: sqlite3.Connection, **overrides: Any) -> Source:
    values: dict[str, Any] = {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/feed",
        "tier": 1,
        "categories": ["models", "business"],
        "reliability_weight": 1.0,
        "is_active": True,
    }
    values.update(overrides)
    return SourceRepository(connection).create(Source(**values))


def _add_article(connection: sqlite3.Connection, source: Source, **overrides: Any) -> Article:
    assert source.id is not None
    values: dict[str, Any] = {
        "source_id": source.id,
        "title": "OpenAI ships Model X",
        "url": "https://openai.com/news/model-x",
        "published_at": "2026-09-16T08:00:00+00:00",
        "fetched_at": "2026-09-16T09:00:00+00:00",
        "raw_excerpt": "<p>OpenAI released Model X.</p>",
        "normalized_text": "OpenAI released Model X.",
        "content_hash": "hash-model-x",
        "language": "en",
    }
    values.update(overrides)
    return ArticleRepository(connection).create(Article(**values))


def _seed_one_event(connection: sqlite3.Connection) -> None:
    """One story reported by two different Tier 1/2 sources -> one VERIFIED event."""
    openai = _add_source(connection)
    reuters = _add_source(
        connection,
        name="Reuters",
        url="https://reuters.com/feed",
        tier=2,
        categories=["business"],
        reliability_weight=0.9,
    )
    _add_article(connection, openai)
    _add_article(
        connection,
        reuters,
        url="https://reuters.com/openai-model-x",
        content_hash="hash-model-x-reuters",
        raw_excerpt="<p>Reuters reports Model X.</p>",
        normalized_text="Reuters reports Model X.",
    )


def _generate(
    connection: sqlite3.Connection,
    output_dir: Path,
    *,
    provider: _FakeLLMProvider | None = None,
    language: str = "en",
    lookback_days: int = DEFAULT_NEWS_LOOKBACK_DAYS,
) -> Any:
    return generate_edition(
        connection,
        provider or _FakeLLMProvider(),
        language=language,
        output_dir=output_dir,
        lookback_days=lookback_days,
        edition_date=_EDITION_DATE,
    )


def _generate_expecting_empty(
    connection: sqlite3.Connection, output_dir: Path, **kwargs: Any
) -> EmptyEditionError:
    """Run generation expecting `EmptyEditionError`; no PDF may have been written."""
    with pytest.raises(EmptyEditionError) as exc_info:
        _generate(connection, output_dir, **kwargs)
    assert not list(output_dir.glob("*.pdf"))
    return exc_info.value


def _edition_status(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT status FROM edition").fetchone()
    return str(row[0])


# --- analysis phase: Article -> Event ---------------------------------------


def test_clustered_articles_become_one_event_with_real_metadata(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    result = _generate(connection, output_dir)

    assert result.events_created == 1
    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    assert len(events) == 1
    event = events[0]
    # A Tier 1 source is present, so VERIFY really ran and returned VERIFIED.
    assert event.verification_status == "VERIFIED"
    assert 0.0 < event.confidence_score <= 10.0
    assert 0.0 < event.importance_score <= 10.0
    assert event.event_type == "standard"
    # No deterministic signal identifies a future event (documented rule).
    assert event.future_date is None


def test_articles_are_attached_to_their_event_and_leave_the_pending_pool(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    _generate(connection, output_dir)

    repository = ArticleRepository(connection)
    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    event_id = events[0].id
    assert event_id is not None
    attached = repository.list_by_event(event_id)
    assert len(attached) == 2
    assert all(article.status == "processed" for article in attached)
    clusterable = repository.list_clusterable(
        reference_date=_EDITION_DATE, lookback_days=DEFAULT_NEWS_LOOKBACK_DAYS
    )
    assert clusterable == []


def test_articles_with_different_titles_form_separate_events(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )

    result = _generate(connection, output_dir)

    assert result.events_created == 2


def test_unnormalized_articles_are_not_clustered(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    source = _add_source(connection)
    _add_article(connection, source, normalized_text=None, content_hash=None)

    error = _generate_expecting_empty(connection, output_dir)

    assert _count(connection, "event") == 0
    assert error.failed_events == []


# --- freshness (TASK-028) ----------------------------------------------------


def test_an_article_older_than_the_lookback_window_creates_no_event(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    """The `list_clusterable` safety net excludes it before clustering even
    runs, even though it would otherwise cluster normally on its own."""
    source = _add_source(connection)
    _add_article(connection, source, published_at="2026-09-01T08:00:00+00:00")

    error = _generate_expecting_empty(connection, output_dir, lookback_days=2)

    assert _count(connection, "event") == 0
    assert error.failed_events == []


def test_an_article_with_no_published_at_still_creates_an_event(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    """Absence of `published_at` is unknown, never treated as staleness
    (CLAUDE.md §17) -- true even under the tightest possible window."""
    source = _add_source(connection)
    _add_article(connection, source, published_at=None)

    result = _generate(connection, output_dir, lookback_days=0)

    assert result.events_created == 1


# --- generation phase: content, editorial, PDF ------------------------------


def test_event_content_is_persisted_for_the_generated_language(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    _generate(connection, output_dir, language="en")

    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    event_id = events[0].id
    assert event_id is not None
    content = EventContentRepository(connection).get(event_id, "en")
    assert content is not None
    assert content.title == "OpenAI ships Model X"
    assert content.summary == "OpenAI released Model X on Monday."
    # The Developer Impact assessment is stored as structured content.
    assert content.structured_content is not None
    assert "developer_impact" in content.structured_content


def test_developer_impact_absence_is_stored_as_no_structured_content(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)
    provider = _FakeLLMProvider(developer_impact_response="HAS_DEVELOPER_IMPACT: no")

    _generate(connection, output_dir, provider=provider)

    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    event_id = events[0].id
    assert event_id is not None
    content = EventContentRepository(connection).get(event_id, "en")
    assert content is not None
    assert content.structured_content is None


def test_generate_writes_a_valid_pdf_with_the_expected_content(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    result = _generate(connection, output_dir)

    assert result.pdf_path.exists()
    assert result.pdf_path.name == "2026-09-16-en.pdf"
    reader = PdfReader(io.BytesIO(result.pdf_path.read_bytes()))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "AI DAILY" in text
    assert "OpenAI ships Model X" in text
    # TASK-022 source citations must still render from real data.
    assert "Reuters" in text
    assert "https://reuters.com/openai-model-x" in text


def test_the_edition_row_records_the_pdf_path(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    result = _generate(connection, output_dir)

    record = EditionRepository(connection).get_by_date_and_language("2026-09-16", "en")
    assert record is not None
    assert record.edition_number == result.edition_number
    assert record.pdf_path == str(result.pdf_path)
    assert record.status == "published"


def test_the_edition_row_stores_the_composed_edition_the_pdf_was_rendered_from(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    """TASK-043: a published edition carries its composition as JSON."""
    _seed_one_event(connection)

    _generate(connection, output_dir)

    record = EditionRepository(connection).get_by_date_and_language("2026-09-16", "en")
    assert record is not None and record.content is not None
    edition = Edition.model_validate_json(record.content)
    assert edition.language == "en"
    assert [story.title for story in edition.top_stories] == ["OpenAI ships Model X"]
    urls = {article.url for article in edition.top_stories[0].articles}
    assert "https://reuters.com/openai-model-x" in urls


def test_an_unverified_event_is_kept_out_of_top_stories(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    """Real VERIFY output must drive Top Stories selection (docs/PRD.md §4)."""
    community = _add_source(
        connection,
        name="Reddit",
        url="https://reddit.com/feed",
        tier=4,
        categories=["community"],
        reliability_weight=0.3,
    )
    _add_article(connection, community, title="Rumor about Model Z")

    _generate(connection, output_dir)

    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    assert events[0].verification_status == "UNVERIFIED"
    record = EditionRepository(connection).get_by_date_and_language("2026-09-16", "en")
    assert record is not None  # the edition is still produced


def test_an_empty_database_raises_and_writes_no_pdf(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    error = _generate_expecting_empty(connection, output_dir)

    assert "no event available" in str(error)
    assert error.failed_events == []
    assert _edition_status(connection) == "failed"


def test_an_already_published_edition_is_not_downgraded_by_an_empty_rerun(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)
    first = _generate(connection, output_dir)
    assert _edition_status(connection) == "published"
    # Every stored event content is gone and the provider now always fails.
    connection.execute("DELETE FROM event_content")
    connection.commit()

    with pytest.raises(EmptyEditionError):
        _generate(
            connection, output_dir, provider=_FakeLLMProvider(fail_with=LLMProviderError("down"))
        )

    assert _edition_status(connection) == "published"
    assert first.pdf_path.exists()


# --- rerun / idempotency ------------------------------------------------------


def test_rerunning_creates_no_duplicate_event_content_or_edition(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)
    provider = _FakeLLMProvider()

    first = _generate(connection, output_dir, provider=provider)
    calls_after_first = len(provider.requests)
    second = _generate(connection, output_dir, provider=provider)

    assert first.events_created == 1
    assert second.events_created == 0
    assert second.events_in_edition == first.events_in_edition
    assert second.edition_number == first.edition_number
    assert _count(connection, "event") == 1
    assert _count(connection, "event_content") == 1
    assert _count(connection, "edition") == 1
    # Stored content is reused: the rerun makes no further LLM call.
    assert len(provider.requests) == calls_after_first


def test_rerunning_reproduces_the_same_edition_rather_than_an_empty_one(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)

    first = _generate(connection, output_dir)
    second = _generate(connection, output_dir)

    assert second.events_in_edition == first.events_in_edition == 1
    assert second.pdf_path == first.pdf_path
    assert second.pdf_path.exists()


def test_a_second_language_reuses_the_events_of_the_first(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    """The analysis phase must not be repeated per language (docs/PRD.md §38)."""
    _seed_one_event(connection)

    english = _generate(connection, output_dir, language="en")
    italian = _generate(connection, output_dir, language="it")

    assert italian.events_created == 0
    assert _count(connection, "event") == 1
    assert _count(connection, "event_content") == 2
    assert italian.edition_number != english.edition_number
    assert italian.pdf_path.name == "2026-09-16-it.pdf"
    assert english.pdf_path.exists() and italian.pdf_path.exists()


# --- event selection before the LLM (TASK-032) -------------------------------


def _event(event_id: int, importance: float, status: VerificationStatus = "VERIFIED") -> Event:
    return Event(
        id=event_id,
        verification_status=status,
        confidence_score=5.0,
        importance_score=importance,
        event_type="standard",
        created_at="2026-09-16T10:00:00+02:00",
    )


def test_selection_keeps_the_most_important_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 2)
    events = [_event(1, 3.0), _event(2, 9.0), _event(3, 6.0), _event(4, 1.0)]

    selected = generation_module._select_events(events, {})

    assert [event.id for event in selected] == [2, 3]


def test_selection_prefers_the_better_verified_event_on_equal_importance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 2)
    events = [
        _event(1, 5.0, "UNVERIFIED"),
        _event(2, 5.0, "DEVELOPING"),
        _event(3, 5.0, "VERIFIED"),
        _event(4, 5.0, "PARTIALLY_VERIFIED"),
    ]

    selected = generation_module._select_events(events, {})

    assert [event.id for event in selected] == [3, 4]


def test_selection_does_not_exclude_unverified_events_when_there_is_room() -> None:
    events = [_event(1, 5.0, "UNVERIFIED"), _event(2, 6.0)]

    selected = generation_module._select_events(events, {})

    assert {event.id for event in selected} == {1, 2}


def _dated_article(article_id: int, source_id: int, published_at: str | None) -> Article:
    return Article(
        id=article_id,
        source_id=source_id,
        title=f"Story {article_id}",
        url=f"https://example.com/{article_id}",
        published_at=published_at,
        fetched_at="2026-09-16T09:00:00+00:00",
        raw_excerpt="x",
    )


def test_selection_prefers_more_independent_sources_on_equal_importance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 1)
    events = [_event(1, 5.0), _event(2, 5.0, "PARTIALLY_VERIFIED")]
    articles = {
        1: [_dated_article(1, 10, None), _dated_article(2, 10, None)],  # one source twice
        2: [_dated_article(3, 10, None), _dated_article(4, 11, None)],
    }

    selected = generation_module._select_events(events, articles)

    assert [event.id for event in selected] == [2]


def test_selection_prefers_the_most_recent_article_after_sources_and_verification() -> None:
    events = [_event(1, 5.0), _event(2, 5.0), _event(3, 5.0)]
    articles = {
        1: [_dated_article(1, 10, None)],
        2: [_dated_article(2, 10, "2026-09-15T23:00:00+00:00")],
        3: [_dated_article(3, 10, "2026-09-16T06:00:00+00:00")],
    }

    selected = generation_module._select_events(events, articles)

    # Newest first, ahead of a lower id; undated last: a missing date is never recent.
    assert [event.id for event in selected] == [3, 2, 1]


def test_top_stories_follow_the_selection_order_on_equal_importance(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    openai = _add_source(connection)
    other = _add_source(connection, name="OpenAI mirror", url="https://mirror.test/feed")
    # Clusters are persisted in title order, so the one-source event gets the lower id.
    _add_article(
        connection,
        openai,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-y",
    )
    _add_article(connection, openai)  # "OpenAI ships Model X"
    _add_article(connection, other, url="https://mirror.test/model-x", content_hash="hash-x2")

    _generate(connection, output_dir)

    events = {e.id: e for e in EventRepository(connection).list_by_created_date("2026-09-16")}
    assert len({e.importance_score for e in events.values()}) == 1  # a real tie
    row = connection.execute("SELECT content FROM edition").fetchone()
    edition = Edition.model_validate_json(row[0])
    repository = ArticleRepository(connection)
    by_size = sorted(events, key=lambda event_id: len(repository.list_by_event(event_id or 0)))
    one_source, two_sources = by_size
    assert one_source is not None and two_sources is not None and one_source < two_sources
    # Before TASK-040 the tie went to the lower event id, the one-source event.
    assert [story.event_id for story in edition.top_stories] == [two_sources, one_source]


def test_only_the_selected_events_reach_the_llm(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 1)
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )
    provider = _FakeLLMProvider()

    result = _generate(connection, output_dir, provider=provider)

    assert _count(connection, "event") == 2
    assert result.events_in_edition == 1
    assert _count(connection, "event_content") == 1
    assert len(provider.requests) == 2  # summarize + developer impact, for one event only


# --- events whose articles have no text (TASK-036) ---------------------------


def test_an_event_with_no_article_text_is_excluded_not_failed(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Hugging Face posts a title-only entry",
        url="https://openai.com/news/title-only",
        content_hash="hash-title-only",
        raw_excerpt="",
        normalized_text="",
    )
    provider = _FakeLLMProvider()

    result = _generate(connection, output_dir, provider=provider)

    assert _count(connection, "event") == 2
    assert result.events_in_edition == 1
    assert result.failed_events == []
    assert len(provider.requests) == 2  # one event only: summarize + developer impact


def test_a_text_less_event_does_not_use_up_a_selection_slot(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 1)
    source = _add_source(connection)
    _add_article(connection, source, raw_excerpt="", normalized_text="")
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )

    result = _generate(connection, output_dir)

    assert result.events_in_edition == 1
    assert result.failed_events == []


def test_an_article_without_text_is_left_out_of_a_mixed_event(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    openai = _add_source(connection)
    reuters = _add_source(connection, name="Reuters", url="https://reuters.com/feed", tier=2)
    _add_article(connection, openai, raw_excerpt="", normalized_text="")
    _add_article(
        connection,
        reuters,
        url="https://reuters.com/openai-model-x",
        content_hash="hash-model-x-reuters",
        raw_excerpt="<p>Reuters reports Model X.</p>",
        normalized_text="Reuters reports Model X.",
    )

    result = _generate(connection, output_dir)

    assert _count(connection, "event") == 1
    assert result.events_in_edition == 1
    assert result.failed_events == []
    reader = PdfReader(io.BytesIO(result.pdf_path.read_bytes()))
    pdf_text = "".join(page.extract_text() for page in reader.pages)
    pdf_text = "".join(pdf_text.split())
    assert "https://reuters.com/openai-model-x" in pdf_text
    assert "https://openai.com/news/model-x" not in pdf_text


# --- per-event error handling -------------------------------------------------


def test_an_event_whose_generation_fails_is_skipped_and_reported(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)
    provider = _FakeLLMProvider(summary_response="not a valid response")

    error = _generate_expecting_empty(connection, output_dir, provider=provider)

    assert "all 1 event(s) failed" in str(error)
    assert len(error.failed_events) == 1
    # The event itself is still persisted: only its content generation failed.
    assert _count(connection, "event") == 1
    assert _count(connection, "event_content") == 0
    assert _edition_status(connection) == "failed"


def test_a_failing_event_does_not_prevent_the_others(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )

    class _FailFirstProvider(_FakeLLMProvider):
        def complete(self, request: CompletionRequest) -> CompletionResponse:
            text = "\n".join(message.content for message in request.messages)
            if "Model Y" in text and "HAS_DEVELOPER_IMPACT" not in text:
                raise LLMProviderError("provider is unavailable for this event")
            return super().complete(request)

    result = _generate(connection, output_dir, provider=_FailFirstProvider())

    assert result.events_in_edition == 1
    assert len(result.failed_events) == 1


def test_a_database_failure_is_not_swallowed(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _seed_one_event(connection)
    connection.close()

    with pytest.raises(sqlite3.ProgrammingError):
        _generate(connection, output_dir)


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    return int(row[0])


# --- Post-Implementation Review, Finding 2: per-cluster error isolation ----


def test_a_cluster_whose_event_assignment_fails_is_skipped_not_crashed(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ValueError from ArticleRepository.assign_event() (e.g. a race between
    listing clusterable articles and attaching them) must not crash the run
    with a raw traceback, and the affected cluster must not be counted as
    a successfully created event.
    """
    _seed_one_event(connection)

    def _failing_assign_event(
        self: ArticleRepository, event_id: int, article_ids: list[int]
    ) -> None:
        raise ValueError("simulated race: article no longer pending")

    monkeypatch.setattr(ArticleRepository, "assign_event", _failing_assign_event)

    # Nothing could be created, so there is nothing to publish.
    _generate_expecting_empty(connection, output_dir)

    assert _count(connection, "event") == 1  # the Event row itself was written first
    assert _count(connection, "event_content") == 0


def test_a_failing_cluster_does_not_prevent_other_clusters_from_succeeding(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )

    original_assign_event = ArticleRepository.assign_event
    calls = {"count": 0}

    def _fail_second_call(
        self: ArticleRepository, event_id: int, article_ids: list[int]
    ) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise ValueError("simulated race on the second cluster")
        original_assign_event(self, event_id, article_ids)

    monkeypatch.setattr(ArticleRepository, "assign_event", _fail_second_call)

    result = _generate(connection, output_dir)

    assert result.events_created == 1
    assert calls["count"] == 2


# --- Post-Implementation Review, Finding 3: edition_date consistency -------


class _FrozenDatetime(datetime):
    """A `datetime.now()` that always returns a fixed moment, regardless of tz."""

    _frozen: datetime

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls._frozen if tz is None else cls._frozen.astimezone(tz)


def test_events_created_are_associated_with_the_generation_edition_date(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event analyzed during a generation for a given edition_date must be
    found by that same generation's editorial-composition phase, even when
    the real wall-clock date is a different day (a run straddling
    midnight, or an explicit backfill edition_date).
    """
    _seed_one_event(connection)

    real_now_far_from_edition_date = datetime(
        2026, 9, 25, 10, 0, 0, tzinfo=generation_module.APP_TIMEZONE
    )
    frozen = type("_Frozen", (_FrozenDatetime,), {"_frozen": real_now_far_from_edition_date})
    monkeypatch.setattr(generation_module, "datetime", frozen)

    result = _generate(connection, output_dir)  # edition_date=_EDITION_DATE (2026-09-16)

    assert result.events_created == 1
    assert result.events_in_edition == 1
    assert result.failed_events == []

    events = EventRepository(connection).list_by_created_date(_EDITION_DATE.isoformat())
    assert len(events) == 1
    # created_at carries edition_day's date, not the real "now" date.
    assert events[0].created_at.startswith(_EDITION_DATE.isoformat())


# --- Post-Implementation Review, Finding 4: LLM usage logging --------------


class _UsageReportingProvider(_FakeLLMProvider):
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        text = "\n".join(message.content for message in request.messages)
        if "HAS_DEVELOPER_IMPACT" in text:
            return CompletionResponse(
                text=self.developer_impact_response,
                usage=Usage(input_tokens=120, output_tokens=40),
            )
        return CompletionResponse(
            text=self.summary_response, usage=Usage(input_tokens=200, output_tokens=60)
        )


def test_llm_usage_is_logged_not_silently_discarded(
    connection: sqlite3.Connection, output_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _seed_one_event(connection)

    with caplog.at_level(logging.INFO, logger="app.pipeline.generation"):
        _generate(connection, output_dir, provider=_UsageReportingProvider())

    usage_lines = [record.message for record in caplog.records if "LLM usage" in record.message]
    assert any("stage=summarize" in line and "input_tokens=200" in line for line in usage_lines)
    assert any(
        "stage=developer_impact" in line and "output_tokens=40" in line for line in usage_lines
    )


# --- full article text (TASK-031) -------------------------------------------


def _summary_prompts(provider: _FakeLLMProvider) -> list[str]:
    prompts = [
        "\n".join(message.content for message in request.messages)
        for request in provider.requests
    ]
    return [prompt for prompt in prompts if "HAS_DEVELOPER_IMPACT" not in prompt]


def test_the_fetched_article_text_replaces_the_excerpt_in_the_prompt(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generation_module, "fetch_article_text", lambda url: "FULL TEXT of the article."
    )
    _add_article(connection, _add_source(connection))
    provider = _FakeLLMProvider()

    _generate(connection, output_dir, provider=provider)

    prompt = _summary_prompts(provider)[0]
    assert "FULL TEXT of the article." in prompt
    assert "OpenAI released Model X." not in prompt


def test_an_unfetchable_page_falls_back_to_the_rss_excerpt(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _add_article(connection, _add_source(connection))
    provider = _FakeLLMProvider()

    result = _generate(connection, output_dir, provider=provider)

    assert result.events_in_edition == 1
    assert "OpenAI released Model X." in _summary_prompts(provider)[0]


def test_pages_are_not_downloaded_again_when_the_content_is_already_stored(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched: list[str] = []
    monkeypatch.setattr(
        generation_module, "fetch_article_text", lambda url: fetched.append(url) or None
    )
    _add_article(connection, _add_source(connection))

    _generate(connection, output_dir)
    _generate(connection, output_dir)

    assert fetched == ["https://openai.com/news/model-x"]


def test_pages_of_events_left_out_of_the_selection_are_not_downloaded(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation_module, "MAX_EDITION_EVENTS", 1)
    fetched: list[str] = []
    monkeypatch.setattr(
        generation_module, "fetch_article_text", lambda url: fetched.append(url) or None
    )
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )

    _generate(connection, output_dir)

    assert len(fetched) == 1


def test_only_the_top_stories_get_the_longer_length_target(
    connection: sqlite3.Connection, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation_module, "MAX_TOP_STORIES", 1)
    source = _add_source(connection)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="Anthropic ships Model Y",
        url="https://openai.com/news/model-y",
        content_hash="hash-model-y",
    )
    provider = _FakeLLMProvider()

    _generate(connection, output_dir, provider=provider)

    prompts = _summary_prompts(provider)
    assert sum("Aim for 250 to 350 words" in prompt for prompt in prompts) == 1
    assert sum("Aim for 120 to 180 words" in prompt for prompt in prompts) == 1


# --- cross-source clustering (TASK-038) --------------------------------------


def _add_dots_articles(connection: sqlite3.Connection) -> None:
    source = _add_source(connection)
    other = _add_source(connection, name="Wired", url="https://wired.com/feed", tier=3)
    _add_article(connection, source, title="Introducing dots", content_hash="h1")
    _add_article(
        connection,
        other,
        title="OpenAI's Dots Are Always-On Agents",
        url="https://wired.com/dots",
        content_hash="h2",
    )


class _MergingProvider(_FakeLLMProvider):
    def __init__(self, grouping_answer: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.grouping_answer = grouping_answer

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.grouping_answer is not None and "event grouping stage" in (
            request.messages[0].content
        ):
            self.analysis_requests.append(request)
            return CompletionResponse(text=self.grouping_answer)
        return super().complete(request)


def test_articles_of_different_outlets_about_one_event_become_one_event(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _add_dots_articles(connection)

    _generate(connection, output_dir, provider=_MergingProvider("GROUP: 1, 2"))

    assert _count(connection, "event") == 1


def test_a_failing_merge_call_falls_back_to_the_exact_title_clusters(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _add_dots_articles(connection)

    _generate(connection, output_dir, provider=_MergingProvider("not a grouping"))

    assert _count(connection, "event") == 2



# --- AI relevance filter (TASK-039) ------------------------------------------


class _RelevanceProvider(_FakeLLMProvider):
    """Answers the relevance call by rejecting the items whose title contains `not_ai`."""

    def __init__(
        self,
        not_ai: str | None = None,
        answer: str | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.not_ai = not_ai
        self.answer = answer
        self.error = error

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if "relevance filter stage" not in request.messages[0].content:
            return super().complete(request)
        self.analysis_requests.append(request)
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return CompletionResponse(text=self.answer)
        numbers = [
            line.split(".", 1)[0]
            for line in request.messages[1].content.splitlines()
            if self.not_ai is not None and self.not_ai in line
        ]
        return CompletionResponse(text=f"NOT_AI: {', '.join(numbers)}" if numbers else "NONE")


def _add_ai_and_car_articles(connection: sqlite3.Connection) -> None:
    source = _add_source(connection, name="BBC", url="https://bbc.co.uk/feed", tier=2)
    _add_article(connection, source)
    _add_article(
        connection,
        source,
        title="BMW 3 Series review",
        url="https://bbc.co.uk/bmw",
        content_hash="hash-bmw",
    )


def _article_statuses(connection: sqlite3.Connection) -> dict[str, tuple[str, int | None]]:
    rows = connection.execute("SELECT title, status, event_id FROM article").fetchall()
    return {title: (status, event_id) for title, status, event_id in rows}


def test_clusters_not_about_ai_are_discarded_and_never_become_events(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _add_ai_and_car_articles(connection)

    result = _generate(connection, output_dir, provider=_RelevanceProvider(not_ai="BMW"))

    assert _count(connection, "event") == 1
    assert result.events_in_edition == 1
    statuses = _article_statuses(connection)
    assert statuses["BMW 3 Series review"] == ("discarded", None)
    assert statuses["OpenAI ships Model X"][0] == "processed"


def test_a_discarded_article_is_not_judged_again_by_a_later_run(
    connection: sqlite3.Connection, output_dir: Path
) -> None:
    _add_ai_and_car_articles(connection)
    _generate(connection, output_dir, provider=_RelevanceProvider(not_ai="BMW"))

    provider = _RelevanceProvider(not_ai="Model X")
    _generate(connection, output_dir, provider=provider)

    assert provider.analysis_requests == []
    assert _count(connection, "event") == 1


@pytest.mark.parametrize(
    "provider",
    [
        _RelevanceProvider(answer="not an answer"),
        _RelevanceProvider(error=LLMProviderError("provider is unavailable")),
    ],
    ids=["malformed-answer", "provider-error"],
)
def test_a_failing_relevance_call_keeps_every_cluster(
    connection: sqlite3.Connection, output_dir: Path, provider: _RelevanceProvider
) -> None:
    _add_ai_and_car_articles(connection)

    _generate(connection, output_dir, provider=provider)

    assert _count(connection, "event") == 2
    assert all(status == "processed" for status, _ in _article_statuses(connection).values())
