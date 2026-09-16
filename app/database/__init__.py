"""Database access: SQLite connection, schema migrations and repositories.

No ORM: data access is plain stdlib `sqlite3` (docs/ARCHITECTURE.md §1.2).
Entity-specific repositories are added by the tasks that need them
(TODO.md, Milestone 2 onward); `Source`/`SourceRepository` (TASK-005),
`Article`/`ArticleRepository` (TASK-007) and `Event`/`EventRepository`
(TASK-011) were the first three, joined by `EventContent` and
`EditionRecord` with their repositories (TASK-024), which persist the
generated content and the publication record of one edition.
"""

from app.database.article import Article
from app.database.article_repository import ArticleRepository
from app.database.connection import get_connection
from app.database.edition import EditionRecord
from app.database.edition_repository import EditionRepository
from app.database.event import Event
from app.database.event_content import EventContent
from app.database.event_content_repository import EventContentRepository
from app.database.event_repository import EventRepository
from app.database.migrations import DEFAULT_MIGRATIONS_DIR, run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

__all__ = [
    "DEFAULT_MIGRATIONS_DIR",
    "Article",
    "ArticleRepository",
    "EditionRecord",
    "EditionRepository",
    "Event",
    "EventContent",
    "EventContentRepository",
    "EventRepository",
    "Source",
    "SourceRepository",
    "get_connection",
    "run_migrations",
]
