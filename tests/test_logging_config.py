"""Tests for app.logging_config (TASK-003).

Covers: default/explicit log level filtering, idempotent configuration,
timestamps rendered in the application timezone (Europe/Rome) regardless of
the host machine's own timezone, and that errors keep their traceback.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config.settings import APP_TIMEZONE
from app.logging_config import LOG_DATE_FORMAT, AppTimezoneFormatter, configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """Prevent test pollution of the process-wide root logger."""
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    yield

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def test_default_level_is_info(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logger = logging.getLogger("test.logging_config.default")

    logger.debug("debug hidden")
    logger.info("info shown")

    captured = capsys.readouterr()
    assert "debug hidden" not in captured.out
    assert "info shown" in captured.out


def test_explicit_level_filters_lower_severity_messages(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level=logging.WARNING)
    logger = logging.getLogger("test.logging_config.warning")

    logger.info("should not appear")
    logger.warning("should appear")

    captured = capsys.readouterr()
    assert "should not appear" not in captured.out
    assert "should appear" in captured.out


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    configure_logging()

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 1

    logger = logging.getLogger("test.logging_config.idempotent")
    logger.info("single line")

    captured = capsys.readouterr()
    assert captured.out.count("single line") == 1


def test_log_output_timestamp_matches_app_timezone(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logger = logging.getLogger("test.logging_config.timezone")

    logger.info("timestamped message")

    captured = capsys.readouterr()
    line = next(line for line in captured.out.splitlines() if "timestamped message" in line)
    timestamp_str = " ".join(line.split(" ")[:2])
    parsed = datetime.strptime(timestamp_str, LOG_DATE_FORMAT).replace(tzinfo=APP_TIMEZONE)

    now_in_rome = datetime.now(tz=APP_TIMEZONE)
    assert abs((parsed - now_in_rome).total_seconds()) < 5


def test_error_log_includes_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logger = logging.getLogger("test.logging_config.error")

    try:
        raise ValueError("boom")
    except ValueError:
        logger.error("failed", exc_info=True)

    captured = capsys.readouterr()
    assert "ERROR" in captured.out
    assert "ValueError: boom" in captured.out
    assert "Traceback" in captured.out


def test_formatter_renders_known_timestamp_in_app_timezone() -> None:
    formatter = AppTimezoneFormatter(fmt="%(message)s", datefmt=LOG_DATE_FORMAT)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    # A known instant with no DST ambiguity: Europe/Rome is UTC+1 (CET) in January.
    known_instant = datetime(2026, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    record.created = known_instant.timestamp()

    formatted = formatter.formatTime(record, LOG_DATE_FORMAT)

    assert formatted == "2026-01-15 13:00:00"
