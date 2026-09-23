"""Page geometry and typography constants for the newspaper renderer (TASK-021).

Pure data: page size, margins, `ParagraphStyle` definitions and rule
geometry. No flowable construction, no editorial logic, no knowledge of
`Edition`/`EditorialContent` -- `app/newspaper/renderer.py` is the only
module that turns these constants into an actual document.

Single-column A4 layout with uniform ~2cm margins (approved FASE 1/FASE 2
decision): the PRD requires a newspaper *look*, not a multi-column grid, and
a single column avoids the real complexity of balancing/flowing text across
`Frame`s for a requirement the PRD never asks for (CLAUDE.md §5).

Typography pairs Times-Roman/Times-Bold (serif, for the masthead title,
story titles and body copy) with Helvetica/Helvetica-Bold (sans, for
section-heading bands, the masthead date line, citations and the footer) --
both Base-14 fonts, so no font embedding is introduced. Base-14 WinAnsi
encoding covers the accented Latin characters used in Italian (à, è, é, ì,
ò, ù and their uppercase forms) -- verified empirically by
`tests/test_newspaper_renderer.py`'s Italian-accented-characters test, not
merely assumed.

Modern-styling pass: the masthead title and every section heading render as
a full-width colored band (`ParagraphStyle.backColor`, which paints behind
the whole available line width, not just the text), and the Developer
Impact / AI Senza Sbatti sub-blocks render as a single rounded, tinted
callout `Paragraph` (`backColor` + `borderColor` + `borderRadius`).
Deliberately implemented as `Paragraph` styling, not `reportlab.platypus.
Table` cells: a `Table` row that does not fit in the remaining page space
does not reliably split across pages and can raise `LayoutError`, whereas a
styled `Paragraph` keeps ReportLab's native, already-relied-upon line-level
splitting -- verified empirically (a callout box with ~100 lines of content
splits cleanly across pages; the equivalent single-row `Table` raised
`LayoutError` instead).
"""

from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

PAGE_SIZE = A4
MARGIN = 2 * cm

# Restrained masthead/newspaper palette (approved styling pass): a single
# accent color for bands/borders, a light tint of it for callout
# backgrounds, and a muted gray for secondary text (citations, footer).
# Body copy stays pure black for readability and print contrast -- CLAUDE.md
# §26 asks for a newspaper look, not a colorful one.
RULE_COLOR = HexColor("#000000")
ACCENT_COLOR = HexColor("#1B2A4A")
ACCENT_TINT = HexColor("#EEF1F6")
ON_ACCENT_COLOR = HexColor("#FFFFFF")
MUTED_COLOR = HexColor("#5A5A5A")
CALLOUT_TEXT_COLOR = HexColor("#33415C")
RULE_THICKNESS = 0.75

_BODY_FONT = "Times-Roman"
_BOLD_FONT = "Times-Bold"
_SANS_FONT = "Helvetica"
_SANS_BOLD_FONT = "Helvetica-Bold"

MASTHEAD_TITLE = ParagraphStyle(
    name="MastheadTitle",
    fontName=_BOLD_FONT,
    fontSize=30,
    leading=34,
    alignment=1,  # center
    textColor=ON_ACCENT_COLOR,
    backColor=ACCENT_COLOR,
    # types-reportlab declares borderPadding as float only; ReportLab
    # itself accepts a (top, right, bottom, left) tuple via normalizeTRBL.
    borderPadding=(14, 16, 12, 16),  # type: ignore[arg-type]
    # `Paragraph.wrap()` does not add borderPadding to the height it
    # reports to the frame (verified against ReportLab's own source): the
    # background/border is drawn on top of whatever comes next unless
    # spaceAfter alone (frame gaps take the max of adjacent spaceAfter/
    # spaceBefore, they do not add) is at least as large as the bottom
    # padding above, with room to spare.
    spaceAfter=16,
)

MASTHEAD_META = ParagraphStyle(
    name="MastheadMeta",
    fontName=_SANS_FONT,
    fontSize=10,
    leading=13,
    alignment=1,  # center
    spaceAfter=12,
    textColor=MUTED_COLOR,
)

SECTION_HEADING = ParagraphStyle(
    name="SectionHeading",
    fontName=_SANS_BOLD_FONT,
    fontSize=13,
    leading=16,
    spaceBefore=18,
    spaceAfter=12,
    textColor=ON_ACCENT_COLOR,
    backColor=ACCENT_COLOR,
    borderPadding=(7, 14, 7, 14),  # type: ignore[arg-type]
)

STORY_TITLE = ParagraphStyle(
    name="StoryTitle",
    fontName=_BOLD_FONT,
    fontSize=12,
    leading=15,
    spaceBefore=16,
    spaceAfter=4,
)

BODY_TEXT = ParagraphStyle(
    name="BodyText",
    fontName=_BODY_FONT,
    fontSize=10,
    leading=15,
    spaceAfter=6,
)

# Developer Impact / AI Senza Sbatti callout box: every field of one
# sub-block is joined into a single `Paragraph` (via `<br/>`, see
# `renderer._build_callout`) so the rounded/tinted background renders as one
# cohesive card instead of a separate box per field.
SUB_BLOCK_BODY = ParagraphStyle(
    name="SubBlockBody",
    fontName=_SANS_FONT,
    fontSize=9.5,
    leading=14,
    textColor=CALLOUT_TEXT_COLOR,
    backColor=ACCENT_TINT,
    borderColor=ACCENT_COLOR,
    borderWidth=0.75,
    borderRadius=4,
    borderPadding=10,
    # See MASTHEAD_TITLE's comment: both must clear borderPadding (10) with
    # room to spare, or the box's background/border bleeds into whatever
    # comes immediately before/after it.
    spaceBefore=15,
    spaceAfter=15,
)

CITATION_TEXT = ParagraphStyle(
    name="CitationText",
    fontName=_SANS_FONT,
    fontSize=8,
    leading=11,
    textColor=MUTED_COLOR,
    spaceAfter=1,
)

FOOTER_TEXT = ParagraphStyle(
    name="FooterText",
    fontName=_SANS_FONT,
    fontSize=8,
    leading=10,
    alignment=1,  # center
    textColor=MUTED_COLOR,
)
