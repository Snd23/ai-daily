"""Database access: SQLite connection, schema migrations and repositories.

No ORM: data access is plain stdlib `sqlite3` (docs/ARCHITECTURE.md §1.2).
Entity-specific repositories are added by the tasks that need them
(TODO.md, Milestone 2 onward); `Source`/`SourceRepository` is the first one
(TASK-005).
"""

from app.database.connection import get_connection
from app.database.migrations import DEFAULT_MIGRATIONS_DIR, run_migrations
from app.database.source import Source
from app.database.source_repository import SourceRepository

__all__ = [
    "DEFAULT_MIGRATIONS_DIR",
    "Source",
    "SourceRepository",
    "get_connection",
    "run_migrations",
]
