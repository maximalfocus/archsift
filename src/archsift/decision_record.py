"""Canonical in-memory decision-record composition for current typed inputs."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any, TypeAlias, TypeVar, cast

from archsift.canonical import (
    CanonicalizationError,
    JsonObject,
    JsonValue,
    canonical_dossier_dict,
    canonical_json_bytes,
    dossier_content_identity,
    evidence_content_identities,
)
from archsift.decision import (
    ArchitectureVerdict,
    AssessmentEvaluation,
    CandidateDisposition,
    CandidateElimination,
    ControlClassDisposition,
    ControlClassElimination,
    CriterionKind,
    DecisionFinding,
    EvidenceState,
    OrderedEliminationEvaluation,
    evaluate_assessment,
)
from archsift.rules import (
    RULESET_VERSION,
    AssessmentPrerequisiteEvaluation,
    AssessmentPrerequisiteFinding,
    RuleEffect,
)
from archsift.validation import (
    AssumptionEvidence,
    ControlClass,
    DecisionArea,
    DecisionCondition,
    DecisionConditionStatus,
    Dossier,
    EvidenceKind,
    MissingEvidence,
)

RECORD_SCHEMA_VERSION = 1

_EnumT = TypeVar("_EnumT", bound=Enum)


class DecisionRecordError(CanonicalizationError):
    """A decision record cannot be composed or represented without ambiguity."""


class UnresolvedGapSource(StrEnum):
    """The deterministic evaluation stage that exposed an unresolved gap."""

    PREREQUISITE = "prerequisite"
    DECISION = "decision"


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """One canonical evidence-ledger identity bound into a decision record."""

    evidence_id: str
    kind: EvidenceKind
    content_identity: str


@dataclass(frozen=True, slots=True)
class PrerequisiteGap:
    """One unmet assessment prerequisite preserved without inferred rationale."""

    source: UnresolvedGapSource
    rule_id: str
    field: str
    requirement: str
    effect: RuleEffect
    message: str
    consequence: str
    remediation: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionGap:
    """One evidence gap that left a represented candidate undetermined."""

    source: UnresolvedGapSource
    rule_id: str
    requirement: str
    effect: RuleEffect
    candidate_id: str
    control_class: ControlClass
    criterion_id: str
    criterion_kind: CriterionKind
    evidence_ids: tuple[str, ...]
    message: str
    consequence: str


UnresolvedGap: TypeAlias = PrerequisiteGap | DecisionGap


@dataclass(frozen=True, slots=True)
class ReassessmentTrigger:
    """One authored schema-v1 observation that can trigger reassessment."""

    evidence_id: str
    kind: EvidenceKind
    observation: str


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Immutable semantic record for the current typed dossier and assessment."""

    record_schema_version: int
    dossier_schema_version: int
    dossier_content_identity: str
    ruleset_version: str
    tool_version: str
    dossier: Dossier
    assessment: AssessmentEvaluation
    evidence_links: tuple[EvidenceLink, ...]
    unresolved_gaps: tuple[UnresolvedGap, ...]
    reassessment_triggers: tuple[ReassessmentTrigger, ...]


def _checked_dataclass(
    value: object,
    expected_type: type[object],
    expected_fields: tuple[str, ...],
) -> None:
    if type(value) is not expected_type or not is_dataclass(value):
        raise DecisionRecordError(
            f"Unsupported {expected_type.__name__} typed value for decision records."
        )
    actual_fields = tuple(field.name for field in fields(cast(Any, value)))
    if actual_fields != expected_fields:
        raise DecisionRecordError(
            f"Unsupported {expected_type.__name__} field contract for decision records."
        )


