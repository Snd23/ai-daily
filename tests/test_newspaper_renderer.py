"""Tests for `app.newspaper.renderer` (TASK-021).

Structural/behavioral tests, not byte-for-byte golden PDFs (ReportLab
embeds a build-time `/CreationDate` in every PDF, so byte comparison is
non-deterministic even for identical input). Every test parses the
rendered PDF back with `pypdf` and asserts on page count / extracted text,
never on raw bytes beyond the `%PDF-` header check.

No network, no database, no filesystem and no LLM: every fixture is an
in-memory `Edition`/`EditorialContent` built the same way TASK-020's own
tests build them, via `assemble_edition`.
"""

from __future__ import annotations

import io
from datetime import date
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from pypdf import PdfReader
from reportlab.platypus import Paragraph
from reportlab.platypus.doctemplate import LayoutError

from app.ai.concept_explainer import ConceptExplanation
from app.ai.developer_impact import DeveloperImpact
from app.ai.event_summarizer import ArticleContext
from app.config.labels import load_labels
from app.editorial.edition import Edition, EventForEdition, assemble_edition
from app.editorial.event_editorial import EditorialContent
from app.newspaper import NewspaperMetadata, NewspaperRenderError, render_edition
from app.newspaper import renderer as renderer_module

_LABELS = load_labels()


def _article(**overrides: object) -> ArticleContext:
    values: dict[str, object] = {
        "source_name": "Reuters",
        "title": "Source title",
        "url": "https://example.com/article",
        "published_at": None,
        "excerpt": "An excerpt.",
    }
    values.update(overrides)
    return ArticleContext.model_validate(values)


def _content(**overrides: object) -> EditorialContent:
    values: dict[str, object] = {
        "event_id": 1,
        "language": "en",
        "verification_status": "VERIFIED",
        "title": "OpenAI announces X",
        "summary": "OpenAI announced X on Monday.",
        "developer_impact": None,
        "concept_explanation": None,
        "articles": (_article(),),
    }
    values.update(overrides)
    return EditorialContent.model_validate(values)


def _event(**overrides: object) -> EventForEdition:
    values: dict[str, object] = {
        "content": _content(),
        "category": "models_llm",
        "importance_score": 5.0,
        "future_date": None,
    }
    values.update(overrides)
    return EventForEdition.model_validate(values)


def _developer_impact(**overrides: object) -> DeveloperImpact:
    values: dict[str, object] = {
        "event_id": 1,
        "language": "en",
        "has_developer_impact": True,
        "impact_summary": "A new API endpoint is now available for developers.",
        "technical_area": ["API", "SDK"],
        "breaking_change": False,
    }
    values.update(overrides)
    return DeveloperImpact.model_validate(values)


def _concept_explanation(**overrides: object) -> ConceptExplanation:
    values: dict[str, object] = {
        "concept_slug": "rag",
        "language": "en",
        "event_id": 1,
        "technical_definition": "RAG combines retrieval with generation.",
        "simple_explanation": "It is like checking a book before answering.",
        "example": "A chatbot that consults a manual before replying.",
        "why_it_matters": "It reduces hallucinations.",
        "one_liner": "Look it up, then answer.",
    }
    values.update(overrides)
    return ConceptExplanation.model_validate(values)


def _metadata(**overrides: object) -> NewspaperMetadata:
    values: dict[str, object] = {"edition_number": 1, "edition_date": date(2026, 9, 15)}
    values.update(overrides)
    return NewspaperMetadata.model_validate(values)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def _empty_edition(language: str = "en") -> Edition:
    return assemble_edition(language=language, events=[], max_top_stories=5)


# --- basic PDF validity -----------------------------------------------------------------


def test_render_edition_returns_non_empty_bytes() -> None:
    result = render_edition(_empty_edition(), metadata=_metadata())

    assert isinstance(result, bytes)
    assert len(result) > 0


def test_render_edition_output_starts_with_pdf_header() -> None:
    result = render_edition(_empty_edition(), metadata=_metadata())

    assert result.startswith(b"%PDF-")


def test_render_edition_output_is_parseable() -> None:
    result = render_edition(_empty_edition(), metadata=_metadata())

    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) >= 1


def test_render_edition_does_not_mutate_edition() -> None:
    edition = assemble_edition(language="en", events=[_event()], max_top_stories=5)
    top_stories_before = edition.top_stories
    sections_before = edition.sections

    render_edition(edition, metadata=_metadata())

    assert edition.top_stories == top_stories_before
    assert edition.sections == sections_before


