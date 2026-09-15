"""Editorial content assembly (TASK-019): EDITORIAL ASSEMBLY (partial).

Aggregates already-generated VERIFY/SUMMARIZE/AI SENZA SBATTI/DEVELOPER
IMPACT outputs into a single, immutable `EditorialContent` for one event in
one language. Pure and in-memory: no database access, no LLM call, no
persistence, no classification, no ranking and no citation formatting
(approved TASK-019 scope).
"""

from app.editorial.event_editorial import EditorialContent, assemble_editorial_content

__all__ = [
    "EditorialContent",
    "assemble_editorial_content",
]
