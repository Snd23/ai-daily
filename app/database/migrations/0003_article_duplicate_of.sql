-- Add article.duplicate_of (TASK-009).
--
-- Deduplication (docs/PRD.md section 8, section 250 area; CLAUDE.md section
-- 16) needs to record, for an article marked as a duplicate, which other
-- article was kept as canonical -- so the link to the original/primary
-- source is never lost even after an article is discarded
-- (CLAUDE.md section 18, docs/PRD.md section 15).
--
-- NULL means "not a duplicate" (either never evaluated, or kept as
-- canonical). No new status value, no CHECK constraint, and no index are
-- introduced here -- deliberately minimal, per the approved TASK-009
-- specification. A duplicate article is never physically deleted; it is
-- marked status = 'discarded' by the application (TASK-009), not by this
-- migration.
--
-- Unlike 0002_article_published_at_nullable.sql, SQLite's ALTER TABLE ...
-- ADD COLUMN supports adding a nullable column with a REFERENCES clause
-- directly, so no "recreate the table" step is needed here.

ALTER TABLE article ADD COLUMN duplicate_of INTEGER REFERENCES article (id);
