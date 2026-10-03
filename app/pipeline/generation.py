"""Edition generation: the analysis-to-PDF half of the pipeline (TASK-024).

Wires the stages that TASK-012 to TASK-022 implemented as pure, in-memory
functions into one real, persisted run, closing the MODEL B boundary
described in docs/ARCHITECTURE.md §4.7:

    ANALYSIS (language-neutral, no LLM, runs once per article)
        list_clusterable -> cluster_articles -> verify_cluster
        -> assign_category -> assign_event_type -> build_ranking_input
        -> compute_importance_score -> Event persisted -> Article.event_id

    GENERATION (per language, LLM-backed, reusable across languages)
        list_by_created_date -> summarize_event + analyze_developer_impact
        -> event_content persisted -> assemble_editorial_content
        -> assemble_edition -> render_edition -> PDF file + edition row
        (with the composed edition as JSON, TASK-043)

The two phases are separated exactly where docs/PRD.md §38 requires it:
everything before `event_content` is language-neutral and is never redone
per language, so generating a second language for the same day reuses the
already-persisted `Event` rows and re-runs only the generation phase.

No stage implemented by an earlier task is modified or reimplemented here:
this module only prepares their inputs, persists their outputs and
sequences them.

`list_clusterable` (TASK-028) additionally excludes articles whose
`published_at` is older than `lookback_days` before `edition_day` -- the
FILTER stage's recency requirement (docs/ARCHITECTURE.md §4.15), applied
here as a safety net alongside `app.collectors.rss.RssCollector`'s
ingestion gate.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.ai.developer_impact import (
    DeveloperImpact,
    DeveloperImpactInput,
    DeveloperImpactParseError,
    analyze_developer_impact,
)
from app.ai.event_summarizer import (
    ArticleContext,
    EventSummary,
    EventSummaryInput,
    SummarizationParseError,
    summarize_event,
)
from app.clustering.article_clusterer import ArticleCluster, cluster_articles
from app.clustering.cluster_merger import ClusterMergeParseError, merge_similar_clusters
from app.collectors.article_text import fetch_article_text
from app.config.settings import APP_TIMEZONE
from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.edition import EditionRecord
from app.database.edition_repository import EditionRepository
from app.database.event import Event
from app.database.event_content import EventContent
from app.database.event_content_repository import EventContentRepository
from app.database.event_repository import EventRepository
from app.database.source import Source
from app.database.source_repository import SourceRepository
from app.editorial.edition import EventForEdition, assemble_edition
from app.editorial.event_editorial import assemble_editorial_content
from app.llm.errors import LLMProviderError
from app.llm.provider import LLMProvider, Usage
from app.newspaper.renderer import NewspaperMetadata, render_edition
from app.pipeline.categories import assign_category, assign_event_type
from app.pipeline.ranking_factors import build_ranking_input
from app.ranking.event_ranker import compute_importance_score
from app.verification.event_verifier import VerificationResult, verify_cluster

logger = logging.getLogger(__name__)

# Number of Top Stories on page 1. `assemble_edition` deliberately has no
# default (approved TASK-020 decision D-008: "not to be invented"), so the
# value is fixed here, from the page-1 layout of docs/PRD.md §17, which
# lists three stories.
MAX_TOP_STORIES = 3

# Maximum number of events per edition that reach the LLM stages (TASK-032,
# CLAUDE.md §35: filter and rank locally before spending LLM calls; two calls
# per event). The rest of the day's events stay persisted without content.
MAX_EDITION_EVENTS = 15

# Tie-break between events of equal importance: better-verified first.
_VERIFICATION_ORDER = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 1, "DEVELOPING": 2, "UNVERIFIED": 3}

# Errors that affect one event only. Every one of them is raised by an
# already-implemented stage on a per-event basis, so the run logs it,
# leaves that event out of the edition and continues with the others
# (CLAUDE.md §34: prefer partial success over total failure). Genuine
# infrastructure failures (`sqlite3.Error`, `OSError`) are deliberately
# absent: they are not per-event problems and must reach the caller.
_EVENT_ERRORS = (
    LLMProviderError,
    SummarizationParseError,
    DeveloperImpactParseError,
    ValueError,
)


class EmptyEditionError(Exception):
    """Raised when an edition would contain no event (TASK-034).

    `failed_events` lists the `(event_id, error)` pairs of the events whose
    generation failed; it is empty when there was simply nothing to publish.
    """

    def __init__(self, message: str, failed_events: list[tuple[int, str]]) -> None:
        super().__init__(message)
        self.failed_events = failed_events


@dataclass
class GenerationResult:
    """Outcome of one `generate_edition` call."""

    language: str
    edition_date: date
    edition_number: int
    pdf_path: Path
    pdf_bytes: int
    events_created: int
    events_in_edition: int
    failed_events: list[tuple[int, str]] = field(default_factory=list)


def generate_edition(
    connection: sqlite3.Connection,
    llm_provider: LLMProvider,
    *,
    language: str,
    output_dir: Path,
    lookback_days: int,
    edition_date: date | None = None,
) -> GenerationResult:
    """Run the analysis and generation phases and write one edition's PDF.

    Args:
        connection: an open SQLite connection with migrations already
            applied.
        llm_provider: the provider used by the summarization and Developer
            Impact stages. Injected, following the pattern every AI stage
            already uses: this module never calls `create_llm_provider`.
        language: the edition's language; one invocation produces exactly
            one language (docs/ARCHITECTURE.md §5.1).
        output_dir: directory the PDF is written to; created if missing.
        lookback_days: the freshness safety net's window
            (`Settings.news_lookback_days`, TASK-028) -- see
            `ArticleRepository.list_clusterable`. Required, not defaulted,
            so the caller (the CLI) always supplies the real configured
            value rather than this module inventing its own.
        edition_date: the edition's date. Defaults to today in the
            application timezone (docs/ARCHITECTURE.md §9).

    Returns:
        A `GenerationResult` describing what was created.

    Raises:
        EmptyEditionError: if the edition would contain no event, either
            because there was none or because every one failed. No PDF is
            written and the edition row is marked `failed` (TASK-034).
        sqlite3.Error, OSError: genuine infrastructure failures, which are
            never caught here.
        ValueError: if an already-persisted edition's row is inconsistent
            (missing `id`).

    Per-event failures do not raise: they are logged, listed in
    `GenerationResult.failed_events`, and the remaining events still
    produce an edition.
    """
    edition_day = edition_date or datetime.now(APP_TIMEZONE).date()

    article_repository = ArticleRepository(connection)
    source_repository = SourceRepository(connection)
    event_repository = EventRepository(connection)
    content_repository = EventContentRepository(connection)
    edition_repository = EditionRepository(connection)

    events_created = _analyze_pending_articles(
        llm_provider,
        article_repository,
        source_repository,
        event_repository,
        edition_day,
        lookback_days,
    )

    events_for_edition, failed_events = _compose_editorial_events(
        llm_provider,
        article_repository,
        source_repository,
        event_repository,
        content_repository,
        language=language,
        edition_day=edition_day,
    )

    record = _edition_record(edition_repository, edition_day, language)
    assert record.id is not None  # set by EditionRepository.create/_from_row

    if not events_for_edition:
        # A rerun must not downgrade an edition that was already published.
        if record.status != "published":
            edition_repository.update_status(record.id, "failed")
        raise EmptyEditionError(
            f"all {len(failed_events)} event(s) failed to generate"
            if failed_events
            else "no event available for this edition",
            failed_events,
        )

    edition = assemble_edition(language, events_for_edition, MAX_TOP_STORIES)

    pdf = render_edition(
        edition,
        metadata=NewspaperMetadata(
            edition_number=record.edition_number, edition_date=edition_day
        ),
    )

    pdf_path = output_dir / f"{edition_day.isoformat()}-{language}.pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf)
    edition_repository.publish(record.id, str(pdf_path), edition.model_dump_json())

    logger.info(
        "Edition %d (%s, %s) written to %s: %d event(s), %d created this run, %d failed",
        record.edition_number,
        edition_day.isoformat(),
        language,
        pdf_path,
        len(events_for_edition),
        events_created,
        len(failed_events),
    )

    return GenerationResult(
        language=language,
        edition_date=edition_day,
        edition_number=record.edition_number,
        pdf_path=pdf_path,
        pdf_bytes=len(pdf),
        events_created=events_created,
        events_in_edition=len(events_for_edition),
        failed_events=failed_events,
    )


def _analyze_pending_articles(
    llm_provider: LLMProvider,
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    event_repository: EventRepository,
    edition_day: date,
    lookback_days: int,
) -> int:
    """Cluster, verify, categorize and rank pending articles into `Event` rows.

    Language-neutral: this phase runs once per article, not once per edition
    language (docs/PRD.md §38). Its only LLM call is the single cross-source
    cluster merge (TASK-038). Returns the number of events created.
    """
    clusterable = article_repository.list_clusterable(
        reference_date=edition_day, lookback_days=lookback_days
    )
    if not clusterable:
        logger.info("No clusterable article: no new event created")
        return 0

    clusters = _merge_clusters(llm_provider, cluster_articles(clusterable))
    created = 0
    for index, cluster in enumerate(clusters, start=1):
        try:
            persisted = _persist_event(
                cluster,
                index,
                article_repository,
                source_repository,
                event_repository,
                edition_day,
            )
        except ValueError as exc:
            # The only raise path here is `ArticleRepository.assign_event`
            # rejecting a rowcount mismatch (Post-Implementation Review,
            # Finding 2) -- an already-created `Event` can be left with no
            # articles attached (inert: excluded from the edition by
            # `_prepare_event`'s "no articles" check below), but that state
            # is never counted as a success and never crashes the run.
            # `sqlite3.Error`/`OSError` are not caught here and still reach
            # the CLI's `_CRITICAL_ERRORS` unchanged.
            logger.warning("Cluster %d skipped: %s", index, exc)
            continue
        if persisted:
            created += 1

    logger.info(
        "Analysis complete: %d article(s) clustered into %d event(s)", len(clusterable), created
    )
    return created


def _merge_clusters(
    llm_provider: LLMProvider, clusters: list[ArticleCluster]
) -> list[ArticleCluster]:
    """Merge clusters about the same event across sources (TASK-038).

    The merge is an improvement, not a requirement: if the LLM call or its
    answer fails, the exact-title clusters are kept (CLAUDE.md §34).
    """
    try:
        merged = merge_similar_clusters(llm_provider, clusters)
    except (LLMProviderError, ClusterMergeParseError) as exc:
        logger.warning("Cross-source cluster merge skipped: %s", exc)
        return clusters
    if len(merged) < len(clusters):
        logger.info("Merged %d cluster(s) into %d", len(clusters), len(merged))
    return merged


def _persist_event(
    cluster: ArticleCluster,
    provisional_id: int,
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    event_repository: EventRepository,
    edition_day: date,
) -> bool:
    """Turn one cluster into a persisted `Event` and attach its articles.

    The `Event` row is written first and the articles are attached
    immediately afterwards, in `assign_event`'s own transaction. An
    interrupted run can therefore leave an `Event` with no articles, which
    is inert (it has no content and is skipped by the generation phase),
    but never an article attached to an event that does not exist.
    Wrapping a whole day's events in a single transaction is deliberately
    avoided.
    """
    sources = _sources_for(cluster.articles, source_repository)
    if sources is None:
        return False

    verification = verify_cluster(cluster.articles, sources)
    category = assign_category(sources.values())
    importance_score = compute_importance_score(
        build_ranking_input(
            event_id=provisional_id,
            sources=sources.values(),
            articles=cluster.articles,
            reference_date=edition_day,
        )
    )

    event = event_repository.create(
        Event(
            verification_status=verification.verification_status,
            confidence_score=verification.confidence_score,
            importance_score=importance_score,
            event_type=assign_event_type(category),
            # No deterministic signal identifies an announced future event,
            # and inventing one is explicitly out of scope
            # (docs/ARCHITECTURE.md §4.6, still open): What to Watch
            # therefore stays empty rather than being populated by guesswork.
            future_date=None,
            # Stamped with edition_day's date and the real wall-clock time,
            # not plain `datetime.now()`: `created_at` doubles as this
            # Event's day-identity (`EventRepository.list_by_created_date`,
            # used right below to compose the edition), so it must always
            # fall on `edition_day`, even if the real calendar day differs
            # (Post-Implementation Review, Finding 3) -- e.g. a run
            # straddling local midnight, or an explicit backfill
            # `edition_date`. `Event` has no separate "day" column, and
            # docs/ARCHITECTURE.md §6 already treats this as an internal
            # implementation detail, not a schema-level requirement, so no
            # new column was added.
            created_at=datetime.combine(
                edition_day, datetime.now(APP_TIMEZONE).time(), tzinfo=APP_TIMEZONE
            ).isoformat(),
        )
    )
    assert event.id is not None  # assigned by EventRepository.create

    article_ids = [article.id for article in cluster.articles if article.id is not None]
    article_repository.assign_event(event.id, article_ids)
    return True


def _compose_editorial_events(
    llm_provider: LLMProvider,
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    event_repository: EventRepository,
    content_repository: EventContentRepository,
    *,
    language: str,
    edition_day: date,
) -> tuple[list[EventForEdition], list[tuple[int, str]]]:
    """Build the edition's events, generating or reusing their content."""
    events_for_edition: list[EventForEdition] = []
    failed: list[tuple[int, str]] = []

    todays_events = event_repository.list_by_created_date(edition_day.isoformat())
    articles_by_event = {
        event.id: article_repository.list_by_event(event.id)
        for event in todays_events
        if event.id is not None
    }
    eligible = [
        event
        for event in todays_events
        if any(_has_text(article) for article in articles_by_event.get(event.id or 0, []))
    ]
    if len(eligible) < len(todays_events):
        logger.info(
            "%d event(s) excluded: none of their articles has any text",
            len(todays_events) - len(eligible),
        )

    # `_select_events` returns the events best-first, so the first
    # `MAX_TOP_STORIES` are the edition's Top Stories (they get a longer summary);
    # `rank` is passed on so `assemble_edition` breaks ties the same way (TASK-040).
    for rank, event in enumerate(_select_events(eligible, articles_by_event)):
        assert event.id is not None  # every persisted Event has an id
        try:
            prepared = _prepare_event(
                llm_provider,
                event,
                article_repository,
                source_repository,
                content_repository,
                language=language,
                is_top_story=rank < MAX_TOP_STORIES,
                selection_rank=rank,
            )
        except _EVENT_ERRORS as exc:
            logger.warning("Event %d skipped: %s", event.id, exc)
            failed.append((event.id, str(exc)))
            continue

        if prepared is not None:
            events_for_edition.append(prepared)

    return events_for_edition, failed


