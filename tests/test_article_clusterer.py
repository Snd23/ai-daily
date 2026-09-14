"""Tests for `app.clustering.article_clusterer` (TASK-012).

Pure/in-memory only, mirroring the style of `tests/test_article_deduplicator.py`'s
`plan_deduplication` section: hand-built `Article` instances, no database, no
`conftest.py` (none exists in this repository and none is needed here).
"""

from __future__ import annotations

from itertools import permutations

from app.clustering.article_clusterer import ArticleCluster, cluster_articles, normalize_title
from app.database.article import Article


def _article(*, id: int, title: str, source_id: int = 1, **overrides: object) -> Article:
    values: dict[str, object] = {
        "id": id,
        "source_id": source_id,
        "title": title,
        "url": f"https://example.com/{id}",
        "published_at": None,
        "fetched_at": "2026-09-01T12:00:00+00:00",
        "raw_excerpt": "excerpt",
    }
    values.update(overrides)
    return Article(**values)  # type: ignore[arg-type]


# --- normalize_title ----------------------------------------------------


def test_normalize_title_decodes_html_entities() -> None:
    assert normalize_title("Tom &amp; Jerry") == normalize_title("Tom & Jerry")


def test_normalize_title_applies_unicode_nfkc() -> None:
    # "Ａ" is the full-width Latin "A"; NFKC folds it to ASCII "A".
    assert normalize_title("ＡI model") == normalize_title("AI model")


def test_normalize_title_casefolds() -> None:
    assert normalize_title("OpenAI Launches GPT") == normalize_title("openai launches gpt")


def test_normalize_title_replaces_punctuation_with_space_not_deletion() -> None:
    # If punctuation were deleted instead of space-substituted, "AI: News"
    # would collapse into "ainews" and wrongly match "A Inews".
    assert normalize_title("AI: News") == "ai news"
    assert normalize_title("AI: News") != normalize_title("A Inews")


def test_normalize_title_collapses_whitespace_runs() -> None:
    assert normalize_title("AI   News\t\nToday") == normalize_title("AI News Today")


def test_normalize_title_strips_leading_and_trailing_whitespace() -> None:
    assert normalize_title("  AI News  ") == "ai news"


# --- basic clustering -----------------------------------------------------


def test_single_article_produces_a_singleton_cluster() -> None:
    article = _article(id=1, title="OpenAI launches GPT-5")

    clusters = cluster_articles([article])

    assert clusters == [ArticleCluster(key="openai launches gpt 5", articles=[article])]


def test_two_articles_with_equivalent_titles_cluster_together() -> None:
    a = _article(id=1, title="OpenAI Launches GPT-5")
    b = _article(id=2, title="openai launches gpt-5")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b]


def test_two_articles_with_different_titles_produce_separate_clusters() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5")
    b = _article(id=2, title="Anthropic releases Claude")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 2
    assert {cluster.key for cluster in clusters} == {
        "openai launches gpt 5",
        "anthropic releases claude",
    }


def test_multiple_groups_have_correct_cardinality() -> None:
    a1 = _article(id=1, title="OpenAI launches GPT-5")
    a2 = _article(id=2, title="OpenAI launches GPT-5")
    a3 = _article(id=3, title="OpenAI launches GPT-5")
    b1 = _article(id=4, title="Anthropic releases Claude")
    b2 = _article(id=5, title="Anthropic releases Claude")
    c1 = _article(id=6, title="Meta unveils Llama")

    clusters = cluster_articles([a1, a2, a3, b1, b2, c1])

    sizes = sorted(len(cluster.articles) for cluster in clusters)
    assert sizes == [1, 2, 3]


# --- title normalizing to empty string -------------------------------------


def test_title_normalizing_to_empty_string_is_a_singleton() -> None:
    article = _article(id=1, title="---")

    clusters = cluster_articles([article])

    assert clusters == [ArticleCluster(key="", articles=[article])]


def test_two_articles_with_empty_normalized_titles_do_not_merge() -> None:
    a = _article(id=1, title="---")
    b = _article(id=2, title="***")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 2
    assert all(cluster.key == "" for cluster in clusters)
    assert all(len(cluster.articles) == 1 for cluster in clusters)
    assert {cluster.articles[0].id for cluster in clusters} == {1, 2}


# --- normalization is conservative (things NOT done) ------------------------


def test_stopword_is_not_removed() -> None:
    a = _article(id=1, title="The rise of the machines")
    b = _article(id=2, title="rise of machines")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 2


def test_editorial_prefix_is_not_removed() -> None:
    a = _article(id=1, title="BREAKING: OpenAI launches GPT-5")
    b = _article(id=2, title="OpenAI launches GPT-5")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 2


# --- cross-source behavior --------------------------------------------------


def test_same_event_different_sources_cluster_together() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5", source_id=1)
    b = _article(id=2, title="OpenAI launches GPT-5", source_id=2)
    c = _article(id=3, title="OpenAI launches GPT-5", source_id=3)

    clusters = cluster_articles([a, b, c])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b, c]


def test_same_event_same_source_cluster_together() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5", source_id=1)
    b = _article(id=2, title="OpenAI launches GPT-5", source_id=1)

    clusters = cluster_articles([a, b])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b]


