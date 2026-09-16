"""Page geometry and typography constants for the newspaper renderer (TASK-021).

Pure data: page size, margins, `ParagraphStyle` definitions and rule
geometry. No flowable construction, no editorial logic, no knowledge of
`Edition`/`EditorialContent` -- `app/newspaper/renderer.py` is the only
module that turns these constants into an actual document.

Single-column A4 layout with uniform ~2cm margins (approved FASE 1/FASE 2
decision): the PRD requires a newspaper *look*, not a multi-column grid, and
a single column avoids the real complexity of balancing/flowing text across
`Frame`s for a requirement the PRD never asks for (CLAUDE.md §5).

Typography uses the Times-Roman/Times-Bold Base-14 fonts for a serif
newspaper feel (approved decision); Base-14 WinAnsi encoding covers the
accented Latin characters used in Italian (à, è, é, ì, ò, ù and their
uppercase forms) -- verified empirically by
`tests/test_newspaper_renderer.py`'s Italian-accented-characters test, not
merely assumed.
"""

from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

PAGE_SIZE = A4
MARGIN = 2 * cm

RULE_COLOR = HexColor("#000000")
RULE_THICKNESS = 0.75

_BODY_FONT = "Times-Roman"
_BOLD_FONT = "Times-Bold"
_ITALIC_FONT = "Times-Italic"

MASTHEAD_TITLE = ParagraphStyle(
    name="MastheadTitle",
    fontName=_BOLD_FONT,
    fontSize=28,
    leading=32,
    alignment=1,  # center
    spaceAfter=4,
)

MASTHEAD_META = ParagraphStyle(
    name="MastheadMeta",
    fontName=_BODY_FONT,
    fontSize=10,
    leading=13,
    alignment=1,  # center
    spaceAfter=2,
)

SECTION_HEADING = ParagraphStyle(
    name="SectionHeading",
    fontName=_BOLD_FONT,
    fontSize=16,
    leading=20,
    spaceBefore=14,
    spaceAfter=8,
)

STORY_TITLE = ParagraphStyle(
    name="StoryTitle",
    fontName=_BOLD_FONT,
    fontSize=12,
    leading=15,
    spaceBefore=10,
    spaceAfter=4,
)

BODY_TEXT = ParagraphStyle(
    name="BodyText",
    fontName=_BODY_FONT,
    fontSize=10,
    leading=14,
    spaceAfter=4,
)

SUB_BLOCK_BODY = ParagraphStyle(
    name="SubBlockBody",
    fontName=_ITALIC_FONT,
    fontSize=9.5,
    leading=13,
    leftIndent=12,
    spaceAfter=2,
)

CITATION_TEXT = ParagraphStyle(
    name="CitationText",
    fontName=_BODY_FONT,
    fontSize=8.5,
    leading=11,
    leftIndent=12,
    spaceAfter=1,
)

FOOTER_TEXT = ParagraphStyle(
    name="FooterText",
    fontName=_BODY_FONT,
    fontSize=8,
    leading=10,
    alignment=1,  # center
)
