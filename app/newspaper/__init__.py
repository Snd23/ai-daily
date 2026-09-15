"""PDF rendering for the newspaper generator (TASK-021).

`render_edition` turns an already-composed `Edition` (TASK-019/TASK-020)
into a complete PDF newspaper, entirely in memory: no database access, no
filesystem access, no LLM call, no persistence, and no re-decision of
Top Stories/section/What to Watch selection or ordering (approved
TASK-021 scope).
"""

from app.newspaper.errors import NewspaperRenderError
from app.newspaper.renderer import NewspaperMetadata, render_edition

__all__ = [
    "NewspaperMetadata",
    "NewspaperRenderError",
    "render_edition",
]