def _require_tuple(value: object, label: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise DecisionRecordError(f"{label} must be an immutable tuple.")
    return value


def _require_string_tuple(value: object, label: str) -> tuple[str, ...]:
    items = _require_tuple(value, label)
    if not all(type(item) is str for item in items):
        raise DecisionRecordError(f"{label} must contain only string values.")
    return cast(tuple[str, ...], items)


def _require_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise DecisionRecordError(f"{label} must be text for decision records.")
    return value


def _enum_value(
    value: _EnumT,
    enum_type: type[_EnumT],
    expected_values: tuple[str, ...],
) -> str:
    actual_values = tuple(member.value for member in enum_type)
    if type(value) is not enum_type or actual_values != expected_values:
        raise DecisionRecordError(
            f"Unsupported {enum_type.__name__} value contract for decision records."
        )
    raw = value.value
    if not isinstance(raw, str):
        raise DecisionRecordError(
            f"Unsupported {enum_type.__name__} non-string decision-record value."
        )
    return raw


def _rule_effect(value: RuleEffect) -> str:
    return _enum_value(
        value,
        RuleEffect,
        ("block", "require-evidence", "support-candidate"),
    )


def _control_class(value: ControlClass) -> str:
    return _enum_value(
        value,
        ControlClass,
        (
            "human-owned-work",
            "process-redesign",
            "deterministic-automation",
            "fixed-ai-workflow",
            "agentic-control",
        ),
    )


def _checked_payload(
    payload: object,
    expected_keys: tuple[str, ...],
    label: str,
) -> JsonObject:
    if type(payload) is not dict or set(payload) != set(expected_keys):
        raise DecisionRecordError(f"Incomplete {label} JSON contract for decision records.")
    return cast(JsonObject, payload)


def _prerequisite_finding_dict(value: AssessmentPrerequisiteFinding) -> JsonObject:
    expected = (
        "rule_id",
        "field",
        "requirement",
        "effect",
        "message",
        "consequence",
        "remediation",
        "evidence_ids",
    )
    _checked_dataclass(value, AssessmentPrerequisiteFinding, expected)
    _require_string(value.rule_id, "Prerequisite-finding rule_id")
    _require_string(value.field, "Prerequisite-finding field")
    _require_string(value.requirement, "Prerequisite-finding requirement")
    _require_string(value.message, "Prerequisite-finding message")
    _require_string(value.consequence, "Prerequisite-finding consequence")
    _require_string(value.remediation, "Prerequisite-finding remediation")
    _rule_effect(value.effect)
    _require_string_tuple(value.evidence_ids, "Prerequisite-finding evidence IDs")
    return _checked_payload(value.to_dict(), expected, "prerequisite-finding")


def _prerequisite_evaluation_dict(value: AssessmentPrerequisiteEvaluation) -> JsonObject:
    expected = ("ruleset_version", "ready", "findings")
    _checked_dataclass(value, AssessmentPrerequisiteEvaluation, expected)
    _require_string(value.ruleset_version, "Prerequisite-evaluation ruleset_version")
    if type(value.ready) is not bool:
        raise DecisionRecordError("Assessment prerequisite readiness must be a boolean.")
    findings = _require_tuple(value.findings, "Assessment prerequisite findings")
    for finding in findings:
        _prerequisite_finding_dict(finding)
    return _checked_payload(value.to_dict(), expected, "prerequisite-evaluation")


def _decision_finding_dict(value: DecisionFinding) -> JsonObject:
    expected = (
        "rule_id",
        "requirement",
        "effect",
        "candidate_id",
        "control_class",
        "criterion_id",
        "criterion_kind",
        "evidence_ids",
        "message",
        "consequence",
    )
    _checked_dataclass(value, DecisionFinding, expected)
    _require_string(value.rule_id, "Decision-finding rule_id")
    _require_string(value.requirement, "Decision-finding requirement")
    _require_string(value.candidate_id, "Decision-finding candidate_id")
    _require_string(value.criterion_id, "Decision-finding criterion_id")
    _require_string(value.message, "Decision-finding message")
    _require_string(value.consequence, "Decision-finding consequence")
    _rule_effect(value.effect)
    _control_class(value.control_class)
    _enum_value(value.criterion_kind, CriterionKind, ("outcome", "constraint"))
    _require_string_tuple(value.evidence_ids, "Decision-finding evidence IDs")
    return _checked_payload(value.to_dict(), expected, "decision-finding")


def _ordered_evaluation_dict(value: OrderedEliminationEvaluation) -> JsonObject:
    expected = (
        "ruleset_version",
        "candidates",
        "control_classes",
        "findings",
        "least_surviving_class",
    )
    _checked_dataclass(value, OrderedEliminationEvaluation, expected)
    _require_string(value.ruleset_version, "Ordered-elimination ruleset_version")
    candidate_values = _require_tuple(value.candidates, "Candidate eliminations")
    class_values = _require_tuple(value.control_classes, "Control-class eliminations")
    finding_values = _require_tuple(value.findings, "Ordered-elimination findings")
    for candidate in candidate_values:
        _checked_dataclass(
            candidate,
            CandidateElimination,
            ("candidate_id", "control_class", "disposition"),
        )
        _require_string(candidate.candidate_id, "Candidate-elimination candidate_id")
        _control_class(candidate.control_class)
        _enum_value(
            candidate.disposition,
            CandidateDisposition,
            ("eliminated", "undetermined", "survives"),
        )
    for result in class_values:
        _checked_dataclass(
            result,
            ControlClassElimination,
            ("control_class", "candidate_ids", "disposition"),
        )
        _require_string_tuple(result.candidate_ids, "Control-class candidate IDs")
        _control_class(result.control_class)
        _enum_value(
            result.disposition,
            ControlClassDisposition,
            ("eliminated", "undetermined", "survives"),
        )
    for finding in finding_values:
        _decision_finding_dict(finding)
    if value.least_surviving_class is not None:
        _control_class(value.least_surviving_class)
    return _checked_payload(value.to_dict(), expected, "ordered-elimination evaluation")


def _assessment_condition_dict(value: DecisionCondition) -> JsonObject:
    expected = (
        "id",
        "target_control_class",
        "decision_area",
        "statement",
        "status",
        "resolved_by",
        "evidence_ids",
    )
    _checked_dataclass(value, DecisionCondition, expected)
    _require_string(value.id, "Decision-condition id")
    _require_string(value.statement, "Decision-condition statement")
    _require_string(value.resolved_by, "Decision-condition resolved_by")
    _require_string_tuple(value.evidence_ids, "Decision-condition evidence IDs")
    return {
        "decision_area": _enum_value(
            value.decision_area,
            DecisionArea,
            (
                "problem-value",
                "agency-necessity",
                "autonomy-permission",
                "comparative-fit",
            ),
        ),
        "evidence_ids": list(value.evidence_ids),
        "id": value.id,
        "resolved_by": value.resolved_by,
        "statement": value.statement,
        "status": _enum_value(
            value.status,
            DecisionConditionStatus,
            ("met", "unmet"),
        ),
        "target_control_class": _control_class(value.target_control_class),
    }


def _assessment_dict(value: AssessmentEvaluation) -> JsonObject:
    expected = (
        "schema_version",
        "ruleset_version",
        "verdict",
        "verdict_rule_id",
        "evidence_state",
        "recommended_class",
        "surviving_candidate_ids",
        "unmet_conditions",
        "active_hard_veto_ids",
        "mandatory_human_control_ids",
        "prerequisite_evaluation",
        "ordered_elimination_evaluation",
    )
    _checked_dataclass(value, AssessmentEvaluation, expected)
    if type(value.schema_version) is not int:
        raise DecisionRecordError("Decision-record assessment schema version must be an integer.")
    _require_string(value.ruleset_version, "Assessment ruleset_version")
    _require_string(value.verdict_rule_id, "Assessment verdict_rule_id")
    _require_string_tuple(value.active_hard_veto_ids, "Active hard-veto IDs")
    _require_string_tuple(value.mandatory_human_control_ids, "Mandatory human-control IDs")
    _require_string_tuple(value.surviving_candidate_ids, "Surviving candidate IDs")
    condition_values = _require_tuple(value.unmet_conditions, "Unmet decision conditions")
    for condition in condition_values:
        _assessment_condition_dict(condition)
    _enum_value(
        value.evidence_state,
        EvidenceState,
        ("evidence-complete", "evidence-incomplete"),
    )
    if value.recommended_class is not None:
        _control_class(value.recommended_class)
    _enum_value(
        value.verdict,
        ArchitectureVerdict,
        (
            "supported",
            "conditional",
            "insufficient-evidence",
            "no-permissible-candidate",
            "no-technology-change",
        ),
    )
    _prerequisite_evaluation_dict(value.prerequisite_evaluation)
    _ordered_evaluation_dict(value.ordered_elimination_evaluation)
    return _checked_payload(value.to_dict(), expected, "assessment evaluation")


def _evidence_link_dict(value: EvidenceLink) -> JsonObject:
    _checked_dataclass(value, EvidenceLink, ("evidence_id", "kind", "content_identity"))
    _require_string(value.evidence_id, "Evidence-link evidence_id")
    _require_string(value.content_identity, "Evidence-link content_identity")
    return {
        "content_identity": value.content_identity,
        "evidence_id": value.evidence_id,
        "kind": _enum_value(
            value.kind,
            EvidenceKind,
            ("observed", "assumption", "estimate", "missing"),
        ),
    }


def _gap_dict(value: UnresolvedGap) -> JsonObject:
    if type(value) is PrerequisiteGap:
        expected: tuple[str, ...] = (
            "source",
            "rule_id",
            "field",
            "requirement",
            "effect",
            "message",
            "consequence",
            "remediation",
            "evidence_ids",
        )
        _checked_dataclass(value, PrerequisiteGap, expected)
        _require_string(value.rule_id, "Prerequisite-gap rule_id")
        _require_string(value.field, "Prerequisite-gap field")
        _require_string(value.requirement, "Prerequisite-gap requirement")
        _require_string(value.message, "Prerequisite-gap message")
        _require_string(value.consequence, "Prerequisite-gap consequence")
        _require_string(value.remediation, "Prerequisite-gap remediation")
        _require_string_tuple(value.evidence_ids, "Prerequisite-gap evidence IDs")
        return {
            "consequence": value.consequence,
            "effect": _rule_effect(value.effect),
            "evidence_ids": list(value.evidence_ids),
            "field": value.field,
            "message": value.message,
            "remediation": value.remediation,
            "requirement": value.requirement,
            "rule_id": value.rule_id,
            "source": _enum_value(
                value.source,
                UnresolvedGapSource,
                ("prerequisite", "decision"),
            ),
        }
    if type(value) is DecisionGap:
        expected = (
            "source",
            "rule_id",
            "requirement",
            "effect",
            "candidate_id",
            "control_class",
            "criterion_id",
            "criterion_kind",
            "evidence_ids",
            "message",
            "consequence",
        )
        _checked_dataclass(value, DecisionGap, expected)
        _require_string(value.rule_id, "Decision-gap rule_id")
        _require_string(value.requirement, "Decision-gap requirement")
        _require_string(value.candidate_id, "Decision-gap candidate_id")
        _require_string(value.criterion_id, "Decision-gap criterion_id")
        _require_string(value.message, "Decision-gap message")
        _require_string(value.consequence, "Decision-gap consequence")
        _require_string_tuple(value.evidence_ids, "Decision-gap evidence IDs")
        return {
            "candidate_id": value.candidate_id,
            "consequence": value.consequence,
            "control_class": _control_class(value.control_class),
            "criterion_id": value.criterion_id,
            "criterion_kind": _enum_value(
                value.criterion_kind,
                CriterionKind,
                ("outcome", "constraint"),
            ),
            "effect": _rule_effect(value.effect),
            "evidence_ids": list(value.evidence_ids),
            "message": value.message,
            "requirement": value.requirement,
            "rule_id": value.rule_id,
            "source": _enum_value(
                value.source,
                UnresolvedGapSource,
                ("prerequisite", "decision"),
            ),
        }
    raise DecisionRecordError("Unsupported unresolved-gap subtype for decision records.")


def _trigger_dict(value: ReassessmentTrigger) -> JsonObject:
    _checked_dataclass(
        value,
        ReassessmentTrigger,
        ("evidence_id", "kind", "observation"),
    )
    _require_string(value.evidence_id, "Reassessment-trigger evidence_id")
    _require_string(value.observation, "Reassessment-trigger observation")
    kind = _enum_value(
        value.kind,
        EvidenceKind,
        ("observed", "assumption", "estimate", "missing"),
    )
    if value.kind not in {EvidenceKind.ASSUMPTION, EvidenceKind.MISSING}:
        raise DecisionRecordError("Unsupported evidence kind for a reassessment trigger.")
    return {
        "evidence_id": value.evidence_id,
        "kind": kind,
        "observation": value.observation,
    }


def _unresolved_gaps(assessment: AssessmentEvaluation) -> tuple[UnresolvedGap, ...]:
    prerequisite_gaps = tuple(
        PrerequisiteGap(
            source=UnresolvedGapSource.PREREQUISITE,
            rule_id=finding.rule_id,
            field=finding.field,
            requirement=finding.requirement,
            effect=finding.effect,
            message=finding.message,
            consequence=finding.consequence,
            remediation=finding.remediation,
            evidence_ids=finding.evidence_ids,
        )
        for finding in assessment.prerequisite_evaluation.findings
    )
    decision_gaps = tuple(
        DecisionGap(
            source=UnresolvedGapSource.DECISION,
            rule_id=finding.rule_id,
            requirement=finding.requirement,
            effect=finding.effect,
            candidate_id=finding.candidate_id,
            control_class=finding.control_class,
            criterion_id=finding.criterion_id,
            criterion_kind=finding.criterion_kind,
            evidence_ids=finding.evidence_ids,
            message=finding.message,
            consequence=finding.consequence,
        )
        for finding in assessment.ordered_elimination_evaluation.findings
        if finding.effect is RuleEffect.REQUIRE_EVIDENCE
    )
    return (*prerequisite_gaps, *decision_gaps)


def _reassessment_triggers(dossier: Dossier) -> tuple[ReassessmentTrigger, ...]:
    triggers: list[ReassessmentTrigger] = []
    for entry in sorted(dossier.evidence, key=lambda item: item.id):
        if type(entry) is AssumptionEvidence:
            triggers.append(
                ReassessmentTrigger(
                    evidence_id=entry.id,
                    kind=EvidenceKind.ASSUMPTION,
                    observation=entry.falsified_by,
                )
            )
        elif type(entry) is MissingEvidence:
            triggers.append(
                ReassessmentTrigger(
                    evidence_id=entry.id,
                    kind=EvidenceKind.MISSING,
                    observation=entry.resolved_by,
                )
            )
    return tuple(triggers)


def _collect_evidence_citations(value: JsonValue) -> set[str]:
    citations: set[str] = set()
    if isinstance(value, list):
        for item in value:
            citations.update(_collect_evidence_citations(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_ids":
                if not isinstance(item, list) or not all(
                    type(identifier) is str for identifier in item
                ):
                    raise DecisionRecordError("Evidence citations must be arrays of string IDs.")
                citations.update(cast(list[str], item))
            else:
                citations.update(_collect_evidence_citations(item))
    return citations


def _validate_resolved_citations(
    dossier_payload: JsonObject,
    assessment_payload: JsonObject,
    evidence_ids: set[str],
) -> None:
    citations = _collect_evidence_citations(dossier_payload)
    citations.update(_collect_evidence_citations(assessment_payload))
    missing = sorted(citations - evidence_ids)
    if missing:
        rendered = ", ".join(repr(identifier) for identifier in missing)
        raise DecisionRecordError(f"Decision record has unresolved evidence IDs: {rendered}.")


def _expected_evidence_links(dossier: Dossier) -> tuple[EvidenceLink, ...]:
    identities = evidence_content_identities(dossier)
    entries = {entry.id: entry for entry in dossier.evidence}
    return tuple(
        EvidenceLink(
            evidence_id=identifier,
            kind=entries[identifier].kind,
            content_identity=identity,
        )
        for identifier, identity in identities.items()
    )


def _validate_record(record: DecisionRecord) -> tuple[JsonObject, JsonObject]:
    expected_fields = (
        "record_schema_version",
        "dossier_schema_version",
        "dossier_content_identity",
        "ruleset_version",
        "tool_version",
        "dossier",
        "assessment",
        "evidence_links",
        "unresolved_gaps",
        "reassessment_triggers",
    )
    _checked_dataclass(record, DecisionRecord, expected_fields)
    if (
        type(record.record_schema_version) is not int
        or record.record_schema_version != RECORD_SCHEMA_VERSION
    ):
        raise DecisionRecordError("Unsupported decision-record schema version.")
    if type(record.dossier_schema_version) is not int:
        raise DecisionRecordError("Decision-record dossier schema version must be an integer.")
    if type(record.dossier_content_identity) is not str:
        raise DecisionRecordError("Decision-record dossier identity must be text.")
    if type(record.ruleset_version) is not str:
        raise DecisionRecordError("Decision-record ruleset version must be text.")
    if type(record.tool_version) is not str or not record.tool_version.strip():
        raise DecisionRecordError("Decision records require an explicit non-empty tool version.")
    _require_tuple(record.evidence_links, "Decision-record evidence links")
    _require_tuple(record.unresolved_gaps, "Decision-record unresolved gaps")
    _require_tuple(record.reassessment_triggers, "Decision-record reassessment triggers")

    dossier_payload = canonical_dossier_dict(record.dossier)
    if record.dossier_schema_version != record.dossier.schema_version:
        raise DecisionRecordError("Decision-record dossier schema version is inconsistent.")
    expected_dossier_identity = dossier_content_identity(record.dossier)
    if record.dossier_content_identity != expected_dossier_identity:
        raise DecisionRecordError("Decision-record dossier identity is inconsistent.")

    assessment_payload = _assessment_dict(record.assessment)
    if record.assessment.schema_version != record.dossier_schema_version:
        raise DecisionRecordError("Decision-record assessment schema version is inconsistent.")
    if (
        record.ruleset_version != RULESET_VERSION
        or record.assessment.ruleset_version != record.ruleset_version
        or record.assessment.prerequisite_evaluation.ruleset_version != record.ruleset_version
        or record.assessment.ordered_elimination_evaluation.ruleset_version
        != record.ruleset_version
    ):
        raise DecisionRecordError("Decision-record ruleset versions are inconsistent.")
    expected_assessment = evaluate_assessment(record.dossier)
    if record.assessment != expected_assessment:
        raise DecisionRecordError("Decision-record assessment is inconsistent with its dossier.")

    expected_links = _expected_evidence_links(record.dossier)
    if record.evidence_links != expected_links:
        raise DecisionRecordError("Decision-record evidence links are inconsistent.")
    _validate_resolved_citations(
        dossier_payload,
        assessment_payload,
        {link.evidence_id for link in expected_links},
    )

    if record.unresolved_gaps != _unresolved_gaps(record.assessment):
        raise DecisionRecordError("Decision-record unresolved gaps are inconsistent.")
    if record.reassessment_triggers != _reassessment_triggers(record.dossier):
        raise DecisionRecordError("Decision-record reassessment triggers are inconsistent.")
    for link in record.evidence_links:
        _evidence_link_dict(link)
    for gap in record.unresolved_gaps:
        _gap_dict(gap)
    for trigger in record.reassessment_triggers:
        _trigger_dict(trigger)
    return dossier_payload, assessment_payload


def compose_decision_record(dossier: Dossier, *, tool_version: str) -> DecisionRecord:
    """Compose the canonical semantic record for one validated typed dossier."""
    if type(tool_version) is not str or not tool_version.strip():
        raise DecisionRecordError("Decision records require an explicit non-empty tool version.")
    dossier_payload = canonical_dossier_dict(dossier)
    assessment = evaluate_assessment(dossier)
    assessment_payload = _assessment_dict(assessment)
    links = _expected_evidence_links(dossier)
    _validate_resolved_citations(
        dossier_payload,
        assessment_payload,
        {link.evidence_id for link in links},
    )
    record = DecisionRecord(
        record_schema_version=RECORD_SCHEMA_VERSION,
        dossier_schema_version=dossier.schema_version,
        dossier_content_identity=dossier_content_identity(dossier),
        ruleset_version=assessment.ruleset_version,
        tool_version=tool_version,
        dossier=dossier,
        assessment=assessment,
        evidence_links=links,
        unresolved_gaps=_unresolved_gaps(assessment),
        reassessment_triggers=_reassessment_triggers(dossier),
    )
    _validate_record(record)
    return record


def canonical_decision_record_dict(record: DecisionRecord) -> JsonObject:
    """Return one complete record snapshot as canonical JSON-compatible data."""
    dossier_payload, assessment_payload = _validate_record(record)
    links: JsonObject = {
        link.evidence_id: _evidence_link_dict(link) for link in record.evidence_links
    }
    if len(links) != len(record.evidence_links):
        raise DecisionRecordError("Duplicate evidence links cannot be canonicalized.")
    return {
        "assessment": assessment_payload,
        "dossier": dossier_payload,
        "dossier_content_identity": record.dossier_content_identity,
        "dossier_schema_version": record.dossier_schema_version,
        "evidence_links": links,
        "reassessment_triggers": [
            _trigger_dict(trigger) for trigger in record.reassessment_triggers
        ],
        "record_schema_version": record.record_schema_version,
        "ruleset_version": record.ruleset_version,
        "tool_version": record.tool_version,
        "unresolved_gaps": [_gap_dict(gap) for gap in record.unresolved_gaps],
    }


def canonical_decision_record_bytes(record: DecisionRecord) -> bytes:
    """Return strict canonical JSON bytes for one in-memory decision record."""
    return canonical_json_bytes(canonical_decision_record_dict(record))
