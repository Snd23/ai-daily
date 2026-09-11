"""Application logging configuration.

Configures the root logger with a single stdout handler whose timestamps
are always rendered in the fixed application timezone (`Europe/Rome`, see
docs/ARCHITECTURE.md §9), regardless of the host machine's own local
timezone.

This module only sets up *how* logs look; it does not decide *when* to log
retries or how the pipeline should continue after a partial failure (PRD
§24, CLAUDE.md §33-34) — that belongs to the collectors and pipeline
orchestration that will actually produce those log lines.

Once `configure_logging()` has run, other modules obtain a logger the
standard way:

    logger = logging.getLogger(__name__)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from app.config.settings import APP_TIMEZONE

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class AppTimezoneFormatter(logging.Formatter):
    """Log formatter that renders timestamps in the application timezone."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, tz=APP_TIMEZONE)
        return moment.strftime(datefmt or LOG_DATE_FORMAT)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure the root logger for the application.

    Attaches a single stdout handler formatted with `AppTimezoneFormatter`.
    Idempotent: safe to call more than once (e.g. across tests) without
    accumulating duplicate handlers or duplicate log output.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(AppTimezoneFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root_logger.addHandler(handler)