# --- masthead ----------------------------------------------------------------------------


def test_render_edition_includes_masthead_title() -> None:
    result = render_edition(_empty_edition(), metadata=_metadata())

    assert "AI DAILY" in _extract_text(result)


def test_render_edition_includes_edition_date_english() -> None:
    metadata = _metadata(edition_date=date(2026, 9, 15))

    text = _extract_text(render_edition(_empty_edition("en"), metadata=metadata))

    assert "September 15, 2026" in text


def test_render_edition_includes_edition_date_italian() -> None:
    metadata = _metadata(edition_date=date(2026, 9, 15))

    text = _extract_text(render_edition(_empty_edition("it"), metadata=metadata))

    assert "15 settembre 2026" in text


def test_render_edition_includes_edition_number_english() -> None:
    metadata = _metadata(edition_number=42)

    text = _extract_text(render_edition(_empty_edition("en"), metadata=metadata))

    assert "Edition No. 42" in text


def test_render_edition_includes_edition_number_italian() -> None:
    metadata = _metadata(edition_number=42)

    text = _extract_text(render_edition(_empty_edition("it"), metadata=metadata))

    assert "Edizione n. 42" in text


# --- Top Stories, sections, What to Watch -----------------------------------------------


def test_render_edition_includes_top_stories_heading_and_titles() -> None:
    event = _event(content=_content(title="A very important story"))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("top_stories", "en") in text
    assert "A very important story" in text


def test_render_edition_section_order_matches_edition_sections_order() -> None:
    events = [
        _event(
            content=_content(event_id=1, title="Startups story"),
            category="startups",
            importance_score=1.0,
        ),
        _event(
            content=_content(event_id=2, title="Models story"),
            category="models_llm",
            importance_score=1.0,
        ),
        _event(
            content=_content(event_id=3, title="Research story"),
            category="ai_research",
            importance_score=1.0,
        ),
    ]
    # UNVERIFIED so none qualify for Top Stories -- isolates section ordering.
    events = [
        _event(
            content=e.content.model_copy(update={"verification_status": "UNVERIFIED"}),
            category=e.category,
            importance_score=e.importance_score,
        )
        for e in events
    ]
    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    models_pos = text.index("Models story")
    research_pos = text.index("Research story")
    startups_pos = text.index("Startups story")
    # Canonical order (app.editorial.edition._EDITORIAL_CATEGORIES):
    # models_llm, ..., ai_research, ..., startups.
    assert models_pos < research_pos < startups_pos


def test_render_edition_omits_empty_sections() -> None:
    event = _event(category="models_llm", content=_content(title="Only models story"))
    # max_top_stories=0 keeps the event in its section (a Top Story is not repeated there).
    edition = assemble_edition(language="en", events=[event], max_top_stories=0)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("models_llm", "en") in text
    assert _LABELS.get("robotics", "en") not in text
    assert _LABELS.get("startups", "en") not in text


def test_render_edition_includes_what_to_watch() -> None:
    event = _event(
        content=_content(title="A future launch"),
        future_date="2026-12-01",
    )
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("what_to_watch", "en") in text
    assert "A future launch" in text


def test_render_edition_omits_what_to_watch_when_empty() -> None:
    edition = _empty_edition("en")

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("what_to_watch", "en") not in text


# --- Developer Impact / Concept Explanation ----------------------------------------------


def test_render_edition_renders_developer_impact_when_present() -> None:
    impact = _developer_impact(
        impact_summary="Ships a new tool-calling API.",
        technical_area=["Tool Calling", "Agents"],
        breaking_change=True,
    )
    event = _event(content=_content(developer_impact=impact))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "Ships a new tool-calling API." in text
    assert "Tool Calling, Agents" in text


