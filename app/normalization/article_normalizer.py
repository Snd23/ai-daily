"""Pure text normalization plus thin persistence orchestration (TASK-008).

Two layers, kept deliberately separate (approved design §2-§3, §9):

- Pure functions (`strip_html`, `normalize_whitespace`, `normalize_text`,
  `calculate_content_hash`, `detect_language`, `normalize_article_content`)
  never touch `sqlite3` or `ArticleRepository`. They are ordinary string ->
  string/None functions, deterministic and independently testable.
- Orchestration (`normalize_article`, `normalize_pending_articles`) knows
  about `Article`/`ArticleRepository` but contains no SQL itself -- all
  persistence goes through `ArticleRepository` (TASK-008 spec §9).

`raw_excerpt` is untrusted input collected from the web (CLAUDE.md §10-11):
everything here only ever *extracts text*. Nothing in this module executes,
evaluates or interprets any part of it.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

from langdetect import DetectorFactory, LangDetectException, detect

from app.database.article import Article
from app.database.article_repository import ArticleRepository

logger = logging.getLogger(__name__)

# Makes langdetect's internal (otherwise unseeded) algorithm deterministic --
# without this, the same text can return a different language across calls.
# Set once at import time, matching langdetect's own documented usage.
DetectorFactory.seed = 0

_SKIPPED_TAGS = frozenset({"script", "style"})

# Tags whose boundaries separate text. Without them `<p>One</p><p>Two</p>`
# would extract as "OneTwo": `HTMLParser` reports tags and text separately,
# so nothing in the text stream marks where one element ends and the next
# begins. Inline tags (`<b>`, `<span>`, `<a>`, `<em>`, `<img>`, ...) are
# deliberately absent, so `Tom<b>my</b>` still extracts as "Tommy".
# `td`/`th` accompany `tr`: separating rows but not cells would glue a
# row's cells together.
_SEPARATING_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
        "pre",
        "tr",
        "td",
        "th",
    }
)

_WHITESPACE_RUN = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Collects text content, dropping tags and `<script>`/`<style>` bodies.

    A boundary of a `_SEPARATING_TAGS` element emits a single space, so the
    text of adjacent block-level elements is never concatenated. The space
    is emitted lazily -- just before the next text chunk, and only when
    some text was already collected -- so leading spaces and runs of
    separators are never produced in the first place.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._separator_pending = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _SEPARATING_TAGS:
            self._separator_pending = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in _SEPARATING_TAGS:
            self._separator_pending = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._separator_pending:
            if self._chunks:
                self._chunks.append(" ")
            self._separator_pending = False
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def strip_html(html: str) -> str:
    """Remove HTML markup from `html`, discarding `<script>`/`<style>` bodies.

    Block-level element boundaries (`_SEPARATING_TAGS`) become a single
    space, so `<p>One</p><p>Two</p>` extracts as "One Two" rather than
    "OneTwo"; inline markup introduces no space, so `Tom<b>my</b>` still
    extracts as "Tommy". Whitespace already present in `html` is passed
    through untouched -- collapsing it is `normalize_whitespace`'s job.

    Never executes or interprets `html`: this only ever extracts text via
    `html.parser.HTMLParser`, never `eval`/`exec`/template rendering
    (CLAUDE.md §10-11 -- `raw_excerpt` is untrusted web content).

    `HTMLParser` is documented as tolerant of malformed markup and is not
    expected to raise on real-world input; if it somehow does, whatever
    text had already been extracted is returned rather than crashing the
    caller.
    """
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - deliberate last-resort fallback, see docstring
        logger.warning("HTML parsing failed; falling back to partially extracted text")
    return parser.get_text()


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and trim both ends."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def normalize_text(raw_excerpt: str) -> str:
    """Turn raw, possibly-HTML feed content into clean, comparable text.

    Pipeline (order matters -- approved design §5): strip HTML -> decode
    HTML entities -> Unicode NFKC -> collapse whitespace -> trim. Stripping
    tags *before* decoding entities is deliberate: text that encodes a
    literal "<p>" as `&lt;p&gt;` must not be resurrected into a real tag
    and then stripped away.

    Deterministic: the same `raw_excerpt` always produces the same result
    (no randomness, no external state).
    """
    text = strip_html(raw_excerpt)
    text = unescape(text)
    text = unicodedata.normalize("NFKC", text)
    return normalize_whitespace(text)


def calculate_content_hash(normalized_text: str) -> str:
    """SHA-256 hex digest of `normalized_text`, encoded as UTF-8.

    Computed *only* from `normalized_text` -- never `title`, `url`,
    `source_id`, `published_at` or `language` (TASK-008 spec §6).
    Deterministic: the same string always produces the same digest.
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def detect_language(normalized_text: str) -> str | None:
    """Best-effort language code for `normalized_text`, or `None`.

    Never raises and never fabricates a language (CLAUDE.md §41): empty,
    whitespace-only or otherwise non-linguistic text makes `langdetect`
    itself raise `LangDetectException`, which this maps to `None`.

    This deliberately does *not* add a probability-threshold check for
    "too short/ambiguous" text beyond what `langdetect` itself already
    rejects. The approved design (§12) identified that implementing that
    part of the requirement needs an arbitrary confidence cutoff that no
    specification defines -- and verification during implementation
    confirmed it: `langdetect.detect_langs()` reports ~99.999% confidence
    even for inputs like "OK" (detected as Portuguese) or "Ciao" (detected
    as Portuguese, not Italian), so a probability threshold would not
    reliably solve the problem being asked for either. Per the design
    review's own resolution for this case, this implements only what is
    actually determinable; the rest is flagged as an open decision in the
    implementation report, not invented here.
    """
    try:
        # `langdetect` ships no type stubs, so `detect()` is typed `Any`;
        # the explicit annotation documents (and lets mypy check) that it
        # actually returns a `str` language code at runtime.
        language: str = detect(normalized_text)
    except LangDetectException:
        return None
    return language