def _has_text(article: Article) -> bool:
    """True if the article has a non-blank excerpt to ground a summary on."""
    return bool((article.normalized_text or article.raw_excerpt or "").strip())


def _select_events(
    events: list[Event], articles_by_event: dict[int, list[Article]]
) -> list[Event]:
    """Keep the `MAX_EDITION_EVENTS` best events, best first.

    Importance first; among equal scores (TASK-040): more distinct sources,
    then better verification, then the most recent article, then `id`.
    Deterministic, so a re-run or another language of the same day selects the
    same events and reuses their stored content.

    Events whose articles have no text were already removed by the caller
    (TASK-036): some feeds (e.g. Hugging Face, Google DeepMind) carry only a
    title, and such an event cannot be summarized.
    """

    def sort_key(event: Event) -> tuple[float, int, int, float, int]:
        assert event.id is not None  # every persisted Event has an id
        # Only articles with text: the others are not cited in the edition.
        articles = [a for a in articles_by_event.get(event.id, []) if _has_text(a)]
        return (
            -event.importance_score,
            -len({article.source_id for article in articles}),
            _VERIFICATION_ORDER[event.verification_status],
            -_latest_published_timestamp(articles),
            event.id,
        )

    selected = sorted(events, key=sort_key)[:MAX_EDITION_EVENTS]
    logger.info("Selected %d of %d event(s) for the edition", len(selected), len(events))
    return selected


