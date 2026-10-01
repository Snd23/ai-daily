"""Tests for `app.clustering.cluster_merger` (TASK-038)."""

from __future__ import annotations

import pytest

from app.clustering import ArticleCluster, cluster_articles
from app.clustering.cluster_merger import ClusterMergeParseError, merge_similar_clusters
from app.database.article import Article
from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider


class _FakeProvider(LLMProvider):
    def __init__(self, text: str = "NONE", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return CompletionResponse(text=self.text)


_PUBLISHED = "2026-09-30T10:00:00+00:00"


def _article(article_id: int, title: str, published_at: str | None = _PUBLISHED) -> Article:
    return Article(
        id=article_id,
        source_id=article_id,
        title=title,
        url=f"https://example.com/{article_id}",
        published_at=published_at,
        fetched_at="2026-09-30T12:00:00+00:00",
        raw_excerpt="x",
    )


def _clusters(*articles: Article) -> list[ArticleCluster]:
    return cluster_articles(list(articles))


_DOTS = [
    _article(1, "Introducing dots"),
    _article(2, "OpenAI's Dots Are Always-On AI Agents"),
    _article(3, "Perplexity improves accuracy with Astra"),
]


def _user_prompt(provider: _FakeProvider) -> str:
    return provider.requests[0].messages[1].content


def test_clusters_with_no_shared_distinctive_word_cause_no_llm_call() -> None:
    provider = _FakeProvider()
    clusters = _clusters(_article(1, "Introducing dots"), _article(2, "Perplexity adds Astra"))

    assert merge_similar_clusters(provider, clusters) == clusters
    assert provider.requests == []


def test_a_group_answer_merges_the_clusters_and_sorts_their_articles() -> None:
    provider = _FakeProvider("GROUP: 1, 2")
    clusters = _clusters(*_DOTS)

    merged = merge_similar_clusters(provider, clusters)

    assert [[a.id for a in cluster.articles] for cluster in merged] == [[1, 2], [3]]
    assert len(provider.requests) == 1


def test_only_the_candidate_titles_are_sent() -> None:
    provider = _FakeProvider()

    merge_similar_clusters(provider, _clusters(*_DOTS))

    prompt = _user_prompt(provider)
    assert "Introducing dots" in prompt
    assert "Perplexity improves accuracy with Astra" not in prompt


def test_none_answer_keeps_every_cluster() -> None:
    clusters = _clusters(*_DOTS)

    assert merge_similar_clusters(_FakeProvider("NONE"), clusters) == clusters


def test_a_word_present_in_too_many_clusters_is_not_distinctive() -> None:
    articles = [_article(i, f"OpenAI announces thing{i}") for i in range(1, 9)]
    provider = _FakeProvider()

    merge_similar_clusters(provider, _clusters(*articles))

    assert provider.requests == []


def test_articles_published_far_apart_are_not_candidates() -> None:
    clusters = _clusters(
        _article(1, "Introducing dots", "2026-09-20T10:00:00+00:00"),
        _article(2, "Dots are always-on agents", "2026-09-30T10:00:00+00:00"),
    )
    provider = _FakeProvider()

    merge_similar_clusters(provider, clusters)

    assert provider.requests == []


def test_a_missing_publication_date_does_not_exclude_a_candidate() -> None:
    clusters = _clusters(_article(1, "Introducing dots", None), _article(2, "Dots are agents"))
    provider = _FakeProvider("GROUP: 1, 2")

    assert len(merge_similar_clusters(provider, clusters)) == 1


@pytest.mark.parametrize(
    "answer",
    [
        "Sure! GROUP: 1, 2",
        "GROUP: 1",
        "GROUP: 1, 1",
        "GROUP: 1, 9",
        "GROUP: 1, 2\nGROUP: 2, 3",
        "",
    ],
)
def test_a_malformed_answer_is_rejected(answer: str) -> None:
    with pytest.raises(ClusterMergeParseError):
        merge_similar_clusters(_FakeProvider(answer), _clusters(*_DOTS))


def test_a_group_of_unlinked_titles_is_ignored_and_the_other_groups_are_kept() -> None:
    clusters = _clusters(
        _article(1, "Introducing dots"),
        _article(2, "Dots are agents"),
        _article(3, "Nvidia ships Rubin"),
        _article(4, "Rubin arrives at CoreWeave"),
    )

    merged = merge_similar_clusters(_FakeProvider("GROUP: 1, 3\nGROUP: 2, 4"), clusters)

    assert merged == clusters


def test_a_valid_group_survives_next_to_an_unlinked_one() -> None:
    # Items are numbered in the order of the normalized titles:
    # 1-2 dots, 3-4 moon, 5-6 rubin.
    clusters = _clusters(
        _article(1, "Introducing dots"),
        _article(2, "Dots are agents"),
        _article(3, "Moon landing planned"),
        _article(4, "Landing on moon delayed"),
        _article(5, "Nvidia ships Rubin"),
        _article(6, "Rubin arrives at CoreWeave"),
    )

    merged = merge_similar_clusters(_FakeProvider("GROUP: 1, 2\nGROUP: 3, 5"), clusters)

    assert sorted(len(cluster.articles) for cluster in merged) == [1, 1, 1, 1, 2]


def test_a_provider_error_propagates() -> None:
    provider = _FakeProvider(error=LLMProviderError("down"))

    with pytest.raises(LLMProviderError):
        merge_similar_clusters(provider, _clusters(*_DOTS))
