"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_article_page_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests off the network: article pages are never downloaded (TASK-031).

    Tests of the download itself call `app.collectors.article_text` directly with
    `requests.get` patched.
    """
    monkeypatch.setattr("app.pipeline.generation.fetch_article_text", lambda url: None)
