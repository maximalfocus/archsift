"""Canonical content-addressed decision records for current typed inputs."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum, StrEnum
from hashlib import sha256
from typing import Any, TypeAlias, TypeVar, cast

from archsift.artefacts import EvidenceArtefactIdentity
from archsift.canonical import (
    CanonicalizationError,
    JsonObject,
    JsonValue,
    canonical_dossier_dict,
    canonical_json_bytes,
    dossier_content_identity,
    evidence_content_identities,
)
from archsift.case_view import CaseKnowledgeView
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
from archsift.knowledge_graph import GRAPH_SCHEMA_VERSION
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
    EvidenceArtefactRoot,
    EvidenceKind,
    HardVetoStatus,
    MissingEvidence,
    is_credible_support,
)

RECORD_SCHEMA_VERSION = 4
CONFIGURATION_SCHEMA_VERSION = 1

_EnumT = TypeVar("_EnumT", bound=Enum)


class DecisionRecordError(CanonicalizationError):
    """A decision record cannot be composed or represented without ambiguity."""


class UnresolvedGapSource(StrEnum):
    """The deterministic evaluation stage that exposed an unresolved gap."""

    PREREQUISITE = "prerequisite"
    DECISION = "decision"


@dataclass(frozen=True, slots=True)
class AssessmentConfigurationEntry:
    """One canonical decision-affecting configuration value."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class AssessmentConfiguration:
    """Versioned configuration included in final decision-record identity."""

    schema_version: int = CONFIGURATION_SCHEMA_VERSION
    entries: tuple[AssessmentConfigurationEntry, ...] = ()


DEFAULT_ASSESSMENT_CONFIGURATION = AssessmentConfiguration()


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """One canonical evidence-ledger identity bound into a decision record."""

    evidence_id: str
    kind: EvidenceKind
    content_identity: str
    decision_bearing: bool


@dataclass(frozen=True, slots=True)
class GraphEntryReference:
    """One finding-relevant reusable entry bound by semantic ID and content."""

    id: str
    content_identity: str


@dataclass(frozen=True, slots=True)
class GraphUse:
    """Exact reusable graph input that supported already-emitted findings."""

    graph_schema_version: int
    graph_version: str
    graph_snapshot_content_identity: str
    case_view_content_identity: str
    supported_finding_rule_ids: tuple[str, ...]
    finding_relevant_nodes: tuple[GraphEntryReference, ...]
    finding_relevant_relations: tuple[GraphEntryReference, ...]


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
    counterpart: str | None = None


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
    action_ids: tuple[str, ...]


UnresolvedGap: TypeAlias = PrerequisiteGap | DecisionGap


@dataclass(frozen=True, slots=True)
class ReassessmentTrigger:
    """One authored observation that can trigger reassessment.

    A trigger for recorded context (an entry no decision field cites) is kept
    visible but is not presented as blocking (FR-004).
    """

    evidence_id: str
    kind: EvidenceKind
    observation: str
    decision_bearing: bool