def _latest_published_timestamp(articles: list[Article]) -> float:
    """POSIX timestamp of the most recent dated article, or 0.0 if none has a usable date.

    A missing or naive date is never treated as recent, as in the novelty factor
    (`app.pipeline.ranking_factors`).
    """
    timestamps = [0.0]
    for article in articles:
        if article.published_at is None:
            continue
        try:
            published = datetime.fromisoformat(article.published_at)
        except ValueError:
            continue
        if published.tzinfo is not None:
            timestamps.append(published.timestamp())
    return max(timestamps)


def _prepare_event(
    llm_provider: LLMProvider,
    event: Event,
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    content_repository: EventContentRepository,
    *,
    language: str,
    is_top_story: bool,
    selection_rank: int,
) -> EventForEdition | None:
    """Assemble one event's `EventForEdition`, or `None` if it has no article with text.

    Articles without text are left out of the LLM context and the citations.
    """
    assert event.id is not None
    articles = [a for a in article_repository.list_by_event(event.id) if _has_text(a)]
    if not articles:
        logger.warning("Event %d has no article with text: excluded from the edition", event.id)
        return None

    sources = _sources_for(articles, source_repository)
    if sources is None:
        return None

    contexts = [_article_context(article, sources[article.source_id]) for article in articles]

    stored = content_repository.get(event.id, language)
    if stored is None:
        summary, developer_impact = _generate_content(
            llm_provider,
            event,
            _with_full_text(contexts),
            language=language,
            is_top_story=is_top_story,
        )
        content_repository.upsert(
            EventContent(
                event_id=event.id,
                language=language,
                title=summary.title,
                summary=summary.summary,
                structured_content=_encode_structured_content(developer_impact),
            )
        )
    else:
        summary = EventSummary(
            event_id=event.id,
            language=language,
            title=stored.title,
            summary=stored.summary,
        )
        developer_impact = _decode_structured_content(stored.structured_content)

    content = assemble_editorial_content(
        event.id,
        language,
        VerificationResult(
            verification_status=event.verification_status,
            confidence_score=event.confidence_score,
            # Marker-based hedging detection is not implemented
            # (docs/ARCHITECTURE.md §4.4, still open); VERIFY itself always
            # returns an empty list, so nothing is invented here either.
            hedging_constraints=[],
        ),
        summary,
        developer_impact,
        # Concept selection and the curated technical definitions the AI
        # Senza Sbatti stage consumes are undecided and unimplemented
        # (docs/ARCHITECTURE.md §6, ambiguities #1 and #6), so no concept
        # explanation is produced rather than a guessed one.
        None,
        contexts,
    )

    return EventForEdition(
        content=content,
        category=assign_category(sources.values()),
        importance_score=event.importance_score,
        selection_rank=selection_rank,
        future_date=event.future_date,
    )


