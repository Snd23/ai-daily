-- Add edition.content (TASK-043).
--
-- Stores the composed edition (app.editorial.edition.Edition: Top Stories,
-- category sections, What to Watch) as JSON, exactly as it was passed to
-- the PDF renderer, so a reader other than the PDF (the web app, TASK-044)
-- can show the same content without recomposing it.
--
-- NULL for editions that were never published, and for editions published
-- before this migration (their composition was never stored).

ALTER TABLE edition ADD COLUMN content TEXT;
