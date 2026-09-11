"""Database access: SQLite connection and schema migrations.

No ORM: data access is plain stdlib `sqlite3` (docs/ARCHITECTURE.md §1.2).
This package only provides the connection and migration infrastructure;
entity-specific repositories are added by the tasks that need them
(TODO.md, Milestone 2 onward).
"""

from app.database.connection import get_connection
from app.database.migrations import DEFAULT_MIGRATIONS_DIR, run_migrations

__all__ = [
    "DEFAULT_MIGRATIONS_DIR",
    "get_connection",
    "run_migrations",
]
