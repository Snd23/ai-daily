"""News collection: fetches articles from configured sources.

`RssCollector` (TASK-007) is the first collector, handling `Source.type ==
"rss"` only. Collectors for `api` and `html` sources are reserved for
future tasks (TODO.md, Milestone 2).
"""

from app.collectors.rss import RssCollector, SourceCollectionResult

__all__ = [
    "RssCollector",
    "SourceCollectionResult",
]