def _generate_content(
    llm_provider: LLMProvider,
    event: Event,
    contexts: list[ArticleContext],
    *,
    language: str,
    is_top_story: bool,
) -> tuple[EventSummary, DeveloperImpact | None]:
    """Run the two LLM stages for one event in one language."""
    assert event.id is not None
    summary = summarize_event(
        llm_provider,
        EventSummaryInput(
            event_id=event.id,
            language=language,
            verification_status=event.verification_status,
            articles=contexts,
            is_top_story=is_top_story,
        ),
    )
    _log_usage("summarize", event.id, language, summary.usage)

    developer_impact = analyze_developer_impact(
        llm_provider,
        DeveloperImpactInput(
            event_id=event.id,
            language=language,
            verification_status=event.verification_status,
            articles=contexts,
        ),
    )
    _log_usage("developer_impact", event.id, language, developer_impact.usage)

    # The absence of developer impact is a normal outcome (docs/PRD.md
    # §43): it is stored as "no structured content" rather than as an
    # assessment saying nothing.
    return summary, developer_impact if developer_impact.has_developer_impact else None


def _log_usage(stage: str, event_id: int, language: str, usage: Usage | None) -> None:
    """Log token usage for one LLM call (CLAUDE.md §35: monitor LLM consumption).

    `Usage` (input/output token counts, `app/llm/provider.py`) is not
    editorial content, so it is logged, not written to `event_content`
    (docs/ARCHITECTURE.md §4.14) -- and not persisted anywhere else either
    (no new table, no new dependency): a structured log line is the
    minimum needed so this data is not silently discarded, without turning
    it into a second persistence concern. `usage` is `None` only when a
    provider does not report it (`app/llm/provider.py`), which is not an
    error.
    """
    if usage is None:
        logger.info(
            "LLM usage: stage=%s event_id=%d language=%s (not reported)", stage, event_id, language
        )
        return
    logger.info(
        "LLM usage: stage=%s event_id=%d language=%s input_tokens=%d output_tokens=%d",
        stage,
        event_id,
        language,
        usage.input_tokens,
        usage.output_tokens,
    )


