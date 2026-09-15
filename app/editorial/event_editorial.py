"""Editorial content assembly (TASK-019): EDITORIAL ASSEMBLY (partial).

Aggregates already-generated, caller-supplied outputs for one event in one
language into a single immutable `EditorialContent`. Pure and in-memory
(MODEL B, approved TASK-019 decision D-001): no database access, no
`Event`/`EventContent`/`Edition` persistence, no `LLMProvider` call
(approved decision D-002 -- this is a deterministic assembly stage, not a
generation stage).

Out of scope (approved TASK-019 decisions D-003/D-004 and FASE 1 spec):
CLASSIFY, category assignment, Top Stories selection, ranking/importance
scoring, concept selection, hedging detection, and citation formatting
(`ArticleContext` is preserved verbatim, never turned into a
`SourceCitation`/`{name, url}`-shaped model -- that belongs to TASK-022).

`assemble_editorial_content` does not rewrite, summarize, translate or
otherwise transform `EventSummary`/`DeveloperImpact`/`ConceptExplanation`
content: it only validates that the supplied `event_id`/`language` are
consistent across every component and copies the relevant fields into one
container. `VerificationResult` (`app.verification.event_verifier`) carries
no `event_id` (MODEL B: no `Event` exists yet at VERIFY time), so no
`event_id` consistency check is performed against it -- only its
`verification_status` is copied through.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from app.ai.concept_explainer import ConceptExplanation
from app.ai.developer_impact import DeveloperImpact
from app.ai.event_summarizer import ArticleContext, EventSummary
from app.config.settings import SUPPORTED_LANGUAGES
from app.database.event import VerificationStatus
from app.verification.event_verifier import VerificationResult


class EditorialContent(BaseModel):
    """The assembled editorial content for one event in one language.

    Immutable container (approved TASK-019 output contract): a plain
    aggregation of already-generated data, not a new generation. `articles`
    is a `tuple`, not a `list`, so the collection itself is also immutable.
    """

    model_config = ConfigDict(frozen=True)

    event_id: int
    language: str
    verification_status: VerificationStatus
    title: str
    summary: str
    developer_impact: DeveloperImpact | None
    concept_explanation: ConceptExplanation | None
    articles: tuple[ArticleContext, ...]

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}, got {value!r}")
        return value


def assemble_editorial_content(
    event_id: int,
    language: str,
    verification: VerificationResult,
    summary: EventSummary,
    developer_impact: DeveloperImpact | None,
    concept_explanation: ConceptExplanation | None,
    articles: Sequence[ArticleContext],
) -> EditorialContent:
    """Assemble the editorial content for one event in one language.

    Validates that `event_id` and `language` are consistent across every
    supplied component before copying their fields into an
    `EditorialContent`. Performs no rewriting, summarization, translation,
    verification, classification, ranking or citation formatting: this is
    a pure aggregation boundary (approved TASK-019 spec).

    Args:
        event_id: identifier of the event this editorial content is for.
        language: target language; must be one of `SUPPORTED_LANGUAGES`.
        verification: the VERIFY result for this event. Only its
            `verification_status` is used -- `VerificationResult` carries
            no `event_id` (MODEL B), so no identity check is made against
            it.
        summary: the SUMMARIZE output for this event. Its `event_id` and
            `language` must match the arguments above.
        developer_impact: the Developer Impact output for this event, or
            `None` if it was not produced (absence is a normal outcome,
            docs/PRD.md §43). If provided, its `event_id` and `language`
            must match the arguments above.
        concept_explanation: the AI Senza Sbatti output connected to this
            event, or `None` if there is none. If provided, its `language`
            must match `language`; its `event_id` is only checked when set,
            since `ConceptExplanationInput.event_id` is itself optional.
        articles: the source articles backing this event's generated
            content. Preserved verbatim, as a tuple, with no
            transformation into a citation/reference shape.

    Returns:
        The assembled `EditorialContent`.

    Raises:
        ValueError: if `summary`, `developer_impact` or `concept_explanation`
            is inconsistent with the supplied `event_id`/`language`.
        pydantic.ValidationError: if `language` is not one of
            `SUPPORTED_LANGUAGES`.

    Pure: no I/O, no LLM call, no mutation of any argument. Deterministic:
    the same arguments always produce the same `EditorialContent`.
    """
    if summary.event_id != event_id:
        raise ValueError(
            f"summary.event_id ({summary.event_id!r}) does not match event_id ({event_id!r})"
        )
    if summary.language != language:
        raise ValueError(
            f"summary.language ({summary.language!r}) does not match language ({language!r})"
        )

    if developer_impact is not None:
        if developer_impact.event_id != event_id:
            raise ValueError(
                f"developer_impact.event_id ({developer_impact.event_id!r}) does not match"
                f" event_id ({event_id!r})"
            )
        if developer_impact.language != language:
            raise ValueError(
                f"developer_impact.language ({developer_impact.language!r}) does not match"
                f" language ({language!r})"
            )

    if concept_explanation is not None:
        if (
            concept_explanation.event_id is not None
            and concept_explanation.event_id != event_id
        ):
            raise ValueError(
                f"concept_explanation.event_id ({concept_explanation.event_id!r}) does not"
                f" match event_id ({event_id!r})"
            )
        if concept_explanation.language != language:
            raise ValueError(
                f"concept_explanation.language ({concept_explanation.language!r}) does not"
                f" match language ({language!r})"
            )

    return EditorialContent(
        event_id=event_id,
        language=language,
        verification_status=verification.verification_status,
        title=summary.title,
        summary=summary.summary,
        developer_impact=developer_impact,
        concept_explanation=concept_explanation,
        articles=tuple(articles),
    )
