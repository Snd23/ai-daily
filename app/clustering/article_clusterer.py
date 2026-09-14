"""Article clustering (TASK-012).

Groups `Article` instances that are believed to describe the same
real-world event, based exclusively on an exact match of their
normalized `title`. Distinct from `app.deduplication` (TASK-009), which
groups articles sharing the same `content_hash` -- exact-content
duplicates, typically from the same source/feed. This module instead
groups articles with *different* content (and therefore different
`content_hash`) that plausibly cover the same event, based only on their
title. Two stages, two different notions of "the same" -- this module
never reads `content_hash`/`normalized_text` and never touches
`duplicate_of` (docs/PRD.md §7's DEDUPLICATE vs. CLUSTER EVENTS stages).

Approved TASK-012 scope (Implementation Specification): this module is
**pure and in-memory only**. It never opens a database connection, never
uses `ArticleRepository`/`EventRepository`, never creates or modifies an
`Event`, and never writes `Article.event_id`, `Article.status` or
`Article.duplicate_of`. Per the approved architectural decision (MODEL
B -- "Event created after enrichment"), an `Event` is persisted only once
VERIFY/CLASSIFY/RANK have produced real values for its NOT NULL columns;
`CLUSTER EVENTS` only produces a logical grouping that a later,
not-yet-implemented stage consumes. `article.event_id` stays `NULL`
throughout this module's execution.

The caller is responsible for supplying only the candidate `Article`
instances (survivors of TASK-009's deduplication, i.e. `status ==
'pending'`) -- this module does not filter, re-validate or otherwise
inspect `status`/`duplicate_of`, by design (approved spec: "NON
introdurre nel clusterer una nuova regola strutturale basata su
duplicate_of: il filtraggio degli input è responsabilità del
chiamante").

Matching rule (approved, deterministic, conservative -- see the approved
Implementation Specification for the rationale): two `Article` belong to
the same cluster if and only if `normalize_title` produces the same
non-empty string for both. No fuzzy matching, no semantic/embedding
similarity, no LLM, no source tier/reliability, no time window: none of
`source_id`, `published_at`, `fetched_at` is read by this module.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from app.database.article import Article

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Normalize `title` into the key used to compare articles for clustering.

    Exact steps, in this order (approved TASK-012 spec -- deliberately
    conservative, no step beyond these five):

    1. HTML/entity decoding (`html.unescape`) -- `Article.title` is never
       touched by TASK-008's normalization (which only writes
       `normalized_text`/`content_hash`/`language`), so entities like
       `&amp;` may still be present.
    2. Unicode normalization (`unicodedata.normalize("NFKC", ...)`) --
       canonicalizes equivalent Unicode forms (e.g. full-width/half-width,
       composed/decomposed accents).
    3. Case folding (`str.casefold()`) -- locale-independent
       case-insensitive comparison.
    4. Punctuation handling -- every character whose Unicode category
       starts with `"P"` (`Pc`, `Pd`, `Pe`, `Pf`, `Pi`, `Po`, `Ps`) is
       replaced with a single space, never deleted outright, so that
       e.g. "AI: The Future" normalizes to "ai the future" rather than
       "aithefuture".
    5. Whitespace normalization -- every run of whitespace (including
       the spaces introduced by step 4) is collapsed to a single space,
       then the result is stripped of leading/trailing whitespace.

    Deliberately NOT done, per the approved spec: no stopword removal, no
    stemming/lemmatization, no removal of editorial prefixes (e.g.
    "BREAKING:"), no word reordering, no numeric/date parsing, no
    language-specific processing. Titles that only differ by one of these
    dropped dimensions will NOT be considered equivalent -- a known,
    accepted limitation of this conservative v1 rule, not a defect.
    """
    text = html.unescape(title)
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass
class ArticleCluster:
    """One logical grouping of `Article` believed to describe the same event.

    Purely in-memory: never persisted, has no `id`, no relationship to
    `EventRepository` or the `event` table. `key` is the `normalize_title`
    value shared by every article in `articles` -- except for a
    singleton produced from a title that normalizes to the empty string,
    where `key` is `""` by construction (see `cluster_articles`) and is
    never shared with any other cluster's members.

    `articles` is sorted by `id`.
    """

    key: str
    articles: list[Article]


def _require_id(article: Article) -> int:
    """Return `article.id`, asserting it is set.

    Every `Article` reaching this module is expected to already be
    persisted (the caller supplies TASK-009 survivors read from the
    database), so it always has an `id`. Mirrors
    `app.deduplication.article_deduplicator._require_id`.
    """
    assert article.id is not None
    return article.id


def cluster_articles(articles: list[Article]) -> list[ArticleCluster]:
    """Group `articles` into `ArticleCluster`s by exact normalized-title match.

    Two articles end up in the same cluster if and only if
    `normalize_title(article.title)` produces the same non-empty string
    for both. An article whose title normalizes to the empty string
    (e.g. a title made only of punctuation) is never grouped with any
    other such article -- it always becomes its own singleton cluster
    with `key=""`, even if another input article also normalizes to the
    empty string. This avoids merging otherwise-unrelated articles purely
    because their titles both degenerate to nothing under normalization.

    Every other `Article.title` known to reach this function is
    guaranteed non-blank by `Article`'s own pydantic validation, so a
    blank/`None` title is not a case this function needs to guard
    against.

    Deterministic and independent of the order of `articles`: clusters
    with a non-empty `key` are ordered by `key` (ascending); clusters
    produced from an empty-title singleton are ordered by their sole
    article's `id` and always appear after every non-empty-key cluster.
    Within every cluster, `articles` is sorted by `id`.

    This function is pure: no database access, no repository, no network
    call. It never creates or updates an `Event`, and never writes
    `Article.event_id`, `Article.status` or `Article.duplicate_of` --
    the `Article` instances in the returned clusters are the same
    objects passed in, unmodified.

    Args:
        articles: candidate articles, already filtered by the caller
            (approved TASK-012 scope: this function does not read or
            enforce `status`/`duplicate_of`).

    Returns:
        One `ArticleCluster` per distinct non-empty normalized title,
        plus one additional singleton `ArticleCluster` per article whose
        title normalizes to the empty string.
    """
    groups_by_key: dict[str, list[Article]] = defaultdict(list)
    empty_title_singletons: list[Article] = []

    for article in articles:
        key = normalize_title(article.title)
        if key:
            groups_by_key[key].append(article)
        else:
            empty_title_singletons.append(article)

    clusters = [
        ArticleCluster(key=key, articles=sorted(group, key=_require_id))
        for key, group in sorted(groups_by_key.items())
    ]
    clusters.extend(
        ArticleCluster(key="", articles=[article])
        for article in sorted(empty_title_singletons, key=_require_id)
    )
    return clusters