@dataclass(frozen=True, slots=True)
class EnvelopeAuthority:
    """One represented candidate's declared authority over one task action (FR-019)."""

    candidate_id: str
    control_class: ControlClass
    retained_human_control_ids: tuple[str, ...]
    omitted_human_control_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnvelopeEntry:
    """The recorded assistance boundary for one task action (FR-019)."""

    action_id: str
    consequential: bool
    person_required: bool
    mandatory_human_control_ids: tuple[str, ...]
    active_hard_veto_ids: tuple[str, ...]
    declared_authorities: tuple[EnvelopeAuthority, ...]
    evidence_ids: tuple[str, ...]
    rule_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplacedControl:
    """A consequential action a candidate proposes to act on without a retained control."""

    candidate_id: str
    action_id: str
    human_control_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssistanceEnvelope:
    """Per-action boundary statement derived only from recorded facts (FR-019).

    The envelope reports declared authority; it never invents permitted
    activity, selects a class, satisfies a prerequisite, or promotes a class.
    """

    entries: tuple[EnvelopeEntry, ...]
    human_decision_retained: bool
    replaced_controls: tuple[ReplacedControl, ...]


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Immutable content-addressed record for the current typed inputs."""

    record_schema_version: int
    record_content_identity: str
    dossier_schema_version: int
    dossier_content_identity: str
    ruleset_version: str
    tool_version: str
    configuration: AssessmentConfiguration
    configuration_content_identity: str
    dossier: Dossier
    assessment: AssessmentEvaluation
    evidence_links: tuple[EvidenceLink, ...]
    artefact_links: tuple[EvidenceArtefactIdentity, ...]
    unresolved_gaps: tuple[UnresolvedGap, ...]
    reassessment_triggers: tuple[ReassessmentTrigger, ...]
    graph_use: GraphUse | None = None
    assistance_envelope: AssistanceEnvelope | None = None


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


def _require_non_empty_string(value: object, label: str) -> str:
    text = _require_string(value, label)
    if not text.strip():
        raise DecisionRecordError(f"{label} must be non-empty text for decision records.")
    return text


def _require_content_identity(value: object, label: str) -> str:
    identity = _require_string(value, label)
    if (
        len(identity) != 71
        or not identity.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in identity[7:])
    ):
        raise DecisionRecordError(f"{label} must be a lowercase SHA-256 content identity.")
    return identity


def _content_identity(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


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
        (
            "block",
            "require-evidence",
            "support-candidate",
            "constrain-autonomy",
            "non-decisive",
        ),
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
        "counterpart",
    )
    _checked_dataclass(value, AssessmentPrerequisiteFinding, expected)
    _require_string(value.rule_id, "Prerequisite-finding rule_id")
    _require_string(value.field, "Prerequisite-finding field")
    _require_string(value.requirement, "Prerequisite-finding requirement")
    _require_string(value.message, "Prerequisite-finding message")
    _require_string(value.consequence, "Prerequisite-finding consequence")
    _require_string(value.remediation, "Prerequisite-finding remediation")
    if value.counterpart is not None:
        _require_string(value.counterpart, "Prerequisite-finding counterpart")
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
        "action_ids",
    )
    _checked_dataclass(value, DecisionFinding, expected)
    _require_string(value.rule_id, "Decision-finding rule_id")
    _require_string(value.requirement, "Decision-finding requirement")
    _require_string(value.criterion_id, "Decision-finding criterion_id")
    _require_string(value.message, "Decision-finding message")
    _require_string(value.consequence, "Decision-finding consequence")
    _rule_effect(value.effect)
    if value.candidate_id is None:
        if value.control_class is not None:
            raise DecisionRecordError(
                "A decision finding without a candidate must also have no control class."
            )
    else:
        _require_string(value.candidate_id, "Decision-finding candidate_id")
        if value.control_class is None:
            raise DecisionRecordError(
                "A decision finding with a candidate must also have a control class."
            )
        _control_class(value.control_class)
    _enum_value(
        value.criterion_kind,
        CriterionKind,
        (
            "outcome",
            "constraint",
            "authority",
            "hard-veto",
            "human-control",
            "agency-question",
            "residual-case",
            "derived-agency",
        ),
    )
    _require_string_tuple(value.evidence_ids, "Decision-finding evidence IDs")
    _require_string_tuple(value.action_ids, "Decision-finding action IDs")
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


def _configuration_dict(value: AssessmentConfiguration) -> JsonObject:
    _checked_dataclass(value, AssessmentConfiguration, ("schema_version", "entries"))
    if (
        type(value.schema_version) is not int
        or value.schema_version != CONFIGURATION_SCHEMA_VERSION
    ):
        raise DecisionRecordError("Unsupported assessment-configuration schema version.")
    entries = _require_tuple(value.entries, "Assessment-configuration entries")
    rendered: list[JsonValue] = []
    previous_key: str | None = None
    for entry in entries:
        _checked_dataclass(entry, AssessmentConfigurationEntry, ("key", "value"))
        key = _require_non_empty_string(entry.key, "Assessment-configuration key")
        _require_non_empty_string(entry.value, "Assessment-configuration value")
        if previous_key is not None and key <= previous_key:
            raise DecisionRecordError(
                "Assessment-configuration entries must have unique canonical key order."
            )
        previous_key = key
        rendered.append({"key": key, "value": entry.value})
    return {"entries": rendered, "schema_version": value.schema_version}


def assessment_configuration_content_identity(value: AssessmentConfiguration) -> str:
    """Return the canonical identity of one validated assessment configuration."""
    return _content_identity(canonical_json_bytes(_configuration_dict(value)))


def _evidence_link_dict(value: EvidenceLink) -> JsonObject:
    _checked_dataclass(
        value, EvidenceLink, ("evidence_id", "kind", "content_identity", "decision_bearing")
    )
    _require_non_empty_string(value.evidence_id, "Evidence-link evidence_id")
    _require_content_identity(value.content_identity, "Evidence-link content_identity")
    if type(value.decision_bearing) is not bool:
        raise DecisionRecordError("Evidence-link decision_bearing must be a boolean.")
    return {
        "content_identity": value.content_identity,
        "decision_bearing": value.decision_bearing,
        "evidence_id": value.evidence_id,
        "kind": _enum_value(
            value.kind,
            EvidenceKind,
            ("observed", "assumption", "estimate", "missing"),
        ),
    }


def _assessment_finding_rule_ids(value: AssessmentEvaluation) -> set[str]:
    return {
        finding.rule_id
        for finding in value.prerequisite_evaluation.findings
        if finding.evidence_ids
    } | {
        finding.rule_id
        for finding in value.ordered_elimination_evaluation.findings
        if finding.evidence_ids
    }


def _graph_entry_reference_dict(value: GraphEntryReference, label: str) -> JsonObject:
    _checked_dataclass(value, GraphEntryReference, ("id", "content_identity"))
    _require_non_empty_string(value.id, f"{label} id")
    _require_content_identity(value.content_identity, f"{label} content identity")
    return {"content_identity": value.content_identity, "id": value.id}


def _graph_references(
    values: object,
    *,
    label: str,
) -> tuple[GraphEntryReference, ...]:
    references = cast(tuple[GraphEntryReference, ...], _require_tuple(values, label))
    identifiers: list[str] = []
    for reference in references:
        _graph_entry_reference_dict(reference, label)
        identifiers.append(reference.id)
    if identifiers != sorted(set(identifiers)):
        raise DecisionRecordError(f"{label} require unique canonical semantic-ID order.")
    return references


def _graph_use_dict(value: GraphUse, assessment: AssessmentEvaluation) -> JsonObject:
    expected = (
        "graph_schema_version",
        "graph_version",
        "graph_snapshot_content_identity",
        "case_view_content_identity",
        "supported_finding_rule_ids",
        "finding_relevant_nodes",
        "finding_relevant_relations",
    )
    _checked_dataclass(value, GraphUse, expected)
    if value.graph_schema_version != GRAPH_SCHEMA_VERSION:
        raise DecisionRecordError("Unsupported graph-use schema version.")
    version = _require_non_empty_string(value.graph_version, "Graph-use graph version")
    if (
        len(version) != 68
        or not version.startswith("gv1:")
        or any(character not in "0123456789abcdef" for character in version[4:])
    ):
        raise DecisionRecordError("Graph-use graph version is not an immutable v1 version.")
    _require_content_identity(
        value.graph_snapshot_content_identity,
        "Graph-use snapshot content identity",
    )
    _require_content_identity(value.case_view_content_identity, "Graph-use case-view identity")
    supported = _require_string_tuple(
        value.supported_finding_rule_ids,
        "Graph-use supported finding rule IDs",
    )
    if not supported or list(supported) != sorted(set(supported)):
        raise DecisionRecordError(
            "Graph-use supported finding rule IDs require non-empty canonical unique order."
        )
    if not set(supported).issubset(_assessment_finding_rule_ids(assessment)):
        raise DecisionRecordError(
            "Graph use names a finding rule ID not emitted with case evidence by the assessment."
        )
    nodes = _graph_references(value.finding_relevant_nodes, label="Graph-use node references")
    relations = _graph_references(
        value.finding_relevant_relations,
        label="Graph-use relation references",
    )
    if not nodes or not relations:
        raise DecisionRecordError(
            "Graph use requires a complete finding-relevant node and relation trace."
        )
    return {
        "case_view_content_identity": value.case_view_content_identity,
        "finding_relevant_nodes": [
            _graph_entry_reference_dict(item, "Graph-use node reference") for item in nodes
        ],
        "finding_relevant_relations": [
            _graph_entry_reference_dict(item, "Graph-use relation reference") for item in relations
        ],
        "graph_schema_version": value.graph_schema_version,
        "graph_snapshot_content_identity": value.graph_snapshot_content_identity,
        "graph_version": value.graph_version,
        "supported_finding_rule_ids": list(supported),
    }


def _view_references(value: object, *, label: str) -> tuple[GraphEntryReference, ...]:
    if type(value) is not list:
        raise DecisionRecordError(f"Case view {label} must be an array.")
    references: list[GraphEntryReference] = []
    for raw in value:
        if type(raw) is not dict or set(raw) != {"content_identity", "id"}:
            raise DecisionRecordError(f"Case view {label} has an unsupported entry contract.")
        item = cast(dict[str, object], raw)
        identifier = _require_non_empty_string(item["id"], f"Case-view {label} id")
        identity = _require_content_identity(
            item["content_identity"], f"Case-view {label} content identity"
        )
        references.append(GraphEntryReference(identifier, identity))
    return tuple(references)


def _graph_use_from_case_view(
    view: CaseKnowledgeView,
    assessment: AssessmentEvaluation,
) -> GraphUse:
    if type(view) is not CaseKnowledgeView or type(view.content) is not dict:
        raise DecisionRecordError("Graph-supported decision records require a typed case view.")
    expected_identity = _content_identity(canonical_json_bytes(view.content))
    if view.content_identity != expected_identity:
        raise DecisionRecordError("Case-view content identity is inconsistent.")
    content = view.content
    requested = content.get("case_finding_ids")
    traces = content.get("reusable_claim_traces")
    if type(requested) is not list or not all(type(item) is str for item in requested):
        raise DecisionRecordError("Case-view finding IDs must be an array of strings.")
    emitted = _assessment_finding_rule_ids(assessment)
    if not set(cast(list[str], requested)).issubset(emitted):
        raise DecisionRecordError(
            "Case view names a finding rule ID not emitted with case evidence by the assessment."
        )
    if type(traces) is not list:
        raise DecisionRecordError("Case-view reusable claim traces must be an array.")
    supported: set[str] = set()
    for raw in traces:
        if type(raw) is not dict:
            raise DecisionRecordError("Case-view reusable claim trace must be an object.")
        finding_ids = raw.get("case_finding_ids")
        paths = raw.get("rule_paths")
        if type(finding_ids) is not list or not all(type(item) is str for item in finding_ids):
            raise DecisionRecordError("Case-view trace finding IDs must be strings.")
        if finding_ids and type(paths) is list and paths:
            supported.update(cast(list[str], finding_ids))
    if not supported:
        raise DecisionRecordError(
            "Case view has no complete reusable-claim to emitted-finding trace."
        )
    schema = content.get("graph_schema_version")
    version = content.get("graph_version")
    snapshot_identity = content.get("graph_snapshot_content_identity")
    if type(schema) is not int or type(version) is not str or type(snapshot_identity) is not str:
        raise DecisionRecordError("Case view has incomplete graph identity fields.")
    graph_use = GraphUse(
        graph_schema_version=schema,
        graph_version=version,
        graph_snapshot_content_identity=snapshot_identity,
        case_view_content_identity=view.content_identity,
        supported_finding_rule_ids=tuple(sorted(supported)),
        finding_relevant_nodes=_view_references(
            content.get("finding_relevant_nodes"), label="finding-relevant nodes"
        ),
        finding_relevant_relations=_view_references(
            content.get("finding_relevant_relations"), label="finding-relevant relations"
        ),
    )
    _graph_use_dict(graph_use, assessment)
    return graph_use


def _artefact_link_dict(value: EvidenceArtefactIdentity) -> JsonObject:
    expected = (
        "evidence_id",
        "artefact_id",
        "root",
        "path",
        "byte_length",
        "content_identity",
        "registration_id",
        "registration_content_identity",
        "declared_material_type",
        "repository_commit",
        "repository_logical_path",
    )
    _checked_dataclass(value, EvidenceArtefactIdentity, expected)
    _require_non_empty_string(value.evidence_id, "Artefact-link evidence_id")
    _require_non_empty_string(value.artefact_id, "Artefact-link artefact_id")
    _require_non_empty_string(value.path, "Artefact-link path")
    if type(value.byte_length) is not int or value.byte_length < 0:
        raise DecisionRecordError("Artefact-link byte_length must be a non-negative integer.")
    _require_content_identity(value.content_identity, "Artefact-link content_identity")
    registration_values = (
        value.registration_content_identity,
        value.declared_material_type,
    )
    if value.registration_id is None:
        provenance = (
            *registration_values,
            value.repository_commit,
            value.repository_logical_path,
        )
        if any(item is not None for item in provenance):
            raise DecisionRecordError(
                "Unregistered artefact links cannot carry registration provenance."
            )
    else:
        _require_non_empty_string(value.registration_id, "Artefact-link registration_id")
        _require_content_identity(
            value.registration_content_identity,
            "Artefact-link registration_content_identity",
        )
        _require_non_empty_string(
            value.declared_material_type,
            "Artefact-link declared_material_type",
        )
        if value.repository_commit is not None:
            _require_non_empty_string(
                value.repository_commit,
                "Artefact-link repository_commit",
            )
        if value.repository_logical_path is not None:
            _require_non_empty_string(
                value.repository_logical_path,
                "Artefact-link repository_logical_path",
            )
    return {
        "artefact_id": value.artefact_id,
        "byte_length": value.byte_length,
        "content_identity": value.content_identity,
        "evidence_id": value.evidence_id,
        "path": value.path,
        "declared_material_type": value.declared_material_type,
        "registration_content_identity": value.registration_content_identity,
        "registration_id": value.registration_id,
        "repository_commit": value.repository_commit,
        "repository_logical_path": value.repository_logical_path,
        "root": _enum_value(
            value.root,
            EvidenceArtefactRoot,
            ("workspace", "external"),
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
            "counterpart",
        )
        _checked_dataclass(value, PrerequisiteGap, expected)
        _require_string(value.rule_id, "Prerequisite-gap rule_id")
        _require_string(value.field, "Prerequisite-gap field")
        _require_string(value.requirement, "Prerequisite-gap requirement")
        _require_string(value.message, "Prerequisite-gap message")
        _require_string(value.consequence, "Prerequisite-gap consequence")
        _require_string(value.remediation, "Prerequisite-gap remediation")
        if value.counterpart is not None:
            _require_string(value.counterpart, "Prerequisite-gap counterpart")
        _require_string_tuple(value.evidence_ids, "Prerequisite-gap evidence IDs")
        return {
            "consequence": value.consequence,
            "counterpart": value.counterpart,
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
            "action_ids",
        )
        _checked_dataclass(value, DecisionGap, expected)
        _require_string(value.rule_id, "Decision-gap rule_id")
        _require_string(value.requirement, "Decision-gap requirement")
        _require_string(value.candidate_id, "Decision-gap candidate_id")
        _require_string(value.criterion_id, "Decision-gap criterion_id")
        _require_string(value.message, "Decision-gap message")
        _require_string(value.consequence, "Decision-gap consequence")
        _require_string_tuple(value.evidence_ids, "Decision-gap evidence IDs")
        _require_string_tuple(value.action_ids, "Decision-gap action IDs")
        return {
            "action_ids": list(value.action_ids),
            "candidate_id": value.candidate_id,
            "consequence": value.consequence,
            "control_class": _control_class(value.control_class),
            "criterion_id": value.criterion_id,
            "criterion_kind": _enum_value(
                value.criterion_kind,
                CriterionKind,
                (
                    "outcome",
                    "constraint",
                    "authority",
                    "hard-veto",
                    "human-control",
                    "agency-question",
                    "residual-case",
                    "derived-agency",
                ),
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
        ("evidence_id", "kind", "observation", "decision_bearing"),
    )
    _require_string(value.evidence_id, "Reassessment-trigger evidence_id")
    _require_string(value.observation, "Reassessment-trigger observation")
    if type(value.decision_bearing) is not bool:
        raise DecisionRecordError("Reassessment-trigger decision_bearing must be a boolean.")
    kind = _enum_value(
        value.kind,
        EvidenceKind,
        ("observed", "assumption", "estimate", "missing"),
    )
    if value.kind not in {EvidenceKind.ASSUMPTION, EvidenceKind.MISSING}:
        raise DecisionRecordError("Unsupported evidence kind for a reassessment trigger.")
    return {
        "decision_bearing": value.decision_bearing,
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
            counterpart=finding.counterpart,
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
            action_ids=finding.action_ids,
        )
        for finding in assessment.ordered_elimination_evaluation.findings
        if finding.effect is RuleEffect.REQUIRE_EVIDENCE
        and finding.candidate_id is not None
        and finding.control_class is not None
    )
    return (*prerequisite_gaps, *decision_gaps)


def decision_bearing_evidence_ids(dossier: Dossier) -> frozenset[str]:
    """Return the evidence IDs that at least one decision field cites (FR-004).

    Citations are collected from every dossier field outside the ledger itself,
    so the set is exhaustive over the schema by construction.
    """
    payload = {
        key: value for key, value in canonical_dossier_dict(dossier).items() if key != "evidence"
    }
    return frozenset(_collect_evidence_citations(payload))


def _reassessment_triggers(dossier: Dossier) -> tuple[ReassessmentTrigger, ...]:
    cited = decision_bearing_evidence_ids(dossier)
    triggers: list[ReassessmentTrigger] = []
    for entry in sorted(dossier.evidence, key=lambda item: item.id):
        if type(entry) is AssumptionEvidence:
            triggers.append(
                ReassessmentTrigger(
                    evidence_id=entry.id,
                    kind=EvidenceKind.ASSUMPTION,
                    observation=entry.falsified_by,
                    decision_bearing=entry.id in cited,
                )
            )
        elif type(entry) is MissingEvidence:
            triggers.append(
                ReassessmentTrigger(
                    evidence_id=entry.id,
                    kind=EvidenceKind.MISSING,
                    observation=entry.resolved_by,
                    decision_bearing=entry.id in cited,
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
    cited = decision_bearing_evidence_ids(dossier)
    return tuple(
        EvidenceLink(
            evidence_id=identifier,
            kind=entries[identifier].kind,
            content_identity=identity,
            decision_bearing=identifier in cited,
        )
        for identifier, identity in identities.items()
    )


def _expected_artefact_contract(
    dossier: Dossier,
) -> tuple[
    tuple[str, str, EvidenceArtefactRoot, str, str | None, str | None],
    ...,
]:
    contract = tuple(
        sorted(
            (
                (
                    evidence.id,
                    reference.id,
                    reference.root,
                    reference.path,
                    reference.registration_id,
                    reference.registration_logical_path,
                )
                for evidence in dossier.evidence
                for reference in evidence.artefacts
            ),
            key=lambda item: (item[0], item[1]),
        )
    )
    pairs = [(item[0], item[1]) for item in contract]
    if len(pairs) != len(set(pairs)):
        raise DecisionRecordError("Decision-record artefact references contain duplicate ID pairs.")
    return contract


def _validated_artefact_links(
    dossier: Dossier,
    links: object,
) -> tuple[EvidenceArtefactIdentity, ...]:
    values = _require_tuple(links, "Decision-record artefact links")
    typed = cast(tuple[EvidenceArtefactIdentity, ...], values)
    for value in typed:
        _artefact_link_dict(value)
    pairs = [(value.evidence_id, value.artefact_id) for value in typed]
    if pairs != sorted(pairs) or len(pairs) != len(set(pairs)):
        raise DecisionRecordError(
            "Decision-record artefact links require unique canonical evidence/artefact order."
        )
    registrations: dict[str, tuple[str | None, str | None, str | None]] = {}
    for value in typed:
        if value.registration_id is None:
            continue
        registration_contract = (
            value.registration_content_identity,
            value.declared_material_type,
            value.repository_commit,
        )
        previous = registrations.setdefault(value.registration_id, registration_contract)
        if previous != registration_contract:
            raise DecisionRecordError(
                "One registration ID cannot carry conflicting immutable provenance."
            )
    actual = tuple(
        (
            value.evidence_id,
            value.artefact_id,
            value.root,
            value.path,
            value.registration_id,
            value.repository_logical_path,
        )
        for value in typed
    )
    if actual != _expected_artefact_contract(dossier):
        raise DecisionRecordError(
            "Decision-record artefact links do not exactly match the dossier references."
        )
    return typed


_CONTROL_RULE_IDS = ("mandatory-human-control-omitted", "mandatory-human-control-retained")
_VETO_RULE_IDS = ("active-veto-blocks-candidate",)


def derive_assistance_envelope(dossier: Dossier) -> AssistanceEnvelope | None:
    """Derive the FR-019 per-action assistance envelope, or None where it does not apply.

    Inputs are only the recorded task boundary, consequentiality, active hard
    vetoes, mandatory human controls, and declared candidate authority. Nothing
    here reads a verdict or changes one.
    """
    task = dossier.task
    autonomy = dossier.autonomy_permission
    if task is None or autonomy is None:
        return None
    if not autonomy.hard_vetoes and not autonomy.mandatory_human_controls:
        return None
    evidence = {entry.id: entry for entry in dossier.evidence}
    controls = sorted(autonomy.mandatory_human_controls, key=lambda item: item.id)
    active_vetoes = sorted(
        (veto for veto in autonomy.hard_vetoes if veto.status is HardVetoStatus.ACTIVE),
        key=lambda item: item.id,
    )
    candidates = (
        sorted(dossier.candidate_comparison.candidates, key=lambda item: item.id)
        if dossier.candidate_comparison is not None
        else []
    )
    entries: list[EnvelopeEntry] = []
    replaced: list[ReplacedControl] = []
    retained_everywhere = True
    for action in task.actions:
        bound_controls = [control for control in controls if action.id in control.action_ids]
        bound_vetoes = [veto for veto in active_vetoes if action.id in veto.action_ids]
        evidenced_control = any(
            any(
                is_credible_support(evidence.get(identifier)) for identifier in control.evidence_ids
            )
            for control in bound_controls
        )
        authorities: list[EnvelopeAuthority] = []
        for candidate in candidates:
            authority = candidate.authority
            if authority is None or action.id not in authority.action_ids:
                continue
            retained = tuple(
                control.id
                for control in bound_controls
                if control.id in authority.retained_human_control_ids
            )
            omitted = tuple(
                control.id
                for control in bound_controls
                if control.id not in authority.retained_human_control_ids
            )
            authorities.append(
                EnvelopeAuthority(
                    candidate_id=candidate.id,
                    control_class=candidate.control_class,
                    retained_human_control_ids=retained,
                    omitted_human_control_ids=omitted,
                    evidence_ids=tuple(sorted(set(authority.evidence_ids))),
                )
            )
            if action.consequential and (omitted or not bound_controls):
                replaced.append(
                    ReplacedControl(
                        candidate_id=candidate.id, action_id=action.id, human_control_ids=omitted
                    )
                )
        if action.consequential and not evidenced_control:
            retained_everywhere = False
        rule_ids = (
            *(_CONTROL_RULE_IDS if bound_controls else ()),
            *(_VETO_RULE_IDS if bound_vetoes else ()),
        )
        entries.append(
            EnvelopeEntry(
                action_id=action.id,
                consequential=action.consequential,
                person_required=bool(bound_controls or bound_vetoes),
                mandatory_human_control_ids=tuple(control.id for control in bound_controls),
                active_hard_veto_ids=tuple(veto.id for veto in bound_vetoes),
                declared_authorities=tuple(authorities),
                evidence_ids=tuple(
                    sorted(
                        {
                            identifier
                            for control in bound_controls
                            for identifier in control.evidence_ids
                        }
                        | {identifier for veto in bound_vetoes for identifier in veto.evidence_ids}
                    )
                ),
                rule_ids=rule_ids,
            )
        )
    return AssistanceEnvelope(
        entries=tuple(entries),
        human_decision_retained=retained_everywhere and not replaced,
        replaced_controls=tuple(replaced),
    )


def _envelope_authority_dict(value: EnvelopeAuthority) -> JsonObject:
    _checked_dataclass(
        value,
        EnvelopeAuthority,
        (
            "candidate_id",
            "control_class",
            "retained_human_control_ids",
            "omitted_human_control_ids",
            "evidence_ids",
        ),
    )
    _require_non_empty_string(value.candidate_id, "Envelope authority candidate_id")
    return {
        "candidate_id": value.candidate_id,
        "control_class": _enum_value(
            value.control_class,
            ControlClass,
            (
                "human-owned-work",
                "process-redesign",
                "deterministic-automation",
                "fixed-ai-workflow",
                "agentic-control",
            ),
        ),
        "evidence_ids": list(
            _require_string_tuple(value.evidence_ids, "Envelope authority evidence IDs")
        ),
        "omitted_human_control_ids": list(
            _require_string_tuple(value.omitted_human_control_ids, "Envelope omitted controls")
        ),
        "retained_human_control_ids": list(
            _require_string_tuple(value.retained_human_control_ids, "Envelope retained controls")
        ),
    }


def _envelope_entry_dict(value: EnvelopeEntry) -> JsonObject:
    _checked_dataclass(
        value,
        EnvelopeEntry,
        (
            "action_id",
            "consequential",
            "person_required",
            "mandatory_human_control_ids",
            "active_hard_veto_ids",
            "declared_authorities",
            "evidence_ids",
            "rule_ids",
        ),
    )
    _require_non_empty_string(value.action_id, "Envelope entry action_id")
    if type(value.consequential) is not bool or type(value.person_required) is not bool:
        raise DecisionRecordError("Envelope entry flags must be booleans.")
    return {
        "action_id": value.action_id,
        "active_hard_veto_ids": list(
            _require_string_tuple(value.active_hard_veto_ids, "Envelope veto IDs")
        ),
        "consequential": value.consequential,
        "declared_authorities": [
            _envelope_authority_dict(item) for item in value.declared_authorities
        ],
        "evidence_ids": list(_require_string_tuple(value.evidence_ids, "Envelope evidence IDs")),
        "mandatory_human_control_ids": list(
            _require_string_tuple(value.mandatory_human_control_ids, "Envelope control IDs")
        ),
        "person_required": value.person_required,
        "rule_ids": list(_require_string_tuple(value.rule_ids, "Envelope rule IDs")),
    }


def _assistance_envelope_dict(value: AssistanceEnvelope) -> JsonObject:
    _checked_dataclass(
        value, AssistanceEnvelope, ("entries", "human_decision_retained", "replaced_controls")
    )
    if type(value.human_decision_retained) is not bool:
        raise DecisionRecordError("Envelope human_decision_retained must be a boolean.")
    replaced: list[JsonValue] = []
    for item in value.replaced_controls:
        _checked_dataclass(
            item, ReplacedControl, ("candidate_id", "action_id", "human_control_ids")
        )
        replaced.append(
            {
                "action_id": _require_non_empty_string(item.action_id, "Replaced control action"),
                "candidate_id": _require_non_empty_string(
                    item.candidate_id, "Replaced control candidate"
                ),
                "human_control_ids": list(
                    _require_string_tuple(item.human_control_ids, "Replaced control IDs")
                ),
            }
        )
    return {
        "entries": [_envelope_entry_dict(item) for item in value.entries],
        "human_decision_retained": value.human_decision_retained,
        "replaced_controls": replaced,
    }


def _identity_payload(
    record: DecisionRecord,
    dossier_payload: JsonObject,
    assessment_payload: JsonObject,
) -> JsonObject:
    links: JsonObject = {
        link.evidence_id: _evidence_link_dict(link) for link in record.evidence_links
    }
    if len(links) != len(record.evidence_links):
        raise DecisionRecordError("Duplicate evidence links cannot be canonicalized.")
    payload: JsonObject = {
        "artefact_links": [_artefact_link_dict(link) for link in record.artefact_links],
        "assessment": assessment_payload,
        "configuration": _configuration_dict(record.configuration),
        "configuration_content_identity": record.configuration_content_identity,
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
    if record.graph_use is not None:
        payload["graph_use"] = _graph_use_dict(record.graph_use, record.assessment)
    if record.assistance_envelope is not None:
        payload["assistance_envelope"] = _assistance_envelope_dict(record.assistance_envelope)
    return payload


def _validate_record(
    record: DecisionRecord,
    *,
    verify_record_identity: bool = True,
) -> JsonObject:
    expected_fields = (
        "record_schema_version",
        "record_content_identity",
        "dossier_schema_version",
        "dossier_content_identity",
        "ruleset_version",
        "tool_version",
        "configuration",
        "configuration_content_identity",
        "dossier",
        "assessment",
        "evidence_links",
        "artefact_links",
        "unresolved_gaps",
        "reassessment_triggers",
        "graph_use",
        "assistance_envelope",
    )
    _checked_dataclass(record, DecisionRecord, expected_fields)
    if (
        type(record.record_schema_version) is not int
        or record.record_schema_version != RECORD_SCHEMA_VERSION
    ):
        raise DecisionRecordError("Unsupported decision-record schema version.")
    if type(record.dossier_schema_version) is not int:
        raise DecisionRecordError("Decision-record dossier schema version must be an integer.")
    _require_content_identity(record.dossier_content_identity, "Decision-record dossier identity")
    _require_non_empty_string(record.ruleset_version, "Decision-record ruleset version")
    _require_non_empty_string(record.tool_version, "Decision-record tool version")
    _require_tuple(record.evidence_links, "Decision-record evidence links")
    _validated_artefact_links(record.dossier, record.artefact_links)
    _require_tuple(record.unresolved_gaps, "Decision-record unresolved gaps")
    _require_tuple(record.reassessment_triggers, "Decision-record reassessment triggers")
    if record.graph_use is not None:
        _graph_use_dict(record.graph_use, record.assessment)

    configuration_payload = _configuration_dict(record.configuration)
    expected_configuration_identity = _content_identity(canonical_json_bytes(configuration_payload))
    if record.configuration_content_identity != expected_configuration_identity:
        raise DecisionRecordError("Decision-record configuration identity is inconsistent.")

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
    if record.assistance_envelope != derive_assistance_envelope(record.dossier):
        raise DecisionRecordError("Decision-record assistance envelope is inconsistent.")
    for link in record.evidence_links:
        _evidence_link_dict(link)
    for gap in record.unresolved_gaps:
        _gap_dict(gap)
    for trigger in record.reassessment_triggers:
        _trigger_dict(trigger)

    payload = _identity_payload(record, dossier_payload, assessment_payload)
    expected_record_identity = _content_identity(canonical_json_bytes(payload))
    if verify_record_identity:
        _require_content_identity(
            record.record_content_identity, "Decision-record content identity"
        )
        if record.record_content_identity != expected_record_identity:
            raise DecisionRecordError("Decision-record content identity is inconsistent.")
    return payload


def compose_decision_record(
    dossier: Dossier,
    *,
    tool_version: str,
    artefact_identities: tuple[EvidenceArtefactIdentity, ...] = (),
    configuration: AssessmentConfiguration = DEFAULT_ASSESSMENT_CONFIGURATION,
    case_view: CaseKnowledgeView | None = None,
) -> DecisionRecord:
    """Compose a pure content-addressed record from already-resolved typed inputs."""
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
    _validated_artefact_links(dossier, artefact_identities)
    configuration_identity = assessment_configuration_content_identity(configuration)
    graph_use = _graph_use_from_case_view(case_view, assessment) if case_view is not None else None
    draft = DecisionRecord(
        record_schema_version=RECORD_SCHEMA_VERSION,
        record_content_identity="",
        dossier_schema_version=dossier.schema_version,
        dossier_content_identity=dossier_content_identity(dossier),
        ruleset_version=assessment.ruleset_version,
        tool_version=tool_version,
        configuration=configuration,
        configuration_content_identity=configuration_identity,
        dossier=dossier,
        assessment=assessment,
        evidence_links=links,
        artefact_links=artefact_identities,
        unresolved_gaps=_unresolved_gaps(assessment),
        reassessment_triggers=_reassessment_triggers(dossier),
        graph_use=graph_use,
        assistance_envelope=derive_assistance_envelope(dossier),
    )
    payload = _validate_record(draft, verify_record_identity=False)
    record = replace(
        draft,
        record_content_identity=_content_identity(canonical_json_bytes(payload)),
    )
    _validate_record(record)
    return record


def canonical_decision_record_identity_payload_bytes(record: DecisionRecord) -> bytes:
    """Return canonical bytes hashed for record identity, excluding only that identity."""
    return canonical_json_bytes(_validate_record(record))


def decision_record_content_identity(record: DecisionRecord) -> str:
    """Recompute and return the validated final decision-record identity."""
    return _content_identity(canonical_decision_record_identity_payload_bytes(record))


def canonical_decision_record_dict(record: DecisionRecord) -> JsonObject:
    """Return one complete content-addressed record as canonical JSON data."""
    payload = _validate_record(record)
    return {**payload, "record_content_identity": record.record_content_identity}


def canonical_decision_record_bytes(record: DecisionRecord) -> bytes:
    """Return strict canonical JSON bytes for one final decision record."""
    return canonical_json_bytes(canonical_decision_record_dict(record))