def test_clustering_is_unaffected_by_source_tier() -> None:
    # `Article` carries no `tier` field (it lives on `Source`), and
    # `cluster_articles` receives only `Article` instances -- never a
    # `Source`. `source_id` is the only source-related signal `Article`
    # exposes, so varying it (a stand-in for "different tier") must have
    # no effect on the clustering outcome either way.
    same_title = [
        _article(id=1, title="OpenAI launches GPT-5", source_id=10),
        _article(id=2, title="OpenAI launches GPT-5", source_id=20),
    ]
    assert len(cluster_articles(same_title)) == 1

    same_source_different_title = [
        _article(id=3, title="OpenAI launches GPT-5", source_id=10),
        _article(id=4, title="Anthropic releases Claude", source_id=10),
    ]
    assert len(cluster_articles(same_source_different_title)) == 2


def test_clustering_is_unaffected_by_reliability_weight() -> None:
    # `reliability_weight` lives on `Source` (TASK-010), never on
    # `Article`, and `cluster_articles` never receives a `Source`. The
    # only proxy available on `Article` is `source_id`; varying it (as
    # for the tier case above) has no effect on the outcome.
    same_title = [
        _article(id=1, title="OpenAI launches GPT-5", source_id=10),
        _article(id=2, title="OpenAI launches GPT-5", source_id=20),
    ]
    assert len(cluster_articles(same_title)) == 1


# --- temporal behavior -------------------------------------------------------


def test_published_at_does_not_affect_clustering() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5", published_at="2026-01-01T00:00:00+00:00")
    b = _article(id=2, title="OpenAI launches GPT-5", published_at=None)

    clusters = cluster_articles([a, b])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b]


def test_articles_published_days_apart_still_cluster_by_title() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5", published_at="2026-01-01T00:00:00+00:00")
    b = _article(id=2, title="OpenAI launches GPT-5", published_at="2026-01-15T00:00:00+00:00")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b]


# --- dedup boundary (TASK-009) ----------------------------------------------


def test_duplicate_of_is_not_read_or_used_to_filter() -> None:
    # The caller is responsible for excluding discarded duplicates before
    # calling cluster_articles (approved spec); this module does not
    # inspect duplicate_of at all, so an article carrying one is still
    # clustered normally rather than being specially excluded here.
    a = _article(id=1, title="OpenAI launches GPT-5", duplicate_of=99)
    b = _article(id=2, title="OpenAI launches GPT-5")

    clusters = cluster_articles([a, b])

    assert len(clusters) == 1
    assert clusters[0].articles == [a, b]


def test_canonical_pending_article_clusters_normally() -> None:
    article = _article(id=1, title="OpenAI launches GPT-5", status="pending", duplicate_of=None)

    clusters = cluster_articles([article])

    assert clusters == [ArticleCluster(key="openai launches gpt 5", articles=[article])]


# --- invariants: no mutation ------------------------------------------------


def test_event_id_is_unchanged_after_clustering() -> None:
    article = _article(id=1, title="OpenAI launches GPT-5", event_id=None)

    clusters = cluster_articles([article])

    assert clusters[0].articles[0].event_id is None


def test_status_is_unchanged_after_clustering() -> None:
    article = _article(id=1, title="OpenAI launches GPT-5", status="pending")

    clusters = cluster_articles([article])

    assert clusters[0].articles[0].status == "pending"


def test_duplicate_of_is_unchanged_after_clustering() -> None:
    article = _article(id=1, title="OpenAI launches GPT-5", duplicate_of=None)

    clusters = cluster_articles([article])

    assert clusters[0].articles[0].duplicate_of is None


# --- determinism -------------------------------------------------------------


def test_repeated_call_with_same_input_produces_the_same_result() -> None:
    articles = [
        _article(id=1, title="OpenAI launches GPT-5"),
        _article(id=2, title="OpenAI launches GPT-5"),
        _article(id=3, title="Anthropic releases Claude"),
    ]

    first = cluster_articles(articles)
    second = cluster_articles(articles)

    assert first == second


def test_result_is_independent_of_input_order() -> None:
    a = _article(id=1, title="OpenAI launches GPT-5")
    b = _article(id=2, title="OpenAI launches GPT-5")
    c = _article(id=3, title="Anthropic releases Claude")
    d = _article(id=4, title="---")
    articles = [a, b, c, d]

    reference = cluster_articles(articles)

    for ordering in permutations(articles):
        assert cluster_articles(list(ordering)) == reference


def test_clusters_are_ordered_by_key_then_empty_title_singletons_last() -> None:
    a = _article(id=1, title="Zebra event")
    b = _article(id=2, title="Alpha event")
    c = _article(id=3, title="---")

    clusters = cluster_articles([a, b, c])

    assert [cluster.key for cluster in clusters] == ["alpha event", "zebra event", ""]


def test_articles_within_a_cluster_are_ordered_by_id() -> None:
    a = _article(id=5, title="OpenAI launches GPT-5")
    b = _article(id=2, title="OpenAI launches GPT-5")
    c = _article(id=8, title="OpenAI launches GPT-5")

    clusters = cluster_articles([a, b, c])

    assert [article.id for article in clusters[0].articles] == [2, 5, 8]
