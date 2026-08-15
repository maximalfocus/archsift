"""One validated, masked view of a canonical decision record for rendering.

Every generated representation of a record — the Markdown review view, the
detailed HTML report (FR-016), and the executive summary in HTML and PPTX
(FR-017) — must agree about the record's shape, about how an abstaining verdict
states its outcome, and about masking. That contract lives here once, so no
renderer can drift into a different idea of what a record is.

Masking (NFR-009) is applied when the view is built rather than by each
renderer, so no rendering path can emit an unmasked authored value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.language import is_supported_language
from archsift.masking import masked_decision_record_view

ABSENT: Final = "(not provided)"
EMPTY: Final = "(none)"
ABSTENTION: Final = "(abstention)"
NO_PERMISSIBLE_CANDIDATE: Final = "(no permissible candidate)"

REQUIRED_RECORD_KEYS: Final[tuple[str, ...]] = (
    "artefact_links",
    "assessment",
    "configuration",
    "configuration_content_identity",
    "dossier",
    "dossier_content_identity",
    "dossier_schema_version",
    "evidence_links",
    "reassessment_triggers",
    "record_content_identity",
    "record_schema_version",
    "ruleset_version",
    "tool_version",
    "unresolved_gaps",
)
REQUIRED_DOSSIER_KEYS: Final[tuple[str, ...]] = (
    "agency_necessity",
    "autonomy_permission",
    "candidate_comparison",
    "case",
    "decision_conditions",
    "evidence",
    "language",
    "problem_value",
    "schema_version",
    "task",
)
REQUIRED_ASSESSMENT_KEYS: Final[tuple[str, ...]] = (
    "active_hard_veto_ids",
    "evidence_state",
    "mandatory_human_control_ids",
    "ordered_elimination_evaluation",
    "prerequisite_evaluation",
    "recommended_class",
    "ruleset_version",
    "schema_version",
    "surviving_candidate_ids",
    "unmet_conditions",
    "verdict",
    "verdict_rule_id",
)

_ABSTAINING_VERDICTS: Final[dict[str, str]] = {
    "insufficient-evidence": ABSTENTION,
    "no-permissible-candidate": NO_PERMISSIBLE_CANDIDATE,
}


class ReportRecordError(ValueError):
    """A decision record cannot be rendered without ambiguity."""


def require_object(value: JsonValue, name: str) -> JsonObject:
    """Return ``value`` as a JSON object, or fail closed."""
    if type(value) is not dict:
        raise ReportRecordError(f"Decision record {name} is not a JSON object.")
    return value


def require_keys(mapping: JsonObject, expected: tuple[str, ...], name: str) -> None:
    """Require every declared key of one record part to be present."""
    missing = [key for key in expected if key not in mapping]
    if missing:
        raise ReportRecordError(f"Decision record {name} is missing {', '.join(missing)}.")


def require_text(value: JsonValue, name: str) -> str:
    """Return ``value`` as record text, or fail closed."""
    if type(value) is not str:
        raise ReportRecordError(f"Decision record {name} is not text.")
    return value


def recommendation(assessment: JsonObject) -> str:
    """Return the recommendation exactly as every representation states it.

    A recommending verdict names its class; an abstaining verdict names why no
    class is recommended. Any other combination is a record the renderers
    cannot describe honestly, so it fails closed.
    """
    recommended = assessment["recommended_class"]
    if recommended is not None:
        return require_text(recommended, "$.assessment.recommended_class")
    verdict = assessment["verdict"]
    if type(verdict) is str and verdict in _ABSTAINING_VERDICTS:
        return _ABSTAINING_VERDICTS[verdict]
    raise ReportRecordError("A recommending verdict has no recommended class.")


def declared_language(dossier: JsonObject) -> str:
    """Return the language a record's generated reports must be rendered in.

    NFR-010: every representation renders in the case's declared language, so
    a record naming a language ArchSift cannot generate content in is refused
    rather than quietly rendered in another one.
    """
    language = require_text(dossier["language"], "$.dossier.language")
    if not is_supported_language(language):
        raise ReportRecordError(f"Declared case language {language!r} is not supported.")
    return language


@dataclass(frozen=True, slots=True)
class RecordView:
    """One masked, shape-checked record with its two decision-bearing parts."""

    record: JsonObject
    dossier: JsonObject
    assessment: JsonObject
    language: str


def masked_record_view(record: JsonObject) -> RecordView:
    """Return one masked, validated view of a loaded canonical decision record."""
    if type(record) is not dict:
        raise ReportRecordError("Decision record is not a JSON object.")
    masked = masked_decision_record_view(record)
    require_keys(masked, REQUIRED_RECORD_KEYS, "$")
    dossier = require_object(masked["dossier"], "$.dossier")
    require_keys(dossier, REQUIRED_DOSSIER_KEYS, "$.dossier")
    assessment = require_object(masked["assessment"], "$.assessment")
    require_keys(assessment, REQUIRED_ASSESSMENT_KEYS, "$.assessment")
    return RecordView(masked, dossier, assessment, declared_language(dossier))
