"""PDF rendering for the newspaper generator (TASK-021).

Turns an already-composed, editorially-final `Edition` (TASK-020) into a
complete PDF newspaper, entirely in memory. Pure and stateless (MODEL B,
consistent with every prior pipeline stage): no filesystem, database,
network or LLM access, and no mutation of `Edition` or any of its
components -- editorial selection, ordering, filtering and grouping are
already decided by `app.editorial.edition.assemble_edition` and are never
redone here (approved TASK-021 scope; the D-005 boundary recorded in
`app/editorial/edition.py` -- rendering is this module's job, not
editorial assembly's).

Explicitly out of scope (approved TASK-021 decisions): persistence,
CLI/pipeline orchestration, any `Research` section (no upstream model
produces one), and any visible `verification_status` indicator (the
wording already produced by earlier stages carries the required caution;
no badge, color or label is added here).

Source citations (TASK-022): `EditorialContent.articles` is rendered as a
per-story citation sub-block (`_build_citations_block`) -- one line per
article, in the order already given by `EditorialContent`, with no
deduplication or reordering. Only `source_name`, `published_at` (when not
`None`) and `url` are shown; `.title` and `.excerpt` are never rendered
(CLAUDE.md §18, docs/PRD.md §41 -- a citation is a factual reference, not
a repeated or quoted piece of AI-generated text). `url` and `source_name`
are untrusted, caller-supplied data (CLAUDE.md §10-11): an absolute
`http(s)` `url` is rendered as a ReportLab `<link>` hyperlink with its
`href` escaped via `xml.sax.saxutils.quoteattr`; any other `url` renders as
plain escaped text, never as a link, and never raises.

Layout: single-column A4 with uniform ~2cm margins (approved decision --
the PRD asks for a newspaper look, not a multi-column grid). Page 1 is the
masthead and Top Stories, followed by an explicit `PageBreak`; page 2
onward flows the category sections (in `Edition.sections`'s already-fixed
order) and What to Watch, using `Platypus`'s native pagination (no manual
page-breaking algorithm). AI SENZA SBATTI / Developer Impact sub-blocks are
distinguished purely by typography (a rounded, tinted callout box, see
`_build_callout`), not by new label text (approved decision -- their
semantic sub-headers are not this task's responsibility and
`config/labels.yaml` is not modified).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from xml.sax.saxutils import escape, quoteattr

from pydantic import BaseModel, ConfigDict, Field
from reportlab.pdfbase.pdfdoc import PDFError
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
)
from reportlab.platypus.doctemplate import LayoutError

from app.ai.concept_explainer import ConceptExplanation
from app.ai.developer_impact import DeveloperImpact
from app.ai.event_summarizer import ArticleContext
from app.config.labels import Labels, load_labels
from app.editorial.edition import Edition, EditionSection
from app.editorial.event_editorial import EditorialContent
from app.newspaper import styles
from app.newspaper.errors import NewspaperRenderError

# Only genuine ReportLab rendering/layout failures are wrapped into
# `NewspaperRenderError` (CLAUDE.md §19's provider-wrapping principle,
# applied to the rendering dependency). A bare `except Exception` would
# also swallow programming errors in this module's own flowable-building
# code, masking real bugs instead of failing tests -- deliberately avoided.
_RENDER_ERRORS = (LayoutError, PDFError)

# Small, masthead/footer-only static strings (approved decision -- not a
# new localization structure, not an addition to config/labels.yaml, which
# has no entries for edition numbering, dates or page numbers).
_EDITION_NUMBER_LABEL: dict[str, str] = {"it": "Edizione n. {n}", "en": "Edition No. {n}"}
_PAGE_LABEL: dict[str, str] = {"it": "Pagina {n}", "en": "Page {n}"}
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


class NewspaperMetadata(BaseModel):
    """Publication metadata the renderer needs but `Edition` does not carry.

    Deliberately not a field of `Edition`: edition numbering/dating is a
    publication-time concern, not editorial content (approved TASK-021
    decision) -- adding it to `Edition` would couple the editorial model
    to the renderer and was explicitly rejected.
    """

    model_config = ConfigDict(frozen=True)

    edition_number: int = Field(ge=1)
    edition_date: date


@lru_cache(maxsize=1)
def _section_labels() -> Labels:
    """Load `config/labels.yaml` once, memoized (mirrors `app.editorial.edition`)."""
    return load_labels()


def _escape(text: str) -> str:
    """Escape a plain string for safe embedding in a ReportLab `Paragraph`.

    `Paragraph` parses its input as a small XML-like markup language;
    generated text may legitimately contain `&`, `<` or `>` (e.g. "R&D"),
    which would otherwise break parsing or be misread as markup.
    """
    return escape(text)


def _format_edition_date(edition_date: date, language: str) -> str:
    month = _MONTH_NAMES[language][edition_date.month - 1]
    if language == "it":
        return f"{edition_date.day} {month} {edition_date.year}"
    return f"{month} {edition_date.day}, {edition_date.year}"


def _thin_rule() -> HRFlowable:
    """A short, muted rule used to visually separate citations from the summary/callout above."""
    return HRFlowable(
        width="25%",
        thickness=0.5,
        color=styles.MUTED_COLOR,
        spaceBefore=4,
        spaceAfter=4,
        hAlign="LEFT",
    )


def _build_section_heading(text: str) -> list[Flowable]:
    """A section heading rendered as a full-width colored band (modern styling pass).

    A single `Paragraph`: `SECTION_HEADING.backColor` already paints behind
    the whole available line width, not just the text, so no separate rule
    or `Table` is needed to get the band effect.
    """
    return [Paragraph(_escape(text), styles.SECTION_HEADING)]


def _build_masthead(edition: Edition, metadata: NewspaperMetadata) -> list[Flowable]:
    date_str = _format_edition_date(metadata.edition_date, edition.language)
    edition_label = _EDITION_NUMBER_LABEL[edition.language].format(n=metadata.edition_number)
    return [
        Paragraph("AI DAILY", styles.MASTHEAD_TITLE),
        Paragraph(_escape(f"{date_str} — {edition_label}"), styles.MASTHEAD_META),
    ]


def _build_callout(fields: list[str]) -> Paragraph:
    """One Developer Impact / AI Senza Sbatti callout box (modern styling pass).

    Every field is escaped and joined with `<br/>` into a single `Paragraph`
    styled with `styles.SUB_BLOCK_BODY` (rounded, tinted, bordered), so the
    whole sub-block renders as one cohesive card instead of a separate box
    per field. Deliberately not a `Table` -- see `app.newspaper.styles`
    module docstring for why (page-split safety).
    """
    return Paragraph("<br/>".join(_escape(field) for field in fields), styles.SUB_BLOCK_BODY)


def _build_developer_impact_block(developer_impact: DeveloperImpact) -> list[Flowable]:
    """Render the developer-impact sub-block, or nothing for a "no impact" result.

    `has_developer_impact = False` is a normal outcome (docs/PRD.md §43),
    not an error, and carries no `impact_summary` to show -- rendering
    nothing in that case is not omitting required content, it is the
    correct representation of "no real impact" (no content is invented).

    `breaking_change` is deliberately never rendered: no PRD/architecture
    decision defines a reader-facing format for it, and inventing one
    (a hardcoded, unlocalized "Yes"/"No") would not respect `Edition`'s
    language and is not this task's decision to make (CLAUDE.md §41 --
    prefer not inventing over guessing a presentation).
    """
    if not developer_impact.has_developer_impact or developer_impact.impact_summary is None:
        return []

    fields = [developer_impact.impact_summary]
    if developer_impact.technical_area:
        fields.append(", ".join(developer_impact.technical_area))
    return [_build_callout(fields)]


def _build_concept_explanation_block(explanation: ConceptExplanation) -> list[Flowable]:
    fields = [
        explanation.technical_definition,
        explanation.simple_explanation,
        explanation.example,
        explanation.why_it_matters,
        explanation.one_liner,
    ]
    return [_build_callout(fields)]


def _is_renderable_link(url: str) -> bool:
    """Return whether `url` is safe to render as a clickable hyperlink.

    Only an absolute `http`/`https` URL is linked; anything else (a
    relative path, another scheme, or malformed text) renders as plain
    text instead. `url` is untrusted, caller-supplied data (CLAUDE.md
    §10-11), so this check must never raise on any input string.
    """
    return url.startswith("http://") or url.startswith("https://")


def _build_citation_line(article: ArticleContext) -> str:
    """Format one article as a single citation line (TASK-022).

    Shows `source_name`, `published_at` (only when not `None`, exactly as
    supplied -- no date parsing or reformatting) and `url`. `.title` and
    `.excerpt` are never included (docs/PRD.md §41, CLAUDE.md §18).

    `source_name` and `url` are untrusted data: the visible text is
    escaped with `_escape`, and a renderable `url` is additionally wrapped
    in a ReportLab `<link>` tag whose `href` is escaped with `quoteattr`,
    so `&`, `"` or `<` in either value can never break Paragraph's markup
    parsing or inject new markup.
    """
    parts = [_escape(article.source_name)]
    if article.published_at is not None:
        parts.append(_escape(article.published_at))
    if _is_renderable_link(article.url):
        parts.append(f"<link href={quoteattr(article.url)}>{_escape(article.url)}</link>")
    else:
        parts.append(_escape(article.url))
    return "- " + " - ".join(parts)


def _build_citations_block(
    articles: tuple[ArticleContext, ...], language: str
) -> list[Flowable]:
    """Render the source citation sub-block: one line per article (TASK-022).

    Preserves `articles`' order exactly, with no deduplication, reordering
    or aggregation. Returns `[]` when `articles` is empty -- no heading
    with nothing under it, mirroring the Developer Impact / AI Senza
    Sbatti sub-blocks.
    """
    if not articles:
        return []
    heading = Paragraph(
        _escape(_section_labels().get("sources", language)), styles.CITATION_TEXT
    )
    lines = [
        Paragraph(_build_citation_line(article), styles.CITATION_TEXT) for article in articles
    ]
    return [_thin_rule(), heading, *lines]


def _build_story_block(content: EditorialContent) -> Flowable:
    """Render one event's title, summary and any optional sub-blocks.

    Wrapped in `KeepTogether` so a story's title is never separated from
    its own summary by a page break; `Platypus` degrades gracefully (lets
    the group flow across pages instead of raising) when a single story is
    too long to fit on one page, so long content remains supported.
    """
    blocks: list[Flowable] = [Paragraph(_escape(content.title), styles.STORY_TITLE)]
    # A complete summary has several paragraphs (TASK-031); one Paragraph per
    # line, because Platypus would fold the line breaks into spaces.
    blocks.extend(
        Paragraph(_escape(line), styles.BODY_TEXT)
        for line in content.summary.splitlines()
        if line.strip()
    )
    if content.developer_impact is not None:
        blocks.extend(_build_developer_impact_block(content.developer_impact))
    if content.concept_explanation is not None:
        blocks.extend(_build_concept_explanation_block(content.concept_explanation))
    blocks.extend(_build_citations_block(content.articles, content.language))
    return KeepTogether(blocks)


def _build_top_stories(edition: Edition) -> list[Flowable]:
    if not edition.top_stories:
        return []
    heading = _build_section_heading(_section_labels().get("top_stories", edition.language))
    return [*heading, *(_build_story_block(content) for content in edition.top_stories)]


def _build_section(section: EditionSection) -> list[Flowable]:
    """Render one category section, using `section.label` exactly as provided.

    Omitted entirely when `section.entries` is empty (approved decision):
    every one of the nine categories always exists on `Edition`, whether or
    not it has content, but an empty heading with nothing under it would
    add filler, not information.
    """
    if not section.entries:
        return []
    heading = _build_section_heading(section.label)
    return [*heading, *(_build_story_block(content) for content in section.entries)]


def _build_what_to_watch(edition: Edition) -> list[Flowable]:
    if not edition.what_to_watch:
        return []
    heading = _build_section_heading(_section_labels().get("what_to_watch", edition.language))
    return [*heading, *(_build_story_block(content) for content in edition.what_to_watch)]


def _build_story(edition: Edition, metadata: NewspaperMetadata) -> list[Flowable]:
    """Build the full flowable story in exactly `Edition`'s order.

    No re-sorting, re-filtering or re-grouping: `edition.top_stories`,
    `edition.sections` and `edition.what_to_watch` are iterated in the
    order `assemble_edition` already produced them.
    """
    story: list[Flowable] = []
    story.extend(_build_masthead(edition, metadata))
    story.extend(_build_top_stories(edition))
    story.append(PageBreak())
    for section in edition.sections:
        story.extend(_build_section(section))
    story.extend(_build_what_to_watch(edition))
    return story


def _make_footer_drawer(language: str) -> Callable[[Canvas, BaseDocTemplate], None]:
    label_template = _PAGE_LABEL[language]

    def _draw_footer(canvas: Canvas, document: BaseDocTemplate) -> None:
        canvas.saveState()
        page_width = styles.PAGE_SIZE[0]
        rule_y = styles.MARGIN / 2 + styles.FOOTER_TEXT.leading
        canvas.setStrokeColor(styles.MUTED_COLOR)
        canvas.setLineWidth(styles.RULE_THICKNESS)
        canvas.line(styles.MARGIN, rule_y, page_width - styles.MARGIN, rule_y)
        canvas.setFillColor(styles.FOOTER_TEXT.textColor)
        canvas.setFont(styles.FOOTER_TEXT.fontName, styles.FOOTER_TEXT.fontSize)
        text = label_template.format(n=canvas.getPageNumber())
        canvas.drawCentredString(page_width / 2, styles.MARGIN / 2, text)
        canvas.restoreState()

    return _draw_footer


def render_edition(edition: Edition, *, metadata: NewspaperMetadata) -> bytes:
    """Render `edition` to a complete PDF newspaper, entirely in memory.

    Pure and deterministic given `edition`/`metadata`: no filesystem,
    database, network or LLM access, and `edition` is never mutated.
    `Edition`'s Top Stories/section/What to Watch selection, ordering and
    grouping are treated as final and are never recomputed here.

    Args:
        edition: the already-composed, editorially-final edition to render.
        metadata: publication metadata (`edition_number`, `edition_date`)
            not carried by `Edition` itself.

    Returns:
        The rendered PDF as `bytes`.

    Raises:
        NewspaperRenderError: if ReportLab fails to lay out or produce the
            PDF document.
    """
    story = _build_story(edition, metadata)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=styles.PAGE_SIZE,
        leftMargin=styles.MARGIN,
        rightMargin=styles.MARGIN,
        topMargin=styles.MARGIN,
        bottomMargin=styles.MARGIN,
    )
    footer = _make_footer_drawer(edition.language)
    try:
        document.build(story, onFirstPage=footer, onLaterPages=footer)
    except _RENDER_ERRORS as exc:
        raise NewspaperRenderError(f"failed to render edition to PDF: {exc}") from exc
    return buffer.getvalue()
