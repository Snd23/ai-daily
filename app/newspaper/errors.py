"""Shared exceptions for the newspaper rendering subsystem (TASK-021)."""


class NewspaperRenderError(Exception):
    """Raised when rendering an `Edition` to PDF fails.

    Wraps the underlying ReportLab exception (via `raise ... from exc`) so
    callers can handle a rendering failure without importing or catching
    ReportLab-specific exception types (CLAUDE.md §19's provider-wrapping
    principle, applied here to the rendering dependency).
    """
