"""Smoke tests for the project bootstrap (TASK-001).

These only verify that the `app` package is installable and importable.
Functional tests for individual pipeline stages will be added by the tasks
that implement them (see TODO.md).
"""

import app


def test_app_package_is_importable() -> None:
    assert app.__name__ == "app"


def test_app_has_a_version() -> None:
    assert isinstance(app.__version__, str)
    assert app.__version__ != ""
