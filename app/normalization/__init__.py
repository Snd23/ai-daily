"""Article normalization (TASK-008).

Turns the raw, potentially HTML-laden `Article.raw_excerpt` collected by
`RssCollector` (TASK-007) into `normalized_text`, `content_hash` and
`language` (docs/ARCHITECTURE.md §2's NORMALIZE stage). Does not touch
`status`, `published_at` or `event_id` -- those remain the responsibility
of the collector and later pipeline stages.
"""

from app.normalization.article_normalizer import (
    NormalizationBatchResult,
    NormalizationResult,
    calculate_content_hash,
    detect_language,
    normalize_article,
    normalize_article_content,
    normalize_pending_articles,
    normalize_text,
    normalize_whitespace,
    strip_html,
)

__all__ = [
    "NormalizationBatchResult",
    "NormalizationResult",
    "calculate_content_hash",
    "detect_language",
    "normalize_article",
    "normalize_article_content",
    "normalize_pending_articles",
    "normalize_text",
    "normalize_whitespace",
    "strip_html",
]
