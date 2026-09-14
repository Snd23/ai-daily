-- Widen article.published_at to nullable (TASK-007).
--
-- The RSS collector must preserve the absence of a publication date when a
-- feed entry does not provide one, rather than inventing one
-- (CLAUDE.md §17, §41). The column was created NOT NULL in TASK-004
-- (0001_initial_schema.sql), before this requirement was identified.
--
-- SQLite has no ALTER COLUMN to drop a NOT NULL constraint, so this follows
-- SQLite's documented "recreate the table" pattern: build a new table with
-- the widened column, copy the existing rows across unchanged, drop the
-- old table, then rename. No other table has a foreign key referencing
-- article.id, so this is safe to do without touching any other table.
--
-- All other columns/constraints are unchanged from 0001_initial_schema.sql.

CREATE TABLE article_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES source (id),
    event_id INTEGER REFERENCES event (id),
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    raw_excerpt TEXT NOT NULL,
    normalized_text TEXT,
    content_hash TEXT,
    language TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processed', 'discarded', 'error')
    )
);

INSERT INTO article_new
    (id, source_id, event_id, title, url, published_at, fetched_at, raw_excerpt,
     normalized_text, content_hash, language, status)
SELECT
    id, source_id, event_id, title, url, published_at, fetched_at, raw_excerpt,
    normalized_text, content_hash, language, status
FROM article;

DROP TABLE article;

ALTER TABLE article_new RENAME TO article;
