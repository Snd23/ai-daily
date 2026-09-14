"""Article clustering (TASK-012): CLUSTER EVENTS.

Groups `Article` instances believed to describe the same real-world event,
by exact normalized-title match. Distinct from `app.deduplication`
(TASK-009), which groups exact-content duplicates via `content_hash` --
see `app.clustering.article_clusterer` for the full boundary. Pure,
in-memory: never touches the database, never creates or updates an
`Event`, never writes `Article.event_id`/`status`/`duplicate_of`
(approved TASK-012 scope, MODEL B).
"""

from app.clustering.article_clusterer import ArticleCluster, cluster_articles, normalize_title

__all__ = [
    "ArticleCluster",
    "cluster_articles",
    "normalize_title",
]
