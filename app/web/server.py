"""Flask web app that shows the published editions (TASK-044).

Read-only: every page is built from the `edition` rows written by
`app.pipeline.generate_edition`, and an edition page renders the composed
`Edition` stored in `edition.content` (TASK-043) -- the same structure the
PDF was rendered from -- without recomposing, re-sorting or regenerating
anything. No LLM call, no write to the database.

All text shown comes from web sources and LLM output, so it is untrusted
(CLAUDE.md §10-11): Jinja2 autoescaping stays on for every template, and a
citation URL becomes a link only when it is an absolute http(s) URL, the
same rule the PDF renderer applies.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, g, render_template, send_file
from flask.typing import ResponseReturnValue

from app.config.labels import Labels, load_labels
from app.database.connection import get_connection
from app.database.edition import EditionRecord
from app.database.edition_repository import EditionRepository
from app.database.migrations import run_migrations
from app.editorial.edition import Edition

_EDITION_NUMBER_LABEL: dict[str, str] = {"it": "Edizione n. {n}", "en": "Edition No. {n}"}
# Small page-chrome strings, kept here like the PDF renderer keeps its
# masthead strings (not an addition to config/labels.yaml).
_UI_TEXT: dict[str, dict[str, str]] = {
    "it": {
        "tagline": "Le notizie sull'intelligenza artificiale, verificate ogni giorno",
        "latest_edition": "Ultima edizione",
        "read_edition": "Leggi l'edizione",
        "archive": "Archivio",
        "no_editions": "Nessuna edizione pubblicata.",
        "all_editions": "Tutte le edizioni",
        "download_pdf": "PDF",
        "in_this_edition": "In questa edizione",
        "story": "notizia",
        "stories": "notizie",
        "source": "fonte",
        "sources": "fonti",
        "minutes": "min",
        "reading": "lettura",
        "briefing": "Il briefing di oggi",
        "no_content": "Il contenuto di questa edizione non è disponibile sul sito.",
    },
    "en": {
        "tagline": "Artificial intelligence news, verified every day",
        "latest_edition": "Latest edition",
        "read_edition": "Read the edition",
        "archive": "Archive",
        "no_editions": "No edition published yet.",
        "all_editions": "All editions",
        "download_pdf": "PDF",
        "in_this_edition": "In this edition",
        "story": "story",
        "stories": "stories",
        "source": "source",
        "sources": "sources",
        "minutes": "min",
        "reading": "reading",
        "briefing": "Today's briefing",
        "no_content": "This edition's content is not available on the site.",
    },
}
# Average silent reading speed used for the reading-time estimate.
_READING_WORDS_PER_MINUTE = 220

_MONTH_NAMES: dict[str, tuple[str, ...]] = {
    "it": (
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}


def create_app(database_url: str, language: str) -> Flask:
    """Build the web app for the database at `database_url`.

    `language` is the language of the edition list's page chrome
    (`Settings.default_language`); an edition page always uses its own
    edition's language.

    Pending migrations are applied once here, so a database created before
    TASK-043 gains the `edition.content` column instead of failing at the
    first query. Each request then opens its own connection: `sqlite3`
    connections cannot be shared across the server's threads.
    """
    connection = get_connection(database_url)
    try:
        run_migrations(connection)
    finally:
        connection.close()

    app = Flask(__name__)
    labels = load_labels()

    def repository() -> EditionRepository:
        if "connection" not in g:
            g.connection = get_connection(database_url)
        return EditionRepository(g.connection)

    @app.teardown_appcontext
    def _close_connection(_exc: BaseException | None) -> None:
        connection: sqlite3.Connection | None = g.pop("connection", None)
        if connection is not None:
            connection.close()

    @app.template_filter("domain")
    def _domain(url: str) -> str:
        return urlsplit(url).hostname or ""

    @app.template_filter("is_link")
    def _is_link(url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    @app.route("/")
    def index() -> ResponseReturnValue:
        editions = [
            {**_edition_heading(record), "headlines": _headlines(record)}
            for record in repository().list_published()
        ]
        return render_template(
            "index.html", editions=editions, ui=_UI_TEXT[language], page_language=language
        )

    @app.route("/editions/<int:edition_number>")
    def edition(edition_number: int) -> ResponseReturnValue:
        record = _published_edition(repository(), edition_number)
        content = _stored_edition(record)
        return render_template(
            "edition.html",
            heading=_edition_heading(record),
            edition=content,
            stats=_edition_stats(content) if content is not None else None,
            labels=_page_labels(labels, record.language),
            has_pdf=record.pdf_path is not None,
            ui=_UI_TEXT[record.language],
            page_language=record.language,
        )

    @app.route("/editions/<int:edition_number>/pdf")
    def edition_pdf(edition_number: int) -> ResponseReturnValue:
        record = _published_edition(repository(), edition_number)
        if record.pdf_path is None:
            abort(404)
        pdf_path = Path(record.pdf_path).resolve()
        if not pdf_path.is_file():
            abort(404)
        return send_file(pdf_path, mimetype="application/pdf")

    return app


def _published_edition(repository: EditionRepository, edition_number: int) -> EditionRecord:
    record = repository.get_by_number(edition_number)
    if record is None or record.status != "published":
        abort(404)
    return record


def _stored_edition(record: EditionRecord) -> Edition | None:
    """The composed edition saved at publication (TASK-043), or `None` if absent."""
    return Edition.model_validate_json(record.content) if record.content else None


def _edition_stats(edition: Edition) -> dict[str, int]:
    """Counts shown under the edition's headline: stories, sources, reading minutes."""
    stories = {story.event_id: story for story in edition.top_stories}
    for section in edition.sections:
        stories.update({story.event_id: story for story in section.entries})
    stories.update({story.event_id: story for story in edition.what_to_watch})
    sources = {article.url for story in stories.values() for article in story.articles}
    words = sum(len(story.summary.split()) for story in stories.values())
    return {
        "stories": len(stories),
        "sources": len(sources),
        "minutes": max(1, round(words / _READING_WORDS_PER_MINUTE)),
    }


def _headlines(record: EditionRecord) -> list[str]:
    """The titles shown for an edition in the archive: its Top Stories, in order."""
    edition = _stored_edition(record)
    return [story.title for story in edition.top_stories] if edition is not None else []


def _edition_heading(record: EditionRecord) -> dict[str, object]:
    """The masthead values of one edition: number, formatted date, language."""
    edition_date = date.fromisoformat(record.date)
    return {
        "number": record.edition_number,
        "language": record.language,
        "date": _format_edition_date(edition_date, record.language),
        "label": _EDITION_NUMBER_LABEL[record.language].format(n=record.edition_number),
    }


def _format_edition_date(edition_date: date, language: str) -> str:
    """Same date format as the PDF masthead (`app.newspaper.renderer`)."""
    month = _MONTH_NAMES[language][edition_date.month - 1]
    if language == "it":
        return f"{edition_date.day} {month} {edition_date.year}"
    return f"{month} {edition_date.day}, {edition_date.year}"


def _page_labels(labels: Labels, language: str) -> dict[str, str]:
    """Headings the edition page needs beyond the section labels `Edition` carries."""
    return {key: labels.get(key, language) for key in ("top_stories", "what_to_watch", "sources")}