def test_render_edition_never_renders_breaking_change_text_english() -> None:
    """`breaking_change` must never produce reader-facing text (FASE-2 finding).

    The masthead's approved "Edition No. {n}" label itself contains the
    substring "No", so a bare `"No" not in text` check would false-positive
    on unrelated, already-approved masthead content. Instead, an edition
    without any `developer_impact` is used as a baseline, and the "Yes"/"No"
    occurrence counts with vs. without `developer_impact` are compared:
    rendering `breaking_change` must not add a single extra occurrence.
    """
    baseline_edition = assemble_edition(
        language="en", events=[_event(content=_content(developer_impact=None))], max_top_stories=5
    )
    baseline_text = _extract_text(render_edition(baseline_edition, metadata=_metadata()))

    impact = _developer_impact(
        impact_summary="Ships a new tool-calling API.",
        technical_area=["Tool Calling", "Agents"],
        breaking_change=True,
    )
    edition = assemble_edition(
        language="en",
        events=[_event(content=_content(developer_impact=impact))],
        max_top_stories=5,
    )
    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "Ships a new tool-calling API." in text
    assert "Tool Calling, Agents" in text
    assert "Breaking change" not in text
    assert text.count("Yes") == baseline_text.count("Yes") == 0
    assert text.count("No") == baseline_text.count("No")


