"""SQL migration runner.

Applies numbered `.sql` migration scripts against a SQLite connection, in
filename order, tracking which ones have already run in a
`schema_migrations` table so re-running is a no-op
(docs/ARCHITECTURE.md §1.2: "migrations as numbered SQL scripts applied at
startup"). No external migration framework: plain stdlib `sqlite3` reading
plain SQL files.

Each migration file is expected to contain only `;`-terminated statements
with no `;` inside string values (full-line `--` comments are stripped
before splitting, so a `;` inside one of those is harmless). A splitter
that understands full SQL string/comment syntax is unnecessary complexity
for the small, hand-written scripts this project uses.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_SCHEMA_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


def run_migrations(
    connection: sqlite3.Connection, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
) -> list[str]:
    """Apply every pending migration in `migrations_dir`, in filename order.

    Each migration runs as a single atomic transaction (all its statements
    succeed, or none of them are kept). A migration already recorded in
    `schema_migrations` is skipped, so calling this again is a no-op.

    Returns:
        The filenames of the migrations applied by this call (empty if
        every migration was already applied).
    """
    connection.execute(_CREATE_SCHEMA_MIGRATIONS_TABLE)
    connection.commit()

    already_applied = {
        row[0] for row in connection.execute("SELECT filename FROM schema_migrations")
    }

    newly_applied: list[str] = []
    for migration_path in sorted(migrations_dir.glob("*.sql")):
        if migration_path.name in already_applied:
            continue

        script = migration_path.read_text(encoding="utf-8")
        _apply_migration(connection, script)
        connection.execute(
            "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
            (migration_path.name, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        newly_applied.append(migration_path.name)

    return newly_applied


def _apply_migration(connection: sqlite3.Connection, script: str) -> None:
    """Run every statement in `script` as a single atomic transaction.

    `sqlite3.Connection.executescript` cannot be used here: it implicitly
    commits any pending transaction before running, and then executes each
    statement in autocommit mode, which defeats manual transaction control.
    Statements are therefore executed one at a time inside an explicit
    BEGIN/COMMIT, with a ROLLBACK on failure.
    """
    original_isolation_level = connection.isolation_level
    connection.isolation_level = None  # full manual transaction control
    try:
        connection.execute("BEGIN")
        for statement in _split_statements(script):
            connection.execute(statement)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.isolation_level = original_isolation_level


def _split_statements(script: str) -> list[str]:
    """Split a migration script into individual `;`-terminated statements.

    Full-line `--` comments are dropped first, so a `;` written inside one
    is never mistaken for a statement terminator.
    """
    code_lines = (line for line in script.splitlines() if not line.strip().startswith("--"))
    code_only = "\n".join(code_lines)
    return [statement.strip() for statement in code_only.split(";") if statement.strip()]
