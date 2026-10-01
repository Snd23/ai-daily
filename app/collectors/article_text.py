"""Full article text retrieval (TASK-031).

RSS excerpts are far too short to ground a complete summary (75-650 characters
on average), so for the events already selected for the edition the pipeline
downloads the article page and extracts its body with `trafilatura`.

The page is untrusted web content (CLAUDE.md §10-11): this module only returns
text, which the caller treats as data. A page that cannot be fetched, is not
HTML, or has no extractable body yields `None` and a log line, never an
exception: the caller falls back to the RSS excerpt (CLAUDE.md §33-34).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests
import trafilatura

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0

# Per-article cap on the text sent to the LLM (CLAUDE.md §35; free-tier limits
# are a design constraint).
MAX_ARTICLE_CHARS = 6000


def fetch_article_text(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = MAX_ARTICLE_CHARS,
) -> str | None:
    """Download `url` and return its main text, cut to `max_chars`, or `None`."""
    if urlparse(url).scheme not in ("http", "https"):
        logger.warning("Article text not fetched: %s is not an http(s) URL", url)
        return None
    try:
        response = requests.get(url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Could not fetch article text from %s: %s", url, exc)
        return None

    if "html" not in response.headers.get("Content-Type", "").lower():
        logger.warning("Article page %s is not HTML: text not extracted", url)
        return None

    text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not text or not text.strip():
        logger.warning("No article text could be extracted from %s", url)
        return None
    # U+2011 (non-breaking hyphen) is missing from the PDF font and prints as a box.
    text = text.replace("‑", "-")
    return _truncate(_neutralize_delimiter(text.strip()), max_chars)


def _neutralize_delimiter(text: str) -> str:
    """Break any `</article` in page text so it cannot close the prompt's data block.

    The summarization and Developer Impact prompts wrap each article in
    `<article>` tags; page text is untrusted (CLAUDE.md §10-11).
    """
    return re.sub(r"</(\s*)article", r"< /article", text, flags=re.IGNORECASE)


def _truncate(text: str, max_chars: int) -> str:
    """Cut `text` to at most `max_chars`, at a word boundary when there is one."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    boundary = cut.rfind(" ")
    return cut[:boundary] if boundary > 0 else cut