def _with_full_text(contexts: list[ArticleContext]) -> list[ArticleContext]:
    """Replace each excerpt with the article's full text when it can be fetched (TASK-031).

    Called only for events whose content is about to be generated, so the pages
    of events that are not selected, or whose content is already stored, are
    never downloaded. An article whose page cannot be fetched keeps its RSS
    excerpt.
    """
    enriched = []
    for context in contexts:
        text = fetch_article_text(context.url)
        enriched.append(context.model_copy(update={"excerpt": text}) if text else context)
    return enriched


def _article_context(article: Article, source: Source) -> ArticleContext:
    """Build the grounding context the AI stages consume for one article."""
    excerpt = article.normalized_text or article.raw_excerpt
    return ArticleContext(
        source_name=source.name,
        title=article.title,
        url=article.url,
        published_at=article.published_at,
        excerpt=excerpt,
    )


def _sources_for(
    articles: list[Article], source_repository: SourceRepository
) -> dict[int, Source] | None:
    """Load every `Source` referenced by `articles`, or `None` if one is missing."""
    sources: dict[int, Source] = {}
    for article in articles:
        if article.source_id in sources:
            continue
        source = source_repository.get_by_id(article.source_id)
        if source is None:
            logger.warning(
                "Source %d referenced by article %s no longer exists: event skipped",
                article.source_id,
                article.id,
            )
            return None
        sources[article.source_id] = source
    return sources


