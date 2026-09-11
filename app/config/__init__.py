"""Application configuration: environment-based settings, editorial labels
and sources configuration.

Three independent configuration concerns live here, kept separate as
required by CLAUDE.md: application/environment settings (secrets and
runtime parameters, see `.env.example`), editorial label data
(`config/labels.yaml`), and the configured news sources
(`config/sources.yaml`, TASK-006).

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
from app.config.sources import DEFAULT_SOURCES_PATH, SyncResult, load_sources_config, sync_sources

__all__ = [
    "APP_TIMEZONE",
    "APP_TIMEZONE_NAME",
    "DEFAULT_SOURCES_PATH",
    "SUPPORTED_LANGUAGES",
    "ConfigurationError",
    "Labels",
    "Settings",
    "SyncResult",
    "load_labels",
    "load_settings",
    "load_sources_config",
    "sync_sources",
]
