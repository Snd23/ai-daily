"""Application configuration: environment-based settings and editorial labels.

Two independent configuration concerns live here, kept separate as required
by CLAUDE.md: application/environment settings (secrets and runtime
parameters, see `.env.example`) and editorial label data (`config/labels.yaml`).

See docs/ARCHITECTURE.md §1.1, §5.1, §5.2 and §9 for the design this module
implements.
"""

from app.config.errors import ConfigurationError
from app.config.labels import Labels, load_labels
from app.config.settings import (
    APP_TIMEZONE,
    APP_TIMEZONE_NAME,
    SUPPORTED_LANGUAGES,
    Settings,
    load_settings,
)

__all__ = [
    "APP_TIMEZONE",
    "APP_TIMEZONE_NAME",
    "SUPPORTED_LANGUAGES",
    "ConfigurationError",
    "Labels",
    "Settings",
    "load_labels",
    "load_settings",
]
