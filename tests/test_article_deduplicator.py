"""Tests for `app.deduplication.article_deduplicator` (TASK-009).

Two sections, mirroring the split used by `tests/test_article_normalizer.py`:

- `plan_deduplication` (pure): hand-built `Article` instances, no database.
- `deduplicate_pending_articles` (integration): a real, migrated in-memory
  SQLite database (same fixture pattern as `tests/test_article_repository.py`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from itertools import permutations

import pytest

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository
from app.deduplication.article_deduplicator import (
    deduplicate_pending_articles,
    plan_deduplication,
)
from app.normalization import normalize_article


def _article(
    *, id: int, source_id: int = 1, content_hash: str | None, **overrides: object
) -> Article:
    values: dict[str, object] = {
        "id": id,
        "source_id": source_id,
        "title": "Title",
        "url": f"https://example.com/{id}",
        "published_at": None,
        "fetched_at": "2026-09-01T12:00:00+00:00",
        "raw_excerpt": "excerpt",
        "content_hash": content_hash,
    }
    values.update(overrides)
    return Article(**values)  # type: ignore[arg-type]


# --- plan_deduplication (pure) ----------------------------------------------


def test_plan_deduplication_groups_same_content_hash() -> None:
    a = _article(id=1, content_hash="hash-1")
    b = _article(id=2, content_hash="hash-1")

    groups = plan_deduplication([a, b], source_tiers={1: 1})

    assert len(groups) == 1
    assert groups[0].content_hash == "hash-1"
    assert groups[0].canonical.id == 1
    assert [d.id for d in groups[0].duplicates] == [2]


def test_plan_deduplication_ignores_different_hashes() -> None:
    a = _article(id=1, content_hash="hash-1")
    b = _article(id=2, content_hash="hash-2")

    assert plan_deduplication([a, b], source_tiers={1: 1}) == []


def test_plan_deduplication_groups_three_articles_with_the_same_hash() -> None:
    a = _article(id=1, content_hash="hash-1")
    b = _article(id=2, content_hash="hash-1")
    c = _article(id=3, content_hash="hash-1")

    groups = plan_deduplication([a, b, c], source_tiers={1: 1})

    assert len(groups) == 1
    assert groups[0].canonical.id == 1
    assert [d.id for d in groups[0].duplicates] == [2, 3]


def test_plan_deduplication_handles_multiple_independent_groups() -> None:
    a = _article(id=1, content_hash="hash-1")
    b = _article(id=2, content_hash="hash-1")
    c = _article(id=3, content_hash="hash-2")
    d = _article(id=4, content_hash="hash-2")

    groups = plan_deduplication([a, b, c, d], source_tiers={1: 1})

    assert [group.content_hash for group in groups] == ["hash-1", "hash-2"]
    assert [dup.id for dup in groups[0].duplicates] == [2]
    assert [dup.id for dup in groups[1].duplicates] == [4]


def test_plan_deduplication_ignores_a_hash_with_a_single_article() -> None:
    a = _article(id=1, content_hash="only-one")

    assert plan_deduplication([a], source_tiers={1: 1}) == []


def test_plan_deduplication_canonical_chosen_by_lowest_source_tier() -> None:
    # Tier 3, lower id -- must still lose: tier beats id.
    worse = _article(id=1, source_id=10, content_hash="hash-1")
    # Tier 1, higher id -- must win.
    better = _article(id=2, source_id=20, content_hash="hash-1")

    groups = plan_deduplication([worse, better], source_tiers={10: 3, 20: 1})

    assert groups[0].canonical.id == 2
    assert [dup.id for dup in groups[0].duplicates] == [1]


def test_plan_deduplication_tie_on_tier_is_broken_by_lowest_id() -> None:
    a = _article(id=5, source_id=1, content_hash="hash-1")
    b = _article(id=2, source_id=1, content_hash="hash-1")

    groups = plan_deduplication([a, b], source_tiers={1: 1})

    assert groups[0].canonical.id == 2
    assert [dup.id for dup in groups[0].duplicates] == [5]


def test_plan_deduplication_does_not_use_published_at() -> None:
    # Same tier, same id ordering would already decide this -- the point is
    # that a "more recent"/"older" published_at must not override it.
    older = _article(
        id=2, source_id=1, content_hash="hash-1", published_at="2020-01-01T00:00:00+00:00"
    )
    newer = _article(
        id=1, source_id=1, content_hash="hash-1", published_at="2026-01-01T00:00:00+00:00"
    )

    groups = plan_deduplication([older, newer], source_tiers={1: 1})

    assert groups[0].canonical.id == 1  # lowest id wins, despite being the newer article


def test_plan_deduplication_result_is_independent_of_input_order() -> None:
    a = _article(id=1, source_id=10, content_hash="hash-1")
    b = _article(id=2, source_id=20, content_hash="hash-1")
    c = _article(id=3, source_id=10, content_hash="hash-2")
    articles = [a, b, c]
    source_tiers = {10: 2, 20: 1}

    reference = plan_deduplication(articles, source_tiers)

    for ordering in permutations(articles):
        assert plan_deduplication(list(ordering), source_tiers) == reference


def test_plan_deduplication_raises_keyerror_for_missing_source_tier() -> None:
    a = _article(id=1, source_id=99, content_hash="hash-1")
    b = _article(id=2, source_id=99, content_hash="hash-1")

    with pytest.raises(KeyError):
        plan_deduplication([a, b], source_tiers={})


# --- deduplicate_pending_articles (integration) -----------------------------


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection("sqlite:///:memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def article_repository(connection: sqlite3.Connection) -> ArticleRepository:
    run_migrations(connection)
    return ArticleRepository(connection)


@pytest.fixture
def source_repository(connection: sqlite3.Connection) -> SourceRepository:
    return SourceRepository(connection)


def _make_source(source_repository: SourceRepository, *, tier: int, name: str) -> int:
    created = source_repository.create(
        Source(
            name=name,
            type="rss",
            url=f"https://example.com/{name}/feed",
            tier=tier,
            categories=[],
            reliability_weight=1.0,
            is_active=True,
        )
    )
    assert created.id is not None
    return created.id


def _make_article(article_repository: ArticleRepository, *, source_id: int, url: str) -> Article:
    return article_repository.create(
        Article(
            source_id=source_id,
            title="Title",
            url=url,
            published_at="2026-09-01T10:00:00+00:00",
            fetched_at="2026-09-01T12:00:00+00:00",
            raw_excerpt="excerpt",
        )
    )


def test_deduplicate_pending_articles_marks_exact_duplicates(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=2, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        first.id,  # type: ignore[arg-type]
        normalized_text="Same text",
        content_hash="hash-1",
        language="en",
    )
    article_repository.update_normalization(
        second.id,  # type: ignore[arg-type]
        normalized_text="Same text",
        content_hash="hash-1",
        language="en",
    )

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 1
    assert len(result.succeeded) == 1
    assert result.succeeded[0].canonical.id == first.id  # lower id wins at equal tier

    fetched_first = article_repository.get_by_url(first.url)
    fetched_second = article_repository.get_by_url(second.url)
    assert fetched_first is not None
    assert fetched_first.status == "pending"
    assert fetched_first.duplicate_of is None
    assert fetched_second is not None
    assert fetched_second.status == "discarded"
    assert fetched_second.duplicate_of == first.id


def test_deduplicate_pending_articles_leaves_different_content_untouched(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        first.id, normalized_text="Text A", content_hash="hash-a", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        second.id, normalized_text="Text B", content_hash="hash-b", language="en"  # type: ignore[arg-type]
    )

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 0
    fetched_first = article_repository.get_by_url(first.url)
    fetched_second = article_repository.get_by_url(second.url)
    assert fetched_first is not None
    assert fetched_first.status == "pending"
    assert fetched_second is not None
    assert fetched_second.status == "pending"


def test_deduplicate_pending_articles_treats_equivalent_markup_as_duplicate(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    # Exercises TASK-008's normalizer and TASK-009's deduplicator together:
    # different HTML that normalizes to the same text must produce the same
    # content_hash and therefore be recognised as a duplicate.
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = article_repository.create(
        Article(
            source_id=source_id,
            title="Title A",
            url="https://example.com/a",
            published_at="2026-09-01T10:00:00+00:00",
            fetched_at="2026-09-01T12:00:00+00:00",
            raw_excerpt="<p>Hello</p><p>world</p>",
        )
    )
    second = article_repository.create(
        Article(
            source_id=source_id,
            title="Title B",
            url="https://example.com/b",
            published_at="2026-09-01T10:00:00+00:00",
            fetched_at="2026-09-01T12:00:00+00:00",
            raw_excerpt="<div>Hello</div><div>world</div>",
        )
    )
    normalize_article(article_repository, first)
    normalize_article(article_repository, second)

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 1
    fetched_second = article_repository.get_by_url(second.url)
    assert fetched_second is not None
    assert fetched_second.status == "discarded"
    assert fetched_second.duplicate_of == first.id


def test_deduplicate_pending_articles_ignores_empty_normalized_content(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        first.id, normalized_text="", content_hash="empty-hash", language=None  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        second.id, normalized_text="", content_hash="empty-hash", language=None  # type: ignore[arg-type]
    )

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 0
    fetched_first = article_repository.get_by_url(first.url)
    fetched_second = article_repository.get_by_url(second.url)
    assert fetched_first is not None
    assert fetched_first.status == "pending"
    assert fetched_second is not None
    assert fetched_second.status == "pending"


def test_deduplicate_pending_articles_leaves_unnormalized_articles_untouched(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    # Neither article has been normalized: content_hash is NULL for both.

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 0
    fetched_first = article_repository.get_by_url(first.url)
    fetched_second = article_repository.get_by_url(second.url)
    assert fetched_first is not None
    assert fetched_first.status == "pending"
    assert fetched_second is not None
    assert fetched_second.status == "pending"


def test_deduplicate_pending_articles_is_idempotent(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        first.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        second.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )

    first_run = deduplicate_pending_articles(article_repository, source_repository)
    assert first_run.duplicates_marked == 1

    second_run = deduplicate_pending_articles(article_repository, source_repository)

    assert second_run.duplicates_marked == 0
    assert second_run.succeeded == []
    assert second_run.failed == []
    assert second_run.reattached == []
    assert second_run.failed_reattachments == []


def test_deduplicate_pending_articles_does_not_change_columns_outside_scope(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = article_repository.create(
        Article(
            source_id=source_id,
            title="Duplicate Title",
            url="https://example.com/b",
            published_at="2026-09-01T10:00:00+00:00",
            fetched_at="2026-09-01T12:00:00+00:00",
            raw_excerpt="Duplicate raw excerpt",
        )
    )
    article_repository.update_normalization(
        first.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        second.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    before = article_repository.get_by_url(second.url)
    assert before is not None

    deduplicate_pending_articles(article_repository, source_repository)

    after = article_repository.get_by_url(second.url)
    assert after is not None
    assert after.title == before.title
    assert after.url == before.url
    assert after.raw_excerpt == before.raw_excerpt
    assert after.published_at == before.published_at
    assert after.fetched_at == before.fetched_at
    assert after.source_id == before.source_id
    assert after.event_id == before.event_id
    assert after.normalized_text == before.normalized_text
    assert after.content_hash == before.content_hash
    assert after.language == before.language


def test_deduplicate_pending_articles_keeps_the_primary_source_reachable(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    # The tier-1 (primary source) article must be chosen as canonical and
    # remain reachable by its own URL even though it has a higher id
    # (TASK-009 spec §5: the link to the primary source is never lost).
    low_tier = _make_source(source_repository, tier=3, name="Blog")
    high_tier = _make_source(source_repository, tier=1, name="Official")
    early_low_tier = _make_article(
        article_repository, source_id=low_tier, url="https://blog.example/a"
    )
    later_primary = _make_article(
        article_repository, source_id=high_tier, url="https://official.example/a"
    )
    article_repository.update_normalization(
        early_low_tier.id,  # type: ignore[arg-type]
        normalized_text="Announcement text",
        content_hash="hash-1",
        language="en",
    )
    article_repository.update_normalization(
        later_primary.id,  # type: ignore[arg-type]
        normalized_text="Announcement text",
        content_hash="hash-1",
        language="en",
    )

    deduplicate_pending_articles(article_repository, source_repository)

    fetched_primary = article_repository.get_by_url(later_primary.url)
    fetched_blog = article_repository.get_by_url(early_low_tier.url)
    assert fetched_primary is not None
    assert fetched_primary.status == "pending"
    assert fetched_primary.url == "https://official.example/a"
    assert fetched_blog is not None
    assert fetched_blog.status == "discarded"
    assert fetched_blog.duplicate_of == later_primary.id


def test_deduplicate_pending_articles_does_not_reelect_canonical_on_a_later_run(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    # TASK-009 spec, approved A8 (worked example): once A is canonical and B
    # is duplicate_of A, a later-arriving, better-tier C must attach to A --
    # it must never dethrone A, and B must never be repointed to C.
    low_tier = _make_source(source_repository, tier=3, name="Blog")
    a = _make_article(article_repository, source_id=low_tier, url="https://example.com/a")
    b = _make_article(article_repository, source_id=low_tier, url="https://example.com/b")
    article_repository.update_normalization(
        a.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        b.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)

    high_tier = _make_source(source_repository, tier=1, name="Official")
    c = _make_article(article_repository, source_id=high_tier, url="https://example.com/c")
    article_repository.update_normalization(
        c.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )

    deduplicate_pending_articles(article_repository, source_repository)

    fetched_a = article_repository.get_by_url(a.url)
    fetched_b = article_repository.get_by_url(b.url)
    fetched_c = article_repository.get_by_url(c.url)
    assert fetched_a is not None
    assert fetched_a.status == "pending"  # A keeps its canonical role
    assert fetched_a.duplicate_of is None
    assert fetched_b is not None
    assert fetched_b.duplicate_of == a.id  # unchanged, not repointed to C
    assert fetched_c is not None
    assert fetched_c.status == "discarded"
    assert fetched_c.duplicate_of == a.id  # C attaches to the existing canonical


def test_deduplicate_pending_articles_attaches_multiple_new_pending_to_the_same_canonical(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    a = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    b = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        a.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        b.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)  # a canonical, b -> a

    c = _make_article(article_repository, source_id=source_id, url="https://example.com/c")
    d = _make_article(article_repository, source_id=source_id, url="https://example.com/d")
    article_repository.update_normalization(
        c.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        d.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )

    result = deduplicate_pending_articles(article_repository, source_repository)

    # Both new pending articles attach to `a` in a single, atomic call.
    assert result.reattached == [(a.id, [c.id, d.id])]
    fetched_c = article_repository.get_by_url(c.url)
    fetched_d = article_repository.get_by_url(d.url)
    assert fetched_c is not None
    assert fetched_c.status == "discarded"
    assert fetched_c.duplicate_of == a.id
    assert fetched_d is not None
    assert fetched_d.status == "discarded"
    assert fetched_d.duplicate_of == a.id


def test_deduplicate_pending_articles_never_creates_a_duplicate_of_chain(
    article_repository: ArticleRepository, source_repository: SourceRepository
) -> None:
    # Three separate runs, each adding one more article sharing the hash.
    # Every follower must point directly at the original root canonical,
    # never at an intermediate duplicate (TASK-009 spec, A8 revision).
    source_id = _make_source(source_repository, tier=1, name="Source")
    a = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    b = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        a.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        b.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)

    c = _make_article(article_repository, source_id=source_id, url="https://example.com/c")
    article_repository.update_normalization(
        c.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)

    d = _make_article(article_repository, source_id=source_id, url="https://example.com/d")
    article_repository.update_normalization(
        d.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)

    fetched_a = article_repository.get_by_url(a.url)
    fetched_b = article_repository.get_by_url(b.url)
    fetched_c = article_repository.get_by_url(c.url)
    fetched_d = article_repository.get_by_url(d.url)
    assert fetched_a is not None
    assert fetched_a.duplicate_of is None
    assert fetched_b is not None
    assert fetched_b.duplicate_of == a.id
    assert fetched_c is not None
    assert fetched_c.duplicate_of == a.id  # not b.id -- no chain through an intermediate duplicate
    assert fetched_d is not None
    assert fetched_d.duplicate_of == a.id  # not b.id or c.id


def test_deduplicate_pending_articles_continues_after_a_reattachment_fails(
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    a = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    b = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        a.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        b.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    deduplicate_pending_articles(article_repository, source_repository)  # a canonical, b -> a

    c = _make_article(article_repository, source_id=source_id, url="https://example.com/c")
    article_repository.update_normalization(
        c.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    # An unrelated, brand-new group that Phase 2 must still process even if
    # Phase 1's reattachment fails.
    fresh_1 = _make_article(article_repository, source_id=source_id, url="https://example.com/e")
    fresh_2 = _make_article(article_repository, source_id=source_id, url="https://example.com/f")
    article_repository.update_normalization(
        fresh_1.id, normalized_text="Other text", content_hash="hash-2", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        fresh_2.id, normalized_text="Other text", content_hash="hash-2", language="en"  # type: ignore[arg-type]
    )

    real_mark_duplicates = article_repository.mark_duplicates

    def failing_mark_duplicates(canonical_id: int, duplicate_ids: object) -> None:
        if canonical_id == a.id:
            raise ValueError("simulated reattachment failure")
        real_mark_duplicates(canonical_id, duplicate_ids)  # type: ignore[arg-type]

    monkeypatch.setattr(article_repository, "mark_duplicates", failing_mark_duplicates)

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.reattached == []
    assert result.failed_reattachments == [(a.id, [c.id], "simulated reattachment failure")]
    assert len(result.succeeded) == 1  # the unrelated fresh group is still processed

    fetched_c = article_repository.get_by_url(c.url)
    assert fetched_c is not None
    assert fetched_c.status == "pending"  # untouched: its reattachment failed

    fetched_fresh_2 = article_repository.get_by_url(fresh_2.url)
    assert fetched_fresh_2 is not None
    assert fetched_fresh_2.status == "discarded"  # phase 2 still ran despite phase 1's failure


def test_deduplicate_pending_articles_continues_after_one_group_fails(
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    good_a = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    good_b = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    bad_a = _make_article(article_repository, source_id=source_id, url="https://example.com/c")
    bad_b = _make_article(article_repository, source_id=source_id, url="https://example.com/d")
    for article, content_hash in (
        (good_a, "good-hash"),
        (good_b, "good-hash"),
        (bad_a, "bad-hash"),
        (bad_b, "bad-hash"),
    ):
        article_repository.update_normalization(
            article.id,  # type: ignore[arg-type]
            normalized_text=content_hash,
            content_hash=content_hash,
            language="en",
        )

    real_mark_duplicates = article_repository.mark_duplicates

    def failing_mark_duplicates(canonical_id: int, duplicate_ids: object) -> None:
        if canonical_id == bad_a.id:
            raise ValueError("simulated failure")
        real_mark_duplicates(canonical_id, duplicate_ids)  # type: ignore[arg-type]

    monkeypatch.setattr(article_repository, "mark_duplicates", failing_mark_duplicates)

    result = deduplicate_pending_articles(article_repository, source_repository)

    assert result.duplicates_marked == 1
    assert [g.canonical.id for g in result.succeeded] == [good_a.id]
    assert len(result.failed) == 1
    assert result.failed[0][0].canonical.id == bad_a.id
    assert "simulated failure" in result.failed[0][1]

    fetched_good_b = article_repository.get_by_url(good_b.url)
    fetched_bad_b = article_repository.get_by_url(bad_b.url)
    assert fetched_good_b is not None
    assert fetched_good_b.status == "discarded"
    assert fetched_bad_b is not None
    assert fetched_bad_b.status == "pending"  # untouched: its group's write failed


def test_deduplicate_pending_articles_propagates_sqlite_errors(
    article_repository: ArticleRepository,
    source_repository: SourceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _make_source(source_repository, tier=1, name="Source")
    first = _make_article(article_repository, source_id=source_id, url="https://example.com/a")
    second = _make_article(article_repository, source_id=source_id, url="https://example.com/b")
    article_repository.update_normalization(
        first.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )
    article_repository.update_normalization(
        second.id, normalized_text="Same text", content_hash="hash-1", language="en"  # type: ignore[arg-type]
    )

    def raise_operational_error(canonical_id: int, duplicate_ids: object) -> None:
        raise sqlite3.OperationalError("simulated database failure")

    monkeypatch.setattr(article_repository, "mark_duplicates", raise_operational_error)

    with pytest.raises(sqlite3.OperationalError):
        deduplicate_pending_articles(article_repository, source_repository)
