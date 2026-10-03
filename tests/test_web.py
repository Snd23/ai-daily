"""Tests for the web app (TASK-044).

Each test publishes editions into a real, migrated SQLite file (the app opens
one connection per request, so an in-memory database would not be shared)
and reads the pages back through Flask's test client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from app.ai.developer_impact import DeveloperImpact
from app.ai.event_summarizer import ArticleContext
from app.database.connection import get_connection
from app.database.edition import EditionRecord
from app.database.edition_repository import EditionRepository
from app.database.migrations import run_migrations
from app.editorial.edition import Edition, EventForEdition, assemble_edition
from app.editorial.event_editorial import EditorialContent
from app.web import create_app


def _content(**overrides: Any) -> EditorialContent:
    values: dict[str, Any] = {
        "event_id": 1,
        "language": "en",
        "verification_status": "VERIFIED",
        "title": "OpenAI announces X",
        "summary": "First paragraph.\nSecond paragraph.",
        "developer_impact": None,
        "concept_explanation": None,
        "articles": (
            ArticleContext(
                source_name="Reuters",
                title="Source title",
                url="https://reuters.com/x",
                published_at="2026-09-16T08:00:00+00:00",
                excerpt="An excerpt that is never shown.",
            ),
        ),
    }
    values.update(overrides)
    return EditorialContent.model_validate(values)


def _edition(*contents: EditorialContent, language: str = "en") -> Edition:
    events = [
        EventForEdition(content=content, category="models_llm", importance_score=5.0)
        for content in contents
    ]
    return assemble_edition(language, events, 3)


class _Database:
    def __init__(self, path: Path) -> None:
        self.url = f"sqlite:///{path / 'ai_daily.db'}"
        self._dir = path
        connection = get_connection(self.url)
        run_migrations(connection)
        connection.close()

    def add(
        self,
        number: int,
        *,
        day: str = "2026-09-16",
        language: str = "en",
        edition: Edition | None = None,
        status: str = "published",
        pdf: bool = True,
    ) -> None:
        connection = get_connection(self.url)
        repository = EditionRepository(connection)
        record = repository.create(
            EditionRecord(
                edition_number=number,
                date=day,
                language=language,
                status="draft",
                created_at=f"{day}T07:00:00+02:00",
            )
        )
        assert record.id is not None
        if status == "published":
            pdf_path = self._dir / f"{day}-{language}.pdf"
            if pdf:
                pdf_path.write_bytes(b"%PDF-1.4 test")
            content = edition.model_dump_json() if edition is not None else None
            repository.publish(record.id, str(pdf_path), content or "")
            if content is None:
                connection.execute("UPDATE edition SET content = NULL WHERE id = ?", (record.id,))
                connection.commit()
        else:
            repository.update_status(record.id, "failed")
        connection.close()


@pytest.fixture
def database(tmp_path: Path) -> _Database:
    return _Database(tmp_path)


def _client(database: _Database, language: str = "it") -> FlaskClient:
    return create_app(database.url, language).test_client()


def test_index_lists_published_editions_newest_first(database: _Database) -> None:
    database.add(1, day="2026-09-15", edition=_edition(_content()))
    database.add(2, day="2026-09-16", edition=_edition(_content()))
    database.add(3, day="2026-09-17", status="failed")

    page = _client(database).get("/").get_data(as_text=True)

    assert "/editions/2" in page and "/editions/1" in page
    assert page.index("/editions/2") < page.index("/editions/1")
    assert "/editions/3" not in page


def test_index_without_editions_says_so(database: _Database) -> None:
    page = _client(database, "it").get("/").get_data(as_text=True)

    assert "Nessuna edizione pubblicata." in page


def test_edition_page_shows_the_stored_content(database: _Database) -> None:
    impact = DeveloperImpact(
        event_id=1,
        language="en",
        has_developer_impact=True,
        impact_summary="A new API endpoint.",
        technical_area=["API", "SDK"],
        breaking_change=False,
    )
    database.add(4, edition=_edition(_content(developer_impact=impact)))

    response = _client(database).get("/editions/4")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<html lang="en">' in page
    assert "September 16, 2026 — Edition No. 4" in page
    assert "TOP STORIES" in page and "MODELS &amp; LLMs" in page
    assert "<p>First paragraph.</p>" in page and "<p>Second paragraph.</p>" in page
    assert "A new API endpoint." in page and "API, SDK" in page
    assert '<a href="https://reuters.com/x"' in page
    assert "An excerpt that is never shown." not in page
    assert "/editions/4/pdf" in page


def test_untrusted_text_is_escaped_and_unsafe_urls_are_not_linked(database: _Database) -> None:
    hostile = _content(
        title="<script>alert(1)</script>",
        articles=(
            ArticleContext(
                source_name="Evil",
                title="t",
                url="javascript:alert(1)",
                published_at=None,
                excerpt="e",
            ),
        ),
    )
    database.add(5, edition=_edition(hostile))

    page = _client(database).get("/editions/5").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert 'href="javascript:' not in page


def test_an_edition_published_before_content_was_stored_links_only_the_pdf(
    database: _Database,
) -> None:
    database.add(6, language="it", edition=None)

    page = _client(database).get("/editions/6").get_data(as_text=True)

    assert "Il contenuto di questa edizione non è disponibile sul sito." in page
    assert "/editions/6/pdf" in page


def test_pdf_is_served(database: _Database) -> None:
    database.add(7, edition=_edition(_content()))

    response = _client(database).get("/editions/7/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data == b"%PDF-1.4 test"
    response.close()


def test_missing_pdf_file_is_not_found(database: _Database) -> None:
    database.add(8, edition=_edition(_content()), pdf=False)

    assert _client(database).get("/editions/8/pdf").status_code == 404


@pytest.mark.parametrize("number", [99, 9])
def test_unknown_or_unpublished_editions_are_not_found(
    database: _Database, number: int
) -> None:
    database.add(9, status="failed")

    assert _client(database).get(f"/editions/{number}").status_code == 404
    assert _client(database).get(f"/editions/{number}/pdf").status_code == 404
