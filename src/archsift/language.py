"""The declared case language (NFR-010).

Every case workspace declares one language code. It governs what ArchSift
itself generates — the workspace boilerplate and the generated decision-record
reports — and it participates in the canonical dossier bytes, so changing it
produces a distinct record.

The language of *authored* dossier prose and evidence is a documented
convention, not a machine-verifiable fact. ArchSift therefore never inspects
authored text to judge what language it is written in, and a mismatch between
the declared code and the prose is not a validation error. Declaring a language
states an intent about the case; it never asserts a truth about its content.

English is the initially supported language. Adding another means adding its
workspace guidance resource and its entry below, so the supported set can never
claim a language whose generated content does not exist.
"""

from __future__ import annotations

import re
from importlib.resources import files
from typing import Final

DEFAULT_LANGUAGE: Final = "en"

# One entry per language ArchSift can generate content in.
_WORKSPACE_GUIDANCE: Final[dict[str, str]] = {
    "en": "templates/workspace-README.md",
}

SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = tuple(sorted(_WORKSPACE_GUIDANCE))

#: A BCP 47-shaped code: a 2-3 letter primary subtag with optional subtags.
#: The shape is checked by the dossier schema; support is checked here.
LANGUAGE_CODE_PATTERN: Final = r"^[a-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$"
_LANGUAGE_CODE: Final = re.compile(LANGUAGE_CODE_PATTERN)


class UnsupportedLanguageError(ValueError):
    """A case declares a language ArchSift cannot generate content in."""


def is_well_formed_language(code: object) -> bool:
    """Return whether ``code`` has the shape of a language code."""
    return type(code) is str and _LANGUAGE_CODE.fullmatch(code) is not None


def is_supported_language(code: object) -> bool:
    """Return whether ArchSift can generate content in ``code``."""
    return type(code) is str and code in _WORKSPACE_GUIDANCE


def supported_languages_text() -> str:
    """Return the supported codes as fixed diagnostic text."""
    return ", ".join(SUPPORTED_LANGUAGES)


#: The template line the rendered evidence-set profile replaces (FR-021).
EVIDENCE_SET_MARKER: Final = "<!-- evidence-set-profile -->"


def workspace_guidance(code: str, schema_version: int = 1) -> str:
    """Return the packaged workspace guidance written in ``code``.

    The guidance presents the evidence-set profile of ``schema_version`` as the
    authoring target, rendered from the published profile at this call so the
    guidance cannot drift from it (FR-001, FR-021).
    """
    resource = _WORKSPACE_GUIDANCE.get(code)
    if resource is None:
        raise UnsupportedLanguageError(f"No workspace guidance exists for language {code!r}.")
    template = files("archsift").joinpath(resource).read_text(encoding="utf-8")
    if EVIDENCE_SET_MARKER not in template:
        return template
    # Imported here: the evidence set reads the schema module, which reads this one.
    from archsift.evidence_set import evidence_set_profile, guidance_lines

    rendered = "\n".join(guidance_lines(evidence_set_profile(schema_version)))
    return template.replace(EVIDENCE_SET_MARKER, rendered)
