"""Tests for `app.normalization.article_normalizer` (TASK-008).

Pure-function tests (`strip_html` through `normalize_article_content`) need
no database. `normalize_article`/`normalize_pending_articles` are exercised
against a real, migrated in-memory SQLite database, same fixture pattern as
`tests/test_article_repository.py`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator

import pytest
from langdetect import LangDetectException

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository
from app.normalization.article_normalizer import (
    calculate_content_hash,
    detect_language,
    normalize_article,
    normalize_article_content,
    normalize_pending_articles,
    normalize_text,
    normalize_whitespace,
    strip_html,
)

# --- strip_html --------------------------------------------------------


def test_strip_html_removes_simple_tag() -> None:
    assert strip_html("<p>Hello</p>") == "Hello"


def test_strip_html_removes_nested_tags() -> None:
    assert strip_html("<div><p>Nested <b>bold <i>italic</i></b> text</p></div>") == (
        "Nested bold italic text"
    )


def test_strip_html_handles_self_closing_tags() -> None:
    # <br/> separates text, <img/> is inline and must not introduce a space.
    assert strip_html("Before<br/>After<img src='x.png'/>End") == "Before AfterEnd"


def test_strip_html_discards_script_tag_content() -> None:
    assert strip_html("<script>import os; os.system('x')</script>Visible") == "Visible"


def test_strip_html_discards_style_tag_content() -> None:
    assert strip_html("<style>.a { color: red; }</style>Visible") == "Visible"


def test_strip_html_never_raises_on_malformed_markup() -> None:
    assert strip_html("<p>Unclosed <b>bold text") == "Unclosed bold text"


def test_strip_html_preserves_plain_text_unchanged() -> None:
    assert strip_html("Plain text, no markup at all.") == "Plain text, no markup at all."


def test_strip_html_decodes_entities_encountered_while_parsing() -> None:
    assert strip_html("A &amp; B") == "A & B"


def test_strip_html_does_not_resurrect_escaped_tags() -> None:
    # &lt;fake&gt; must stay literal text, never be treated as a real tag
    # that then gets stripped away.
    assert strip_html("<p>Text with &lt;fake&gt; tag</p>") == "Text with <fake> tag"


def test_strip_html_never_executes_script_content() -> None:
    # CLAUDE.md §10-11: untrusted content must only ever be extracted as
    # text, never interpreted/executed.
    result = strip_html("<script>import os; os.system('echo pwned')</script>Safe")
    assert result == "Safe"
    assert "os.system" not in result


# --- strip_html: block-level separation ----------------------------------
# Regression tests: adjacent block-level elements used to be concatenated
# without any separator ("<p>One</p><p>Two</p>" extracted as "OneTwo"),
# corrupting normalized_text and therefore content_hash.


def test_strip_html_separates_adjacent_divs() -> None:
    assert strip_html("<div>a</div><div>b</div>") == "a b"


def test_strip_html_separates_adjacent_paragraphs() -> None:
    assert strip_html("<p>a</p><p>b</p>") == "a b"


def test_strip_html_separates_across_a_line_break() -> None:
    assert strip_html("a<br>b") == "a b"


def test_strip_html_separates_adjacent_list_items() -> None:
    assert strip_html("<li>a</li><li>b</li>") == "a b"


def test_strip_html_separates_heading_from_body() -> None:
    assert strip_html("<h1>Title</h1><p>Body</p>") == "Title Body"


def test_strip_html_separates_nested_block_elements() -> None:
    assert strip_html("<ul><li>a</li><li>b</li></ul>") == "a b"


def test_strip_html_separates_table_cells_and_rows() -> None:
    assert strip_html("<tr><td>a</td><td>b</td></tr><tr><td>c</td></tr>") == "a b c"


# --- strip_html: inline elements must NOT introduce spaces ----------------


def test_strip_html_inline_bold_does_not_split_a_word() -> None:
    assert strip_html("Tom<b>my</b>") == "Tommy"


def test_strip_html_inline_span_does_not_split_a_word() -> None:
    assert strip_html("<a>Open</a><span>AI</span>") == "OpenAI"


def test_strip_html_inline_strong_and_em_do_not_split_a_word() -> None:
    assert strip_html("<strong>Open</strong><em>AI</em>") == "OpenAI"


def test_strip_html_keeps_existing_space_around_inline_markup() -> None:
    assert strip_html("Hello <strong>world</strong>") == "Hello world"


def test_strip_html_does_not_add_a_leading_space_for_a_leading_block_tag() -> None:
    assert strip_html("<p>Hello</p>") == "Hello"


# --- normalize_whitespace ------------------------------------------------


def test_normalize_whitespace_collapses_multiple_spaces() -> None:
    assert normalize_whitespace("a    b") == "a b"


def test_normalize_whitespace_collapses_tabs() -> None:
    assert normalize_whitespace("a\t\tb") == "a b"


def test_normalize_whitespace_collapses_newlines() -> None:
    assert normalize_whitespace("a\n\n\nb") == "a b"


def test_normalize_whitespace_collapses_mixed_whitespace() -> None:
    assert normalize_whitespace("a \t\n b") == "a b"


def test_normalize_whitespace_trims_leading_and_trailing() -> None:
    assert normalize_whitespace("   a b   ") == "a b"


def test_normalize_whitespace_empty_string() -> None:
    assert normalize_whitespace("") == ""


def test_normalize_whitespace_only_whitespace_becomes_empty() -> None:
    assert normalize_whitespace("   \n\t  ") == ""


# --- normalize_text (full pipeline) --------------------------------------


def test_normalize_text_full_pipeline() -> None:
    assert normalize_text("  <p>Hello &amp; <b>World</b></p>  ") == "Hello & World"


def test_normalize_text_decodes_numeric_entities() -> None:
    assert normalize_text("A &#39;quote&#39;") == "A 'quote'"


def test_normalize_text_applies_nfkc_to_fullwidth_characters() -> None:
    fullwidth_abc = chr(0xFF21) + chr(0xFF22) + chr(0xFF23)
    assert normalize_text(fullwidth_abc) == "ABC"


def test_normalize_text_applies_nfkc_to_combining_characters() -> None:
    decomposed = "e" + chr(0x0301) + "cole"  # "e" + combining acute accent
    assert normalize_text(decomposed) == chr(0xE9) + "cole"  # precomposed "é"


def test_normalize_text_collapses_whitespace_after_stripping_tags() -> None:
    assert normalize_text("<p>Line one</p>\n\n<p>Line   two</p>") == "Line one Line two"


def test_normalize_text_empty_raw_excerpt() -> None:
    assert normalize_text("") == ""


def test_normalize_text_html_only_becomes_empty() -> None:
    assert normalize_text("<img src='x.png'/>") == ""


def test_normalize_text_is_deterministic() -> None:
    raw = "<p>Some &amp; text</p>"
    assert normalize_text(raw) == normalize_text(raw)


# --- calculate_content_hash -----------------------------------------------


def test_calculate_content_hash_is_a_sha256_hex_digest() -> None:
    digest = calculate_content_hash("hello")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_calculate_content_hash_matches_known_sha256_of_empty_string() -> None:
    assert calculate_content_hash("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_calculate_content_hash_same_input_same_hash() -> None:
    assert calculate_content_hash("same text") == calculate_content_hash("same text")


def test_calculate_content_hash_different_input_different_hash() -> None:
    assert calculate_content_hash("text a") != calculate_content_hash("text b")


def test_calculate_content_hash_uses_utf8_encoding() -> None:
    text = "café"
    assert calculate_content_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_equivalent_markup_produces_the_same_normalized_text_and_hash() -> None:
    # Markup that renders identically must normalize identically, otherwise
    # content_hash cannot be used to recognise the same content arriving
    # with cosmetically different HTML.
    variants = [
        "<p>Hello</p><p>world</p>",
        "<p>Hello</p> <p>world</p>",
        "<p>Hello</p>\n\n<p>world</p>",
        "<div>Hello</div><div>world</div>",
    ]

    normalized = {normalize_text(variant) for variant in variants}
    hashes = {calculate_content_hash(normalize_text(variant)) for variant in variants}

    assert normalized == {"Hello world"}
    assert len(hashes) == 1


# --- detect_language --------------------------------------------------

_EN = (
    "The quick brown fox jumps over the lazy dog while the sun sets "
    "slowly behind the distant mountains."
)
_IT = (
    "Il rapido gatto marrone salta sopra il cane pigro mentre il sole "
    "tramonta lentamente dietro le montagne lontane."
)
_FR = (
    "Le renard brun rapide saute par-dessus le chien paresseux pendant "
    "que le soleil se couche lentement derriere les montagnes lointaines."
)


def test_detect_language_english() -> None:
    assert detect_language(_EN) == "en"


def test_detect_language_italian() -> None:
    assert detect_language(_IT) == "it"


def test_detect_language_french() -> None:
    assert detect_language(_FR) == "fr"


def test_detect_language_empty_text_returns_none() -> None:
    assert detect_language("") is None


def test_detect_language_whitespace_only_returns_none() -> None:
    assert detect_language("   ") is None


def test_detect_language_no_linguistic_content_returns_none() -> None:
    assert detect_language("123 456 789") is None


def test_detect_language_never_lets_langdetectexception_escape() -> None:
    try:
        detect_language("")
    except LangDetectException:
        pytest.fail("detect_language must never let LangDetectException escape")


def test_detect_language_is_deterministic_across_repeated_calls() -> None:
    results = {detect_language(_EN) for _ in range(10)}
    assert results == {"en"}


# --- normalize_article_content (pure orchestration) ------------------------


def test_normalize_article_content_composes_all_three_fields() -> None:
    result = normalize_article_content("<p>Hello &amp; World</p>")

    assert result.normalized_text == "Hello & World"
    assert result.content_hash == calculate_content_hash("Hello & World")
    assert result.language == "en"


def test_normalize_article_content_is_idempotent() -> None:
    raw = f"<p>{_IT}</p>"

    first = normalize_article_content(raw)
    second = normalize_article_content(raw)

    assert first == second


# --- normalize_article / normalize_pending_articles (integration) ----------


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
def source_id(connection: sqlite3.Connection) -> int:
    created = SourceRepository(connection).create(
        Source(
            name="OpenAI",
            type="rss",
            url="https://openai.com/feed",
            tier=1,
            categories=[],
            reliability_weight=1.0,
            is_active=True,
        )
    )
    assert created.id is not None
    return created.id


def _make_article(source_id: int, **overrides: object) -> Article:
    values: dict[str, object] = {
        "source_id": source_id,
        "title": "Example",
        "url": "https://example.com/a",
        "published_at": "2026-09-01T10:00:00+00:00",
        "fetched_at": "2026-09-01T12:00:00+00:00",
        "raw_excerpt": "<p>Hello &amp; World</p>",
    }
    values.update(overrides)
    return Article(**values)  # type: ignore[arg-type]


def test_normalize_article_persists_and_returns_the_updated_article(
    article_repository: ArticleRepository, source_id: int
) -> None:
    created = article_repository.create(_make_article(source_id))

    updated = normalize_article(article_repository, created)

    assert updated.normalized_text == "Hello & World"
    assert updated.content_hash == calculate_content_hash("Hello & World")
    assert updated.language == "en"
    fetched = article_repository.get_by_url(created.url)
    assert fetched == updated


def test_normalize_article_does_not_change_status(
    article_repository: ArticleRepository, source_id: int
) -> None:
    created = article_repository.create(_make_article(source_id))

    normalize_article(article_repository, created)

    fetched = article_repository.get_by_url(created.url)
    assert fetched is not None
    assert fetched.status == "pending"


def test_normalize_pending_articles_empty_batch(article_repository: ArticleRepository) -> None:
    result = normalize_pending_articles(article_repository)

    assert result.succeeded == []
    assert result.failed == []


def test_normalize_pending_articles_processes_all_pending(
    article_repository: ArticleRepository, source_id: int
) -> None:
    article_repository.create(
        _make_article(source_id, url="https://example.com/a", raw_excerpt="<p>Hello world</p>")
    )
    article_repository.create(
        _make_article(source_id, url="https://example.com/b", raw_excerpt="<p>Ciao mondo</p>")
    )

    result = normalize_pending_articles(article_repository)

    assert len(result.succeeded) == 2
    assert result.failed == []
    for article in result.succeeded:
        assert article.normalized_text
        assert article.content_hash


def test_normalize_pending_articles_skips_articles_not_pending(
    article_repository: ArticleRepository, connection: sqlite3.Connection, source_id: int
) -> None:
    pending = article_repository.create(_make_article(source_id, url="https://example.com/a"))
    processed = article_repository.create(_make_article(source_id, url="https://example.com/b"))
    connection.execute("UPDATE article SET status = 'processed' WHERE id = ?", (processed.id,))
    connection.commit()

    result = normalize_pending_articles(article_repository)

    assert [a.id for a in result.succeeded] == [pending.id]


def test_normalize_pending_articles_does_not_stop_on_a_single_failure(
    article_repository: ArticleRepository, source_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = article_repository.create(_make_article(source_id, url="https://example.com/a"))
    survives = article_repository.create(_make_article(source_id, url="https://example.com/b"))
    original_update = article_repository.update_normalization

    def _update_or_fail(article_id: int, **kwargs: object) -> None:
        if article_id == failing.id:
            raise ValueError(f"No article found with id={article_id}")
        original_update(article_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(article_repository, "update_normalization", _update_or_fail)

    result = normalize_pending_articles(article_repository)

    assert [a.id for a in result.succeeded] == [survives.id]
    assert len(result.failed) == 1
    assert result.failed[0][0].id == failing.id


def test_normalize_pending_articles_propagates_non_value_error_failures(
    article_repository: ArticleRepository, source_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A genuine sqlite infrastructure failure must NOT be swallowed as a
    # per-article skip -- it aborts the batch (TASK-008 design §6).
    article_repository.create(_make_article(source_id, url="https://example.com/a"))
    article_repository.create(_make_article(source_id, url="https://example.com/b"))

    def _boom(article_id: int, **kwargs: object) -> None:
        raise sqlite3.OperationalError("simulated infrastructure failure")

    monkeypatch.setattr(article_repository, "update_normalization", _boom)

    with pytest.raises(sqlite3.OperationalError, match="simulated infrastructure failure"):
        normalize_pending_articles(article_repository)


def test_normalize_pending_articles_is_idempotent_across_repeated_runs(
    article_repository: ArticleRepository, source_id: int
) -> None:
    article_repository.create(_make_article(source_id))

    first = normalize_pending_articles(article_repository)
    # status is never changed by design, so the same article is picked up
    # again on a second run -- a documented, deliberate consequence.
    second = normalize_pending_articles(article_repository)

    assert len(first.succeeded) == 1
    assert len(second.succeeded) == 1
    assert first.succeeded[0].normalized_text == second.succeeded[0].normalized_text
    assert first.succeeded[0].content_hash == second.succeeded[0].content_hash
    assert first.succeeded[0].language == second.succeeded[0].language
