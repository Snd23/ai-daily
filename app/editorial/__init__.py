"""Editorial content assembly (TASK-019) and newspaper layout (TASK-020).

`event_editorial` aggregates already-generated VERIFY/SUMMARIZE/AI SENZA
SBATTI/DEVELOPER IMPACT outputs into a single, immutable `EditorialContent`
for one event in one language. `edition` composes several already-assembled
`EditorialContent` into an `Edition` (Top Stories, category sections, What
to Watch). Both are pure and in-memory: no database access, no LLM call, no
persistence, no classification, no ranking and no PDF rendering (approved
TASK-019/TASK-020 scope).
"""

from app.editorial.edition import (
    Edition,
    EditionSection,
    EditorialCategory,
    EventForEdition,
    assemble_edition,
)
from app.editorial.event_editorial import EditorialContent, assemble_editorial_content

__all__ = [
    "Edition",
    "EditionSection",
    "EditorialCategory",
    "EditorialContent",
    "EventForEdition",
    "assemble_edition",
    "assemble_editorial_content",
]
