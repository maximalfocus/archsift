"""The standard evidence set (FR-021): the profile every case is prepared into.

For a dossier schema version, the profile is the ordered list of decision-
bearing slots — the schema locations that carry evidence references — with the
task boundary first and the slots grouped under the four decision questions.
Each slot carries a fixed reader-facing name, one plain sentence, the evidence
kinds acceptable to the rules that read it, and the framework rule numbers
(FR-020) that read it. The profile is derived from the packaged schema and the
vocabulary only: a location that carries evidence references and has no slot is
a schema defect and fails closed, as does a slot that names no location of any
supported schema version. The profile never participates in validation or
assessment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from archsift import vocabulary
from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.validation import (
    SUPPORTED_DOSSIER_SCHEMA_VERSIONS,
    DecisionArea,
    EvidenceKind,
    packaged_dossier_schema,
)
from archsift.vocabulary import (
    QUESTIONS,
    TASK_BOUNDARY_LOCATION,
    SlotPhrases,
    VocabularyError,
    phrase,
    slot_phrases,
    validate_vocabulary,
)

EVIDENCE_SET_PROFILE_SCHEMA_VERSION: Final = 1

#: The top-level dossier section each decision question is answered in.
_SECTION_QUESTIONS: Final[Mapping[str, DecisionArea]] = {
    "problem_value": DecisionArea.PROBLEM_VALUE,
    "agency_necessity": DecisionArea.AGENCY_NECESSITY,
    "autonomy_permission": DecisionArea.AUTONOMY_PERMISSION,
    "candidate_comparison": DecisionArea.COMPARATIVE_FIT,
    # A condition on the result concerns the fit of the indicated option.
    "decision_conditions": DecisionArea.COMPARATIVE_FIT,
}


@dataclass(frozen=True, slots=True)
class Slot:
    """One slot of the evidence set: a schema location and its reader-facing form."""

    location: str
    question: DecisionArea | None
    phrases: SlotPhrases

    @property
    def kind_phrases(self) -> tuple[str, ...]:
        return tuple(phrase(kind) for kind in self.phrases.kinds)


@dataclass(frozen=True, slots=True)
class EvidenceSetProfile:
    """The complete evidence-set profile of one dossier schema version."""

    dossier_schema_version: int
    vocabulary_version: str
    framework_version: str
    slots: tuple[Slot, ...]


def evidence_bearing_locations(schema_version: int) -> tuple[str, ...]:
    """Return every location of a packaged schema that carries evidence references.

    The walk follows the schema's own property order, so the profile order is
    the schema order and needs no separate list to keep in step.
    """
    schema = packaged_dossier_schema(schema_version)
    definitions = cast(Mapping[str, Any], schema.get("$defs", {}))
    found: list[str] = []

    def walk(node: Any, path: str, seen: frozenset[str]) -> None:
        if not isinstance(node, dict):
            return
        reference = node.get("$ref")
        if isinstance(reference, str):
            name = reference.rsplit("/", 1)[-1]
            if name in seen:
                return
            target = definitions[name]
            if "evidence_ids" in target.get("properties", {}):
                found.append(path)
            walk(target, path, seen | {name})
            return
        for key, value in node.get("properties", {}).items():
            walk(value, f"{path}.{key}", seen)
        if "items" in node:
            walk(node["items"], f"{path}[]", seen)
        for keyword in ("anyOf", "oneOf", "allOf"):
            for alternative in node.get(keyword, []):
                walk(alternative, path, seen)

    walk(schema, "$", frozenset())
    return tuple(found)


def _question_of(location: str) -> DecisionArea:
    section = location.removeprefix("$.").split(".", 1)[0].removesuffix("[]")
    try:
        return _SECTION_QUESTIONS[section]
    except KeyError:
        raise VocabularyError(
            f"Schema location {location!r} belongs to no decision question; the evidence-set "
            "profile cannot place it."
        ) from None


def evidence_set_profile(schema_version: int) -> EvidenceSetProfile:
    """Return the evidence-set profile of one supported dossier schema version, failing closed."""
    validate_vocabulary()
    if schema_version not in SUPPORTED_DOSSIER_SCHEMA_VERSIONS:
        raise VocabularyError(f"Unsupported dossier schema version {schema_version}.")
    locations = evidence_bearing_locations(schema_version)
    slots = [Slot(TASK_BOUNDARY_LOCATION, None, slot_phrases(TASK_BOUNDARY_LOCATION))]
    for area in DecisionArea:
        for location in locations:
            if _question_of(location) is area:
                slots.append(Slot(location, area, slot_phrases(location)))
    if len(slots) != len(locations) + 1:  # pragma: no cover - every location has one question
        raise VocabularyError("The evidence-set profile did not place every location.")
    return EvidenceSetProfile(
        dossier_schema_version=schema_version,
        vocabulary_version=vocabulary.VOCABULARY_VERSION,
        framework_version=vocabulary.FRAMEWORK_VERSION,
        slots=tuple(slots),
    )


def validate_slot_coverage() -> None:
    """Fail closed unless every slot names a location of some supported schema version."""
    known = {TASK_BOUNDARY_LOCATION}
    for version in SUPPORTED_DOSSIER_SCHEMA_VERSIONS:
        known.update(evidence_bearing_locations(version))
    for location in vocabulary.SLOTS:
        if location not in known:
            raise VocabularyError(
                f"Evidence-set slot {location!r} names no location of any supported dossier "
                "schema; remove it or correct its location."
            )


def profile_payload(profile: EvidenceSetProfile) -> JsonObject:
    """Return the deterministic machine-readable form of a profile."""
    return {
        "dossier_schema_version": profile.dossier_schema_version,
        "evidence_set_profile_schema_version": EVIDENCE_SET_PROFILE_SCHEMA_VERSION,
        "framework_version": profile.framework_version,
        "slots": [
            {
                "acceptable_kinds": [kind.value for kind in slot.phrases.kinds],
                "framework_rules": list(slot.phrases.framework_rules),
                "location": slot.location,
                "name": slot.phrases.name,
                "question": slot.question.value if slot.question is not None else None,
                "sentence": slot.phrases.sentence,
            }
            for slot in profile.slots
        ],
        "vocabulary_version": profile.vocabulary_version,
    }


def profile_bytes(profile: EvidenceSetProfile) -> bytes:
    """Return the canonical JSON bytes of a profile."""
    return canonical_json_bytes(profile_payload(profile))


def profile_lines(profile: EvidenceSetProfile) -> list[str]:
    """Render the profile as plain text lines: the task boundary, then each question's slots."""
    lines = [
        f"Evidence set for case file format {profile.dossier_schema_version} "
        f"(vocabulary {profile.vocabulary_version}; framework {profile.framework_version}): "
        f"{len(profile.slots)} slots"
    ]
    current: DecisionArea | None = None
    for slot in profile.slots:
        if slot.question is not None and slot.question is not current:
            current = slot.question
            lines.append(QUESTIONS[current])
        kinds = ", ".join(slot.kind_phrases) if slot.phrases.kinds else "none"
        rules = ", ".join(str(number) for number in slot.phrases.framework_rules)
        prefix = "" if slot.question is None else "  "
        lines.append(
            f"{prefix}- {slot.phrases.name}: {slot.phrases.sentence} Evidence: {kinds}. "
            f"Framework rules: {rules}."
        )
    return lines


__all__ = [
    "EVIDENCE_SET_PROFILE_SCHEMA_VERSION",
    "EvidenceKind",
    "EvidenceSetProfile",
    "Slot",
    "evidence_bearing_locations",
    "evidence_set_profile",
    "profile_bytes",
    "profile_lines",
    "profile_payload",
    "validate_slot_coverage",
]