def test_render_edition_never_renders_breaking_change_text_italian() -> None:
    """Regression test for the FASE-2 finding: `breaking_change` must never
    produce reader-facing text, in any language -- no PRD/architecture
    decision defines a format for it, and a hardcoded English "Yes"/"No"
    would not respect `Edition.language` (docs/PRD.md §38)."""
    impact = _developer_impact(
        language="it",
        impact_summary="Disponibile una nuova API per il tool calling.",
        technical_area=["Tool Calling", "Agenti"],
        breaking_change=True,
    )
    event = _event(
        content=_content(
            language="it",
            title="Nuova API disponibile",
            summary="La nuova API è ora disponibile per gli sviluppatori.",
            developer_impact=impact,
        )
    )
    edition = assemble_edition(language="it", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "Disponibile una nuova API per il tool calling." in text
    assert "Tool Calling, Agenti" in text
    assert "Yes" not in text
    assert "No" not in text
    assert "Sì" not in text
    assert "Breaking change" not in text
    assert "Modifica sostanziale" not in text


def test_render_edition_omits_developer_impact_block_when_no_impact() -> None:
    impact = _developer_impact(
        has_developer_impact=False,
        impact_summary=None,
        technical_area=None,
        breaking_change=None,
    )
    event = _event(content=_content(developer_impact=impact))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    result = render_edition(edition, metadata=_metadata())

    assert result.startswith(b"%PDF-")


def test_render_edition_renders_concept_explanation_when_present() -> None:
    explanation = _concept_explanation()
    event = _event(content=_content(concept_explanation=explanation))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "RAG combines retrieval with generation." in text
    assert "It is like checking a book before answering." in text
    assert "A chatbot that consults a manual before replying." in text
    assert "It reduces hallucinations." in text
    assert "Look it up, then answer." in text


def test_render_edition_omits_concept_explanation_when_none() -> None:
    event = _event(content=_content(concept_explanation=None))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "checking a book" not in text


def test_render_edition_renders_source_citations() -> None:
    article = _article(source_name="A Very Unique Publisher Name", url="https://unique.example")
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "A Very Unique Publisher Name" in text
    assert "unique.example" in text


def test_render_edition_renders_citation_for_every_article() -> None:
    articles = (
        _article(source_name="Reuters", url="https://example.com/1"),
        _article(source_name="TechCrunch", url="https://example.com/2"),
        _article(source_name="The Verge", url="https://example.com/3"),
    )
    event = _event(content=_content(articles=articles))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "Reuters" in text
    assert "example.com/1" in text
    assert "TechCrunch" in text
    assert "example.com/2" in text
    assert "The Verge" in text
    assert "example.com/3" in text


def test_render_edition_preserves_citation_order() -> None:
    articles = (
        _article(source_name="First Publisher", url="https://example.com/first"),
        _article(source_name="Second Publisher", url="https://example.com/second"),
        _article(source_name="Third Publisher", url="https://example.com/third"),
    )
    event = _event(content=_content(articles=articles))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    first_pos = text.index("First Publisher")
    second_pos = text.index("Second Publisher")
    third_pos = text.index("Third Publisher")
    assert first_pos < second_pos < third_pos


def test_render_edition_does_not_deduplicate_citations() -> None:
    articles = (
        _article(source_name="Same Publisher", url="https://example.com/article-a"),
        _article(source_name="Same Publisher", url="https://example.com/article-b"),
    )
    event = _event(content=_content(articles=articles))
    # max_top_stories=0 keeps the event out of Top Stories, so it (and its
    # citations) is rendered exactly once, in its category section only --
    # Top Stories and category sections are non-exclusive views over the
    # same events (app.editorial.edition.assemble_edition), unrelated to
    # citation rendering; this isolates the dedup assertion from that.
    edition = assemble_edition(language="en", events=[event], max_top_stories=0)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert text.count("Same Publisher") == 2
    assert "example.com/article-a" in text
    assert "example.com/article-b" in text


def _extract_link_uris(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    uris: list[str] = []
    for page in reader.pages:
        annotations = page.get("/Annots")
        if not annotations:
            continue
        for annot_ref in annotations:
            annotation = annot_ref.get_object()
            action = annotation.get("/A")
            if action and "/URI" in action:
                uris.append(str(action["/URI"]))
    return uris


def test_render_edition_hyperlinks_http_url() -> None:
    article = _article(url="https://example.com/hyperlinked-story")
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    result = render_edition(edition, metadata=_metadata())

    assert "https://example.com/hyperlinked-story" in _extract_link_uris(result)


def test_render_edition_uses_plain_text_for_non_http_url() -> None:
    article = _article(url="ftp://example.com/not-a-web-link")
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    result = render_edition(edition, metadata=_metadata())
    text = _extract_text(result)

    assert "ftp://example.com/not-a-web-link" in text
    assert _extract_link_uris(result) == []


def test_render_edition_escapes_special_characters_in_url() -> None:
    url = 'https://example.com/x?a=1&b="q"<tag>'
    article = _article(url=url)
    event = _event(content=_content(articles=(article,)))
    # max_top_stories=0 keeps the event out of Top Stories, so it (and its
    # citation annotation) is rendered exactly once, in its category
    # section only -- see test_render_edition_does_not_deduplicate_citations
    # for why this is needed (Top Stories and category sections are
    # non-exclusive views over the same events).
    edition = assemble_edition(language="en", events=[event], max_top_stories=0)

    result = render_edition(edition, metadata=_metadata())
    text = _extract_text(result)

    # No exception was raised getting here, and the PDF is well-formed
    # (parseable by pypdf below, in both _extract_text and
    # _extract_link_uris) -- markup injection would have broken one of
    # these, not merely left a character out of the visible text.
    assert result.startswith(b"%PDF-")
    assert "&" in text
    assert '"' in text
    assert "<" in text

    # The href actually carried by the PDF's /URI annotation must be the
    # exact, unmangled original URL -- proving `quoteattr` escaped the
    # attribute correctly (round-trip), not merely that the visible text
    # happens to contain the right characters somewhere.
    assert _extract_link_uris(result) == [url]


def test_render_edition_renders_sources_heading_english() -> None:
    event = _event(content=_content())
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("sources", "en") in text


def test_render_edition_renders_sources_heading_italian() -> None:
    content = _content(
        language="it",
        title="Titolo",
        summary="Riassunto.",
    )
    event = _event(content=content)
    edition = assemble_edition(language="it", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("sources", "it") in text


def test_render_edition_omits_citations_when_no_articles() -> None:
    event = _event(content=_content(articles=()))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert _LABELS.get("sources", "en") not in text


def test_render_edition_shows_published_at_when_present() -> None:
    article = _article(published_at="2026-09-14T10:00:00Z")
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "2026-09-14T10:00:00Z" in text


def test_render_edition_omits_published_at_when_none() -> None:
    article = _article(published_at=None)
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "None" not in text


def test_render_edition_never_renders_article_excerpt() -> None:
    article = _article(excerpt="A Very Unique Excerpt That Must Never Be Shown To Readers")
    event = _event(content=_content(articles=(article,)))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "A Very Unique Excerpt That Must Never Be Shown To Readers" not in text


def test_render_edition_places_citations_after_summary_and_subblocks() -> None:
    article = _article(source_name="A Very Unique Trailing Citation Publisher")
    content = _content(
        summary="A very unique summary sentence for ordering.",
        developer_impact=_developer_impact(
            impact_summary="A very unique developer impact sentence."
        ),
        concept_explanation=_concept_explanation(
            simple_explanation="A very unique concept explanation sentence."
        ),
        articles=(article,),
    )
    event = _event(content=content)
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    summary_pos = text.index("A very unique summary sentence for ordering.")
    developer_impact_pos = text.index("A very unique developer impact sentence.")
    concept_explanation_pos = text.index("A very unique concept explanation sentence.")
    citation_pos = text.index("A Very Unique Trailing Citation Publisher")
    assert summary_pos < developer_impact_pos < concept_explanation_pos < citation_pos


def test_a_multi_paragraph_summary_is_rendered_as_separate_paragraphs() -> None:
    content = _content(summary="First paragraph.\n\nSecond paragraph.\nThird paragraph.")

    block = renderer_module._build_story_block(content)

    paragraphs = [f for f in block._content if isinstance(f, Paragraph)]  # type: ignore[attr-defined]
    body = [p.getPlainText() for p in paragraphs if p.style.name == "BodyText"]
    assert body == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]


def test_render_edition_never_renders_verification_status_text() -> None:
    event = _event(content=_content(verification_status="UNVERIFIED"))
    edition = assemble_edition(language="en", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "UNVERIFIED" not in text
    assert "VERIFIED" not in text


# --- Unicode -------------------------------------------------------------------------------


def test_render_edition_renders_italian_accented_characters() -> None:
    content = _content(
        language="it",
        title="Società italiana lancia città intelligente",
        summary="Àbc èlite ìdrico òpera ùnica, perché è così, con SOCIETÀ e CITTÀ e È maiuscola.",
    )
    event = _event(content=content)
    edition = assemble_edition(language="it", events=[event], max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    for character in ("à", "è", "é", "ì", "ò", "ù", "À", "È"):
        assert character in text
    assert "Società" in text
    assert "città" in text


# --- pagination / footer ------------------------------------------------------------------


def test_render_edition_produces_at_least_two_pages_for_a_non_empty_edition() -> None:
    events = [_event(), _event(content=_content(event_id=2, title="Second story"))]
    edition = assemble_edition(language="en", events=events, max_top_stories=1)

    result = render_edition(edition, metadata=_metadata())

    # Structural page break: Top Stories -> category sections (the second story is
    # not a Top Story, so its section exists).
    assert _page_count(result) >= 2


def test_render_edition_handles_minimal_empty_edition() -> None:
    result = render_edition(_empty_edition(), metadata=_metadata())

    assert result.startswith(b"%PDF-")
    assert _page_count(result) >= 1


def test_render_edition_handles_long_content_across_many_pages() -> None:
    long_summary = " ".join(["This is a long generated summary sentence."] * 200)
    categories = (
        "models_llm",
        "big_tech_business",
        "ai_research",
        "ai_developers",
        "robotics",
        "regulation",
        "society",
        "hardware",
        "startups",
    )
    events = [
        _event(
            content=_content(event_id=i, title=f"Long story number {i}", summary=long_summary),
            category=categories[i % len(categories)],
            importance_score=float(i % 10),
        )
        for i in range(40)
    ]
    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    result = render_edition(edition, metadata=_metadata())

    assert result.startswith(b"%PDF-")
    assert _page_count(result) > 3


def test_render_edition_includes_page_number_footer() -> None:
    long_summary = " ".join(["Filler sentence for pagination."] * 300)
    events = [
        _event(content=_content(event_id=i, title=f"Story {i}", summary=long_summary))
        for i in range(10)
    ]
    edition = assemble_edition(language="en", events=events, max_top_stories=5)

    text = _extract_text(render_edition(edition, metadata=_metadata()))

    assert "Page 1" in text
    assert "Page 2" in text


# --- error handling ------------------------------------------------------------------------


def test_render_edition_wraps_reportlab_layout_errors() -> None:
    edition = _empty_edition()

    with patch(
        "app.newspaper.renderer.SimpleDocTemplate.build",
        side_effect=LayoutError("simulated layout failure"),
    ):
        with pytest.raises(NewspaperRenderError) as exc_info:
            render_edition(edition, metadata=_metadata())

    assert isinstance(exc_info.value.__cause__, LayoutError)


# --- NewspaperMetadata -----------------------------------------------------------------------


def test_newspaper_metadata_accepts_valid_values() -> None:
    metadata = _metadata(edition_number=3, edition_date=date(2026, 1, 1))

    assert metadata.edition_number == 3
    assert metadata.edition_date == date(2026, 1, 1)


def test_newspaper_metadata_is_frozen() -> None:
    metadata = _metadata()

    with pytest.raises(ValidationError):
        metadata.edition_number = 99  # type: ignore[misc]


def test_newspaper_metadata_rejects_edition_number_below_one() -> None:
    with pytest.raises(ValidationError):
        _metadata(edition_number=0)
