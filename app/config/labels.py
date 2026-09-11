"""Editorial section labels, localized for `it` and `en`.

Loads and validates `config/labels.yaml` (docs/ARCHITECTURE.md §5.2): a
mapping from language code to a flat mapping of internal label key
(English, repository language — CLAUDE.md §43) to the displayed string for
that language (editorial content). The approved label keys and values are
recorded in docs/PRD.md §40.

This module only loads and validates the data. Resolving a label during
editorial assembly is a concern of the (not yet implemented) `app/editorial/`
package (docs/ARCHITECTURE.md §5.2); `get_label` here is the primitive it
will build on.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from app.config.errors import ConfigurationError
from app.config.settings import SUPPORTED_LANGUAGES

DEFAULT_LABELS_PATH = Path("config/labels.yaml")

_LabelsData = dict[str, dict[str, str]]
_labels_adapter: TypeAdapter[_LabelsData] = TypeAdapter(_LabelsData)


class Labels:
    """Localized section labels, keyed by language then internal label key."""

    def __init__(self, data: _LabelsData) -> None:
        self._data = data

    def get(self, key: str, language: str) -> str:
        """Return the label for `key` in `language`.

        Raises:
            ConfigurationError: if `language` is not supported, or `key`
                has no label defined for it.
        """
        if language not in self._data:
            raise ConfigurationError(f"Unsupported language: {language!r}")
        try:
            return self._data[language][key]
        except KeyError:
            raise ConfigurationError(
                f"Missing label {key!r} for language {language!r}"
            ) from None


def load_labels(path: str | Path = DEFAULT_LABELS_PATH) -> Labels:
    """Load and validate the editorial labels file.

    Raises:
        ConfigurationError: if the file is missing, is not valid YAML, does
            not map to `{language: {key: value}}`, does not cover every
            language in `SUPPORTED_LANGUAGES`, or defines a different set of
            keys per language.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"Labels file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    try:
        data = _labels_adapter.validate_python(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid labels file {path}: {exc}") from exc

    missing_languages = [language for language in SUPPORTED_LANGUAGES if language not in data]
    if missing_languages:
        raise ConfigurationError(f"Labels file {path} is missing languages: {missing_languages}")

    reference_language = SUPPORTED_LANGUAGES[0]
    reference_keys = set(data[reference_language])
    for language in SUPPORTED_LANGUAGES[1:]:
        keys = set(data[language])
        if keys != reference_keys:
            raise ConfigurationError(
                f"Labels file {path} has mismatched keys between "
                f"{reference_language!r} and {language!r}: {keys ^ reference_keys}"
            )

    return Labels(data)
