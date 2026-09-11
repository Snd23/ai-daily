"""SQLite connection management.

Opens connections against the database configured by `Settings.database_url`
(docs/PRD.md §20, §26; `.env.example`). Foreign keys are off by default in
SQLite and must be enabled per connection (docs/ARCHITECTURE.md §3).

No ORM: plain stdlib `sqlite3` (docs/ARCHITECTURE.md §1.2).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SQLITE_URL_PREFIX = "sqlite:///"


def get_connection(database_url: str) -> sqlite3.Connection:
    """Open a SQLite connection for `database_url`.

    `database_url` must use the `sqlite:///<path>` scheme already defined by
    `Settings.database_url`, where `<path>` is either a relative/absolute
    filesystem path (its parent directory is created if missing) or the
    literal `:memory:` for an in-memory database (used in tests).

    Raises:
        ValueError: if `database_url` does not use the `sqlite:///` scheme.
    """
    if not database_url.startswith(_SQLITE_URL_PREFIX):
        raise ValueError(
            f"Unsupported database URL: {database_url!r} (expected {_SQLITE_URL_PREFIX}<path>)"
        )

    path = database_url[len(_SQLITE_URL_PREFIX) :]

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