def _encode_structured_content(developer_impact: DeveloperImpact | None) -> str | None:
    """Serialize a `DeveloperImpact` for `event_content.structured_content`.

    Shape: `{"developer_impact": {...}}`. `usage` is excluded -- token
    counts are per-call telemetry, not editorial content, and would make
    the stored row differ between an original run and a rerun.
    """
    if developer_impact is None:
        return None
    return json.dumps({"developer_impact": developer_impact.model_dump(exclude={"usage"})})


def _decode_structured_content(structured_content: str | None) -> DeveloperImpact | None:
    """Rebuild the `DeveloperImpact` stored by `_encode_structured_content`."""
    if structured_content is None:
        return None
    payload = json.loads(structured_content)
    return DeveloperImpact.model_validate(payload["developer_impact"])


def _edition_record(
    edition_repository: EditionRepository, edition_day: date, language: str
) -> EditionRecord:
    """Return the edition row for this day and language, creating it if needed.

    Re-running generation for the same day and language reuses the
    existing row, so an edition keeps its original `edition_number`
    instead of consuming a new one on every run.
    """
    existing = edition_repository.get_by_date_and_language(edition_day.isoformat(), language)
    if existing is not None:
        return existing

    return edition_repository.create(
        EditionRecord(
            edition_number=edition_repository.next_edition_number(),
            date=edition_day.isoformat(),
            language=language,
            status="draft",
            created_at=datetime.now(APP_TIMEZONE).isoformat(),
        )
    )
