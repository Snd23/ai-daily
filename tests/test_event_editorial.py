"""Tests for `app.editorial.event_editorial` (TASK-019).

No network, no database and no LLM: `assemble_editorial_content` is a pure
aggregation function over already-constructed model instances.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.concept_explainer import ConceptExplanation
from app.ai.developer_impact import DeveloperImpact
from app.ai.event_summarizer import ArticleContext, EventSummary
from app.editorial import EditorialContent, assemble_editorial_content
from app.verification.event_verifier import VerificationResult


def _article(**overrides: object) -> ArticleContext:
    values: dict[str, object] = {
        "source_name": "Reuters",
        "title": "OpenAI announces X",
        "url": "https://example.com/openai-x",
        "published_at": "2026-09-14T10:00:00Z",
        "excerpt": "OpenAI announced X on Monday, according to a company statement.",
    }
    values.update(overrides)
    return ArticleContext.model_validate(values)


def _verification(**overrides: object) -> VerificationResult:
    values: dict[str, object] = {
        "verification_status": "VERIFIED",
        "confidence_score": 8.5,
        "hedging_constraints": [],
    }
    values.update(overrides)
    return VerificationResult.model_validate(values)


def _summary(**overrides: object) -> EventSummary:
    values: dict[str, object] = {
        "event_id": 42,
        "language": "en",
        "title": "OpenAI announces X",
        "summary": "OpenAI announced X on Monday.",
    }
    values.update(overrides)
    return EventSummary.model_validate(values)


def _developer_impact(**overrides: object) -> DeveloperImpact:
    values: dict[str, object] = {
        "event_id": 42,
        "language": "en",
        "has_developer_impact": True,
        "impact_summary": "The new API version changes the authentication flow.",
        "technical_area": ["API", "SDK"],
        "breaking_change": True,
    }
    values.update(overrides)
    return DeveloperImpact.model_validate(values)


def _concept_explanation(**overrides: object) -> ConceptExplanation:
    values: dict[str, object] = {
        "concept_slug": "transformer",
        "language": "en",
        "event_id": 42,
        "technical_definition": (
            "A transformer is a neural network architecture that uses self-attention."
        ),
        "simple_explanation": "It lets a computer figure out which words matter most.",
        "example": "It's a bit like highlighting the key words in a sentence.",
        "why_it_matters": "It powers most modern AI chatbots.",
        "one_liner": "A transformer lets AI focus on what matters most in a text.",
    }
    values.update(overrides)
    return ConceptExplanation.model_validate(values)


def _assemble(**overrides: object) -> EditorialContent:
    values: dict[str, object] = {
        "event_id": 42,
        "language": "en",
        "verification": _verification(),
        "summary": _summary(),
        "developer_impact": _developer_impact(),
        "concept_explanation": _concept_explanation(),
        "articles": [_article()],
    }
    values.update(overrides)
    return assemble_editorial_content(**values)  # type: ignore[arg-type]


# --- Happy path ----------------------------------------------------------------------


def test_assembles_content_with_all_optional_components() -> None:
    verification = _verification(verification_status="PARTIALLY_VERIFIED", confidence_score=6.0)
    summary = _summary(title="Title", summary="Summary text.")
    developer_impact = _developer_impact()
    concept_explanation = _concept_explanation()
    articles = [_article(), _article(source_name="TechCrunch", url="https://example.com/y")]

    content = assemble_editorial_content(
        event_id=42,
        language="en",
        verification=verification,
        summary=summary,
        developer_impact=developer_impact,
        concept_explanation=concept_explanation,
        articles=articles,
    )

    assert content.event_id == 42
    assert content.language == "en"
    assert content.verification_status == "PARTIALLY_VERIFIED"
    assert content.title == "Title"
    assert content.summary == "Summary text."
    assert content.developer_impact == developer_impact
    assert content.concept_explanation == concept_explanation
    assert content.articles == tuple(articles)


# --- Optional blocks -------------------------------------------------------------------


def test_assembles_content_with_developer_impact_none() -> None:
    content = _assemble(developer_impact=None)

    assert content.developer_impact is None
    assert content.concept_explanation is not None


def test_assembles_content_with_concept_explanation_none() -> None:
    content = _assemble(concept_explanation=None)

    assert content.concept_explanation is None
    assert content.developer_impact is not None


def test_assembles_content_with_both_optional_components_none() -> None:
    content = _assemble(developer_impact=None, concept_explanation=None)

    assert content.developer_impact is None
    assert content.concept_explanation is None


def test_assembles_content_with_no_developer_impact_result() -> None:
    """`has_developer_impact=False` is a valid, non-`None` `DeveloperImpact` (docs/PRD.md §43)."""
    no_impact = _developer_impact(
        has_developer_impact=False, impact_summary=None, technical_area=None, breaking_change=None
    )

    content = _assemble(developer_impact=no_impact)

    assert content.developer_impact is not None
    assert content.developer_impact.has_developer_impact is False


# --- Event consistency -----------------------------------------------------------------


def test_rejects_summary_event_id_mismatch() -> None:
    with pytest.raises(ValueError, match="summary.event_id"):
        _assemble(summary=_summary(event_id=99))


def test_rejects_developer_impact_event_id_mismatch() -> None:
    with pytest.raises(ValueError, match="developer_impact.event_id"):
        _assemble(developer_impact=_developer_impact(event_id=99))


def test_rejects_concept_explanation_event_id_mismatch() -> None:
    with pytest.raises(ValueError, match="concept_explanation.event_id"):
        _assemble(concept_explanation=_concept_explanation(event_id=99))


def test_allows_concept_explanation_with_no_event_id() -> None:
    """`ConceptExplanationInput.event_id` is optional; `None` is not a mismatch."""
    content = _assemble(concept_explanation=_concept_explanation(event_id=None))

    assert content.concept_explanation is not None
    assert content.concept_explanation.event_id is None


# --- Language consistency ---------------------------------------------------------------


def test_rejects_unsupported_language() -> None:
    with pytest.raises(ValidationError):
        _assemble(
            language="fr",
            summary=_summary(language="fr"),
            developer_impact=_developer_impact(language="fr"),
            concept_explanation=_concept_explanation(language="fr"),
        )


def test_rejects_summary_language_mismatch() -> None:
    with pytest.raises(ValueError, match="summary.language"):
        _assemble(summary=_summary(language="it"))


def test_rejects_developer_impact_language_mismatch() -> None:
    with pytest.raises(ValueError, match="developer_impact.language"):
        _assemble(developer_impact=_developer_impact(language="it"))


def test_rejects_concept_explanation_language_mismatch() -> None:
    with pytest.raises(ValueError, match="concept_explanation.language"):
        _assemble(concept_explanation=_concept_explanation(language="it"))


# --- Immutability --------------------------------------------------------------------


def test_editorial_content_is_frozen() -> None:
    content = _assemble()

    with pytest.raises(ValidationError):
        content.title = "Changed"  # type: ignore[misc]


def test_editorial_content_articles_is_a_tuple() -> None:
    content = _assemble(articles=[_article()])

    assert isinstance(content.articles, tuple)


# --- Source preservation ---------------------------------------------------------------


def test_preserves_every_supplied_article_unchanged() -> None:
    articles = [
        _article(source_name="Reuters", url="https://example.com/1"),
        _article(source_name="TechCrunch", url="https://example.com/2"),
        _article(source_name="The Verge", url="https://example.com/3"),
    ]

    content = _assemble(articles=articles)

    assert list(content.articles) == articles
    for original, preserved in zip(articles, content.articles, strict=True):
        assert preserved is original


# --- No input mutation -----------------------------------------------------------------


def test_does_not_mutate_the_supplied_articles_sequence() -> None:
    articles = [_article(), _article(source_name="TechCrunch", url="https://example.com/y")]
    original_articles = list(articles)

    _assemble(articles=articles)

    assert articles == original_articles


def test_does_not_mutate_the_supplied_component_objects() -> None:
    verification = _verification()
    summary = _summary()
    developer_impact = _developer_impact()
    concept_explanation = _concept_explanation()

    verification_copy = verification.model_copy()
    summary_copy = summary.model_copy()
    developer_impact_copy = developer_impact.model_copy()
    concept_explanation_copy = concept_explanation.model_copy()

    assemble_editorial_content(
        event_id=42,
        language="en",
        verification=verification,
        summary=summary,
        developer_impact=developer_impact,
        concept_explanation=concept_explanation,
        articles=[_article()],
    )

    assert verification == verification_copy
    assert summary == summary_copy
    assert developer_impact == developer_impact_copy
    assert concept_explanation == concept_explanation_copy