@dataclass
class NormalizationResult:
    """Pure result of normalizing one `raw_excerpt` -- no article identity."""

    normalized_text: str
    content_hash: str
    language: str | None


def normalize_article_content(raw_excerpt: str) -> NormalizationResult:
    """Compute `normalized_text`/`content_hash`/`language` for `raw_excerpt`.

    Pure: no database access, no I/O. Deterministic and idempotent --
    calling this twice with the same `raw_excerpt` returns an identical
    `NormalizationResult` (see module docstrings of the functions used
    here for why each step is deterministic).
    """
    normalized_text = normalize_text(raw_excerpt)
    content_hash = calculate_content_hash(normalized_text)
    language = detect_language(normalized_text)
    return NormalizationResult(
        normalized_text=normalized_text, content_hash=content_hash, language=language
    )


def normalize_article(repository: ArticleRepository, article: Article) -> Article:
    """Normalize `article` and persist the result via `repository`.

    Reads `article.raw_excerpt`, computes the three normalization fields,
    and writes them through `ArticleRepository.update_normalization` --
    which by construction never touches `status`, `published_at`,
    `event_id`, `raw_excerpt`, `title`, `url`, `source_id` or `fetched_at`
    (TASK-008 spec §8). Contains no SQL itself.

    Raises:
        ValueError: if `article` no longer exists in the database
            (propagated from `ArticleRepository.update_normalization`).
        Exception: any other error raised by the repository update (e.g. a
            genuine `sqlite3` infrastructure failure) propagates unchanged
            -- see `normalize_pending_articles` for how the batch entry
            point treats these two cases differently.
    """
    assert article.id is not None  # a persisted Article always has an id
    result = normalize_article_content(article.raw_excerpt)
    repository.update_normalization(
        article.id,
        normalized_text=result.normalized_text,
        content_hash=result.content_hash,
        language=result.language,
    )
    return article.model_copy(
        update={
            "normalized_text": result.normalized_text,
            "content_hash": result.content_hash,
            "language": result.language,
        }
    )


@dataclass
class NormalizationBatchResult:
    """Outcome of one `normalize_pending_articles` call.

    `succeeded` holds each `Article` (post-update) that was normalized
    successfully, in processing order. `failed` holds `(Article, error
    message)` pairs for articles skipped because they no longer existed
    when the update was attempted -- logged, never aborting the batch.
    """

    succeeded: list[Article] = field(default_factory=list)
    failed: list[tuple[Article, str]] = field(default_factory=list)


def normalize_pending_articles(repository: ArticleRepository) -> NormalizationBatchResult:
    """Normalize every `Article` with `status == 'pending'`, one by one.

    `status` is never read as a selection criterion beyond what
    `ArticleRepository.list_pending` already applies, and is never written
    by this function (TASK-008 spec §1, §9).

    An article that no longer exists by the time its update is attempted
    (`ValueError` from `ArticleRepository.update_normalization` -- a
    benign race, not an infrastructure problem) is logged and skipped; the
    rest of the batch still runs, mirroring the per-source resilience
    already established by `RssCollector.collect_all` (TASK-007).

    Any other exception (in particular a genuine `sqlite3` infrastructure
    failure) is treated as critical and propagates, aborting the batch --
    consistent with the same distinction TASK-007 already draws between
    "one item failed" and "the database itself is broken".
    """
    result = NormalizationBatchResult()
    for article in repository.list_pending():
        try:
            result.succeeded.append(normalize_article(repository, article))
        except ValueError as exc:
            logger.warning(
                "Skipping article id=%s (%s) during normalization: %s",
                article.id,
                article.url,
                exc,
            )
            result.failed.append((article, str(exc)))
    return result
