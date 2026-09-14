"""Article deduplication (TASK-009).

Groups `pending` articles that share the same `content_hash` (computed by
`app.normalization` from `normalized_text`, TASK-008) and marks every
article in a group except one -- the canonical -- as a duplicate.

Distinct from clustering articles from different sources about the same
real-world event (docs/ARCHITECTURE.md §2's DEDUPLICATE vs. CLUSTER EVENTS
stages, docs/PRD.md §7): this module never creates an `Event`, never
assigns `Article.event_id`, and never uses title/semantic similarity, an
LLM or embeddings. Two articles are duplicates if and only if they share a
`content_hash` -- nothing else.

Two layers, kept deliberately separate, following the same split as
`app.normalization.article_normalizer`:

- `plan_deduplication` is pure: no `sqlite3`, no `ArticleRepository`. It
  only groups `Article` instances already in memory and decides,
  deterministically, which one in each group is canonical. It knows
  nothing about any previous deduplication run -- that is `deduplicate_
  pending_articles`'s job (see "no canonical re-election" below).
- `deduplicate_pending_articles` is the orchestration: reads candidates and
  source tiers through the repositories, calls `plan_deduplication`, and
  persists each decision through `ArticleRepository.mark_duplicates`.
  Contains no SQL itself.

`raw_excerpt`/`normalized_text` content is never read or interpreted here
(CLAUDE.md §10-11): only the already-computed `content_hash` is compared.

No canonical re-election (TASK-009 spec, approved A8): once an article has
been chosen as canonical for a `content_hash`, it keeps that role forever,
even if a better-tier article for the same content arrives in a later run.
This is achieved by running two phases every time `deduplicate_pending_
articles` is called:

  Phase 1 -- reattachment: any `pending` article that shares its
  `content_hash` with an already-`'discarded'` article's `duplicate_of`
  target is attached directly to that existing canonical
  (`ArticleRepository.list_pending_matches_for_established_canonicals` +
  `mark_duplicates`). No `(tier, id)` comparison happens here -- the
  canonical was already decided, so there is nothing left to decide.

  Phase 2 -- fresh grouping: `list_deduplication_candidates` +
  `plan_deduplication` + `mark_duplicates`, exactly as if `content_hash`
  had never been seen before. Phase 1 already ran (and committed) first,
  so any article it reattached is now `'discarded'` and no longer appears
  among `pending` candidates -- Phase 2 therefore never sees, and never
  re-decides, a `content_hash` Phase 1 already handled.

`plan_deduplication` itself carries no notion of "already established": it
only ever runs on brand-new groups, which is exactly what TASK-009 spec's
Domain API describes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.source_repository import SourceRepository

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """One set of articles sharing a `content_hash`, with a canonical choice.

    `canonical` is the `Article` kept as-is (it stays `status = 'pending'`
    after deduplication -- TASK-009 spec, approved A12). `duplicates` holds
    every other `Article` in the group, sorted by `id` -- these are the
    ones that get marked `'discarded'`.
    """

    content_hash: str
    canonical: Article
    duplicates: list[Article]


def _require_id(article: Article) -> int:
    """Return `article.id`, asserting it is set.

    Every `Article` reaching this module comes from `ArticleRepository.
    list_deduplication_candidates` (or a test double built the same way),
    so it is always persisted and always has an `id`.
    """
    assert article.id is not None
    return article.id


def plan_deduplication(
    candidates: list[Article], source_tiers: Mapping[int, int]
) -> list[DuplicateGroup]:
    """Group `candidates` by `content_hash` and choose a canonical per group.

    Every `Article` in `candidates` must have a non-`None` `content_hash`
    -- `ArticleRepository.list_deduplication_candidates` guarantees this by
    construction; passing an article with no hash is a programming error,
    not a data condition this function handles gracefully.

    A group with a single member is dropped: there is nothing to
    deduplicate it against (TASK-009 spec §4/§7). The canonical of each
    remaining group is the `Article` with the lowest
    `(source.tier, article.id)` -- source tier first (a lower tier number
    is a more authoritative source, docs/ARCHITECTURE.md §13), `id`
    breaking every tie. `published_at` plays no part in this choice
    (TASK-009 spec, approved A6). Every `Article.source_id` must be a key
    of `source_tiers`; a missing key is a foreign-key integrity violation
    and raises `KeyError` rather than being silently worked around.

    This function has no notion of a previously-established canonical: it
    always decides a group from scratch by `(tier, id)` alone. Keeping an
    article that already won a previous run from being outranked here is
    `deduplicate_pending_articles`'s responsibility (TASK-009 spec,
    approved A8 revision) -- by the time this function ever sees a group,
    Phase 1 has already removed from contention every article that
    shouldn't compete.

    Deterministic and independent of the order of `candidates`: grouping
    only depends on `content_hash` equality, and `min` over a total order
    `(tier, id)` always picks the same element regardless of input order.

    Returns:
        One `DuplicateGroup` per `content_hash` shared by 2+ candidates,
        ordered by `content_hash`. `duplicates` within each group is
        sorted by `id`.
    """
    groups_by_hash: dict[str, list[Article]] = defaultdict(list)
    for article in candidates:
        assert article.content_hash is not None  # caller-guaranteed precondition
        groups_by_hash[article.content_hash].append(article)

    result: list[DuplicateGroup] = []
    for content_hash in sorted(groups_by_hash):
        members = groups_by_hash[content_hash]
        if len(members) < 2:
            continue

        canonical = min(members, key=lambda a: (source_tiers[a.source_id], _require_id(a)))
        duplicates = sorted(
            (article for article in members if article.id != canonical.id),
            key=_require_id,
        )
        result.append(
            DuplicateGroup(content_hash=content_hash, canonical=canonical, duplicates=duplicates)
        )

    return result


@dataclass
class DeduplicationBatchResult:
    """Outcome of one `deduplicate_pending_articles` call.

    `succeeded`/`failed` cover Phase 2 (fresh groups): `succeeded` holds
    each `DuplicateGroup` whose duplicates were marked successfully, in
    processing order; `failed` holds `(DuplicateGroup, error message)`
    pairs for groups rejected by `ArticleRepository.mark_duplicates`.

    `reattached`/`failed_reattachments` cover Phase 1 (attachment to an
    already-established canonical): `reattached` holds each successful
    `(canonical_id, duplicate_ids)` pair; `failed_reattachments` holds
    `(canonical_id, duplicate_ids, error message)` triples for pairs
    rejected by `mark_duplicates`.

    In both phases, a rejection is logged and skipped -- never aborting
    the batch (TASK-009 spec §9/§11).
    """

    succeeded: list[DuplicateGroup] = field(default_factory=list)
    failed: list[tuple[DuplicateGroup, str]] = field(default_factory=list)
    reattached: list[tuple[int, list[int]]] = field(default_factory=list)
    failed_reattachments: list[tuple[int, list[int], str]] = field(default_factory=list)

    @property
    def duplicates_marked(self) -> int:
        """Total number of articles marked as duplicates, across both phases."""
        from_new_groups = sum(len(group.duplicates) for group in self.succeeded)
        from_reattachments = sum(len(duplicate_ids) for _, duplicate_ids in self.reattached)
        return from_new_groups + from_reattachments


def deduplicate_pending_articles(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> DeduplicationBatchResult:
    """Deduplicate every eligible pending `Article`, in two phases.

    Phase 1 attaches any `pending` article that shares its `content_hash`
    with an already-established canonical (found via `ArticleRepository.
    list_pending_matches_for_established_canonicals`) directly to that
    canonical, through `mark_duplicates` -- no `(tier, id)` comparison, no
    re-election (TASK-009 spec, approved A8).

    Phase 2 then reads the remaining candidates via `ArticleRepository.
    list_deduplication_candidates` (already restricted to `status =
    'pending'` with a non-empty `normalized_text`/`content_hash`, TASK-009
    spec §4) and every source's tier via `SourceRepository.list_all`, calls
    `plan_deduplication` to decide a canonical for every brand-new group,
    and persists each decision through `mark_duplicates`. Articles
    reattached in Phase 1 are already `'discarded'` by the time this query
    runs, so they never appear here and are never reconsidered.

    A rejection by `mark_duplicates` (`ValueError` -- a benign race, e.g. a
    row no longer `'pending'`) is logged and skipped in either phase; the
    rest of the batch still runs, mirroring the resilience already
    established by `RssCollector.collect_all` (TASK-007) and `normalize_
    pending_articles` (TASK-008).

    Any other exception (in particular a genuine `sqlite3` infrastructure
    failure) is treated as critical and propagates, aborting the batch.
    """
    result = DeduplicationBatchResult()

    # Phase 1: reattach new pending articles to an already-established
    # canonical. Purely mechanical -- the canonical was already decided by
    # a previous run, so there is no comparison to make here.
    matches = article_repository.list_pending_matches_for_established_canonicals()
    for canonical_id, duplicate_ids in matches.items():
        try:
            article_repository.mark_duplicates(canonical_id, duplicate_ids)
        except ValueError as exc:
            logger.warning(
                "Skipping reattachment to established canonical id=%s: %s", canonical_id, exc
            )
            result.failed_reattachments.append((canonical_id, duplicate_ids, str(exc)))
        else:
            logger.info(
                "Reattached %d pending article(s) to established canonical id=%s",
                len(duplicate_ids),
                canonical_id,
            )
            result.reattached.append((canonical_id, duplicate_ids))

    # Phase 2: decide a canonical for every group Phase 1 did not already
    # resolve. Articles reattached above are now 'discarded' and therefore
    # excluded from list_deduplication_candidates() by construction.
    candidates = article_repository.list_deduplication_candidates()

    source_tiers: dict[int, int] = {}
    for source in source_repository.list_all():
        assert source.id is not None  # persisted sources always have an id
        source_tiers[source.id] = source.tier

    for group in plan_deduplication(candidates, source_tiers):
        canonical_id = _require_id(group.canonical)
        duplicate_ids = [_require_id(article) for article in group.duplicates]
        try:
            article_repository.mark_duplicates(canonical_id, duplicate_ids)
        except ValueError as exc:
            logger.warning(
                "Skipping duplicate group (content_hash=%s, canonical id=%s): %s",
                group.content_hash,
                canonical_id,
                exc,
            )
            result.failed.append((group, str(exc)))
        else:
            logger.info(
                "Marked %d duplicate(s) of article id=%s (content_hash=%s)",
                len(group.duplicates),
                canonical_id,
                group.content_hash,
            )
            result.succeeded.append(group)

    logger.info(
        "Deduplication complete: %d duplicate(s) marked (%d new group(s), %d reattachment(s))",
        result.duplicates_marked,
        len(result.succeeded),
        len(result.reattached),
    )
    return result
