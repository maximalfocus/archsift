"""Canonical schema-v1 dossier serialization and content identities."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from functools import cache
from hashlib import sha256
from types import UnionType
from typing import Any, TypeAlias, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    AutonomyAnswer,
    AutonomyPermission,
    AutonomyQuestion,
    Candidate,
    CandidateAuthority,
    CandidateComparison,
    CandidateConstraintTest,
    CandidateOutcomeTest,
    CandidatePairComparison,
    CandidateRole,
    CandidateTestResult,
    CaseIdentity,
    ComparisonDimension,
    ComparisonDimensions,
    ComparisonResult,
    ControlClass,
    DecisionArea,
    DecisionCondition,
    DecisionConditionStatus,
    Dossier,
    EstimateEvidence,
    Evidence,
    EvidenceArtefactReference,
    EvidenceArtefactRoot,
    EvidencedStatement,
    EvidenceKind,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    ResidualCase,
    TaskAction,
    TaskBoundary,
)

JsonScalar: TypeAlias = bool | int | str | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

_EnumT = TypeVar("_EnumT", bound=Enum)

_AGENCY_FIELDS = (
    "execution_steps_predefinable",
    "step_count_or_order_predictable",
    "runtime_tool_choice_required",
    "runtime_replanning_required",
    "environmental_feedback_available",
    "completion_independently_verifiable",
    "effects_independently_verifiable",
    "fixed_workflow_sufficient",
)
_AUTONOMY_FIELDS = (
    "actions_reversible",
    "failure_blast_radius_bounded",
    "regulatory_automation_permitted",
    "data_confidence_sufficient",
    "accountable_owner_assigned",
    "decision_path_auditable",
    "timely_human_intervention_available",
    "safe_degradation_available",
)
_DIMENSION_FIELDS = (
    "outcome_quality",
    "difficult_case_performance",
    "cost",
    "latency",
    "human_effort",
    "integration_burden",
    "security_exposure",
    "failure_impact",
    "operability",
    "evaluation_burden",
    "maintainability",
)


class CanonicalizationError(ValueError):
    """A typed value cannot be represented by the current canonical contract."""


def _checked_object(
    instance: object,
    expected_type: type[object],
    expected_fields: tuple[str, ...],
    values: JsonObject,
    *,
    extra_keys: tuple[str, ...] = (),
    omitted_keys: tuple[str, ...] = (),
) -> JsonObject:
    if type(instance) is not expected_type or not is_dataclass(instance):
        raise CanonicalizationError(
            f"Unsupported {expected_type.__name__} typed value for canonicalization."
        )
    actual_fields = tuple(field.name for field in fields(cast(Any, instance)))
    if actual_fields != expected_fields:
        raise CanonicalizationError(
            f"Unsupported {expected_type.__name__} field contract for canonicalization."
        )
    if not set(omitted_keys).issubset(expected_fields) or set(values) != (
        set(expected_fields) - set(omitted_keys)
    ) | set(extra_keys):
        raise CanonicalizationError(
            f"Incomplete {expected_type.__name__} canonical object contract."
        )
    return values


def _enum_value(
    value: _EnumT,
    enum_type: type[_EnumT],
    expected_values: tuple[str, ...],
) -> str:
    actual_values = tuple(member.value for member in enum_type)
    if type(value) is not enum_type or actual_values != expected_values:
        raise CanonicalizationError(
            f"Unsupported {enum_type.__name__} value contract for canonicalization."
        )
    raw = value.value
    if not isinstance(raw, str):
        raise CanonicalizationError(f"Unsupported {enum_type.__name__} non-string canonical value.")
    return raw


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("Canonical JSON object keys must be strings.")
        for item in value.values():
            _validate_json_value(item)
        return
    raise CanonicalizationError("Unsupported value in canonical JSON object.")


@cache
def _declared_fields(cls: type[Any]) -> dict[str, Any]:
    """Resolve the declared runtime field types for one dossier dataclass."""
    return get_type_hints(cls)


def _check_typed_value(value: object, declared: Any) -> None:
    """Enforce the declared Dossier/Evidence type graph before serialization.

    Validates exact runtime types for scalars, enums, dates, dataclasses,
    tuple containers, and unions so malformed programmatic dossiers fail
    closed with a deterministic CanonicalizationError instead of leaking
    built-in AttributeError/TypeError failures or schema-invalid JSON.
    """
    if declared is None or declared is type(None):
        if value is not None:
            raise CanonicalizationError("Unsupported None typed value for canonicalization.")
        return
    if declared is str or declared is int or declared is bool:
        if type(value) is not declared:
            raise CanonicalizationError(
                f"Unsupported {declared.__name__} typed value for canonicalization."
            )
        return
    if declared is date:
        if type(value) is not date:
            raise CanonicalizationError("Observed evidence requires a canonical date value.")
        return
    if isinstance(declared, type) and issubclass(declared, Enum):
        if type(value) is not declared:
            raise CanonicalizationError(
                f"Unsupported {declared.__name__} value contract for canonicalization."
            )
        return
    if isinstance(declared, type) and is_dataclass(declared):
        if type(value) is not declared:
            raise CanonicalizationError(
                f"Unsupported {declared.__name__} typed value for canonicalization."
            )
        hints = _declared_fields(declared)
        for field in fields(cast(Any, value)):
            _check_typed_value(getattr(value, field.name), hints[field.name])
        return
    origin = get_origin(declared)
    if origin is tuple:
        arguments = get_args(declared)
        if len(arguments) != 2 or arguments[1] is not Ellipsis:
            raise CanonicalizationError("Unsupported tuple typed value for canonicalization.")
        if type(value) is not tuple:
            raise CanonicalizationError("Unsupported tuple typed value for canonicalization.")
        for item in value:
            _check_typed_value(item, arguments[0])
        return
    if isinstance(declared, UnionType) or origin is Union:
        arguments = get_args(declared)
        if value is None:
            if any(member is type(None) for member in arguments):
                return
            raise CanonicalizationError("Unsupported None typed value for canonicalization.")
        members = tuple(member for member in arguments if member is not type(None))
        for member in members:
            member_origin = get_origin(member)
            if type(value) is member or (member_origin is tuple and type(value) is tuple):
                _check_typed_value(value, member)
                return
        if declared is Evidence:
            raise CanonicalizationError("Unsupported evidence subtype for canonicalization.")
        names = "|".join(member.__name__ for member in members)
        raise CanonicalizationError(f"Unsupported {names} typed value for canonicalization.")
    raise CanonicalizationError("Unsupported declared canonical type for canonicalization.")


def canonical_json_bytes(value: JsonValue) -> bytes:
    """Encode strict sorted-key JSON with ASCII escapes and one trailing LF."""
    _validate_json_value(value)
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:  # defensive boundary
        raise CanonicalizationError("Value cannot be encoded as canonical JSON.") from error
    return f"{text}\n".encode()


def _content_identity(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


def _case(value: CaseIdentity) -> JsonObject:
    expected = ("id", "title")
    return _checked_object(
        value,
        CaseIdentity,
        expected,
        {"id": value.id, "title": value.title},
    )


def _task_action(value: TaskAction) -> JsonObject:
    expected = ("id", "description", "consequential", "approval_boundary")
    return _checked_object(
        value,
        TaskAction,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "consequential": value.consequential,
            "approval_boundary": value.approval_boundary,
        },
    )


def _task(value: TaskBoundary) -> JsonObject:
    expected = (
        "operation",
        "starts_when",
        "completes_when",
        "accountable_owner",
        "actors",
        "systems_and_tools",
        "information_read",
        "actions",
        "exclusions",
    )
    return _checked_object(
        value,
        TaskBoundary,
        expected,
        {
            "operation": value.operation,
            "starts_when": value.starts_when,
            "completes_when": value.completes_when,
            "accountable_owner": value.accountable_owner,
            "actors": list(value.actors),
            "systems_and_tools": list(value.systems_and_tools),
            "information_read": list(value.information_read),
            "actions": [_task_action(action) for action in value.actions],
            "exclusions": list(value.exclusions),
        },
    )


def _evidenced_statement(value: EvidencedStatement) -> JsonObject:
    expected = ("statement", "evidence_ids")
    return _checked_object(
        value,
        EvidencedStatement,
        expected,
        {"statement": value.statement, "evidence_ids": list(value.evidence_ids)},
    )


def _problem_outcome(value: ProblemOutcome) -> JsonObject:
    expected = (
        "id",
        "description",
        "measure",
        "target",
        "baseline_id",
        "binding",
        "evidence_ids",
    )
    return _checked_object(
        value,
        ProblemOutcome,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "measure": value.measure,
            "target": value.target,
            "baseline_id": value.baseline_id,
            "binding": value.binding,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _problem_baseline(value: ProblemBaseline) -> JsonObject:
    expected = ("id", "description", "measure", "value", "evidence_ids")
    return _checked_object(
        value,
        ProblemBaseline,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "measure": value.measure,
            "value": value.value,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _problem_constraint(value: ProblemConstraint) -> JsonObject:
    expected = (
        "id",
        "description",
        "test",
        "required_result",
        "binding",
        "evidence_ids",
    )
    return _checked_object(
        value,
        ProblemConstraint,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "test": value.test,
            "required_result": value.required_result,
            "binding": value.binding,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _problem_value(value: ProblemValue) -> JsonObject:
    expected = (
        "outcomes",
        "baselines",
        "constraints",
        "affected_volume",
        "material_pain",
        "error_cost",
        "technology_limitation",
    )
    return _checked_object(
        value,
        ProblemValue,
        expected,
        {
            "outcomes": [_problem_outcome(item) for item in value.outcomes],
            "baselines": [_problem_baseline(item) for item in value.baselines],
            "constraints": [_problem_constraint(item) for item in value.constraints],
            "affected_volume": _evidenced_statement(value.affected_volume),
            "material_pain": _evidenced_statement(value.material_pain),
            "error_cost": _evidenced_statement(value.error_cost),
            "technology_limitation": _evidenced_statement(value.technology_limitation),
        },
    )


def _agency_question(value: AgencyQuestion) -> JsonObject:
    expected = ("answer", "rationale", "evidence_ids")
    return _checked_object(
        value,
        AgencyQuestion,
        expected,
        {
            "answer": _enum_value(value.answer, AgencyAnswer, ("yes", "no", "unknown")),
            "rationale": value.rationale,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _residual_case(value: ResidualCase) -> JsonObject:
    expected = ("id", "description", "fixed_workflow_failure", "evidence_ids")
    return _checked_object(
        value,
        ResidualCase,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "fixed_workflow_failure": value.fixed_workflow_failure,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _agency(value: AgencyNecessity) -> JsonObject:
    expected = (*_AGENCY_FIELDS, "residual_cases")
    values: JsonObject = {
        name: _agency_question(cast(AgencyQuestion, getattr(value, name)))
        for name in _AGENCY_FIELDS
    }
    values["residual_cases"] = [_residual_case(item) for item in value.residual_cases]
    return _checked_object(value, AgencyNecessity, expected, values)


def _autonomy_question(value: AutonomyQuestion) -> JsonObject:
    expected = ("answer", "rationale", "evidence_ids")
    return _checked_object(
        value,
        AutonomyQuestion,
        expected,
        {
            "answer": _enum_value(value.answer, AutonomyAnswer, ("yes", "no", "unknown")),
            "rationale": value.rationale,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _hard_veto(value: HardVeto) -> JsonObject:
    expected = (
        "id",
        "status",
        "condition",
        "consequence",
        "action_ids",
        "evidence_ids",
        "prohibited_control_classes",
    )
    values: JsonObject = {
        "id": value.id,
        "status": _enum_value(
            value.status,
            HardVetoStatus,
            ("active", "inactive", "unknown"),
        ),
        "condition": value.condition,
        "consequence": value.consequence,
        "action_ids": list(value.action_ids),
        "evidence_ids": list(value.evidence_ids),
    }
    if value.prohibited_control_classes is not None:
        values["prohibited_control_classes"] = [
            _enum_value(
                item,
                ControlClass,
                (
                    "human-owned-work",
                    "process-redesign",
                    "deterministic-automation",
                    "fixed-ai-workflow",
                    "agentic-control",
                ),
            )
            for item in value.prohibited_control_classes
        ]
    return _checked_object(
        value,
        HardVeto,
        expected,
        values,
        omitted_keys=("prohibited_control_classes",)
        if value.prohibited_control_classes is None
        else (),
    )


def _human_control(value: MandatoryHumanControl) -> JsonObject:
    expected = (
        "id",
        "description",
        "control_point",
        "responsible_role",
        "action_ids",
        "evidence_ids",
    )
    return _checked_object(
        value,
        MandatoryHumanControl,
        expected,
        {
            "id": value.id,
            "description": value.description,
            "control_point": value.control_point,
            "responsible_role": value.responsible_role,
            "action_ids": list(value.action_ids),
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _autonomy(value: AutonomyPermission) -> JsonObject:
    expected = (*_AUTONOMY_FIELDS, "hard_vetoes", "mandatory_human_controls")
    values: JsonObject = {
        name: _autonomy_question(cast(AutonomyQuestion, getattr(value, name)))
        for name in _AUTONOMY_FIELDS
    }
    values["hard_vetoes"] = [_hard_veto(item) for item in value.hard_vetoes]
    values["mandatory_human_controls"] = [
        _human_control(item) for item in value.mandatory_human_controls
    ]
    return _checked_object(value, AutonomyPermission, expected, values)


def _outcome_test(value: CandidateOutcomeTest) -> JsonObject:
    expected = ("outcome_id", "result", "rationale", "evidence_ids")
    return _checked_object(
        value,
        CandidateOutcomeTest,
        expected,
        {
            "outcome_id": value.outcome_id,
            "result": _enum_value(
                value.result,
                CandidateTestResult,
                ("meets", "fails", "unknown"),
            ),
            "rationale": value.rationale,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _constraint_test(value: CandidateConstraintTest) -> JsonObject:
    expected = ("constraint_id", "result", "rationale", "evidence_ids")
    return _checked_object(
        value,
        CandidateConstraintTest,
        expected,
        {
            "constraint_id": value.constraint_id,
            "result": _enum_value(
                value.result,
                CandidateTestResult,
                ("meets", "fails", "unknown"),
            ),
            "rationale": value.rationale,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _candidate_authority(value: CandidateAuthority) -> JsonObject:
    expected = ("action_ids", "retained_human_control_ids", "evidence_ids")
    return _checked_object(
        value,
        CandidateAuthority,
        expected,
        {
            "action_ids": list(value.action_ids),
            "retained_human_control_ids": list(value.retained_human_control_ids),
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _candidate(value: Candidate) -> JsonObject:
    expected = (
        "id",
        "name",
        "description",
        "control_class",
        "roles",
        "material_deviations",
        "outcome_tests",
        "constraint_tests",
        "authority",
    )
    values: JsonObject = {
        "id": value.id,
        "name": value.name,
        "description": value.description,
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
        "roles": [
            _enum_value(
                role,
                CandidateRole,
                (
                    "current-baseline",
                    "proposed",
                    "strongest-simpler",
                    "agentic-comparator",
                ),
            )
            for role in value.roles
        ],
        "material_deviations": list(value.material_deviations),
        "outcome_tests": [_outcome_test(item) for item in value.outcome_tests],
        "constraint_tests": [_constraint_test(item) for item in value.constraint_tests],
    }
    if value.authority is not None:
        values["authority"] = _candidate_authority(value.authority)
    return _checked_object(
        value,
        Candidate,
        expected,
        values,
        omitted_keys=("authority",) if value.authority is None else (),
    )


def _comparison_dimension(value: ComparisonDimension) -> JsonObject:
    expected = ("result", "rationale", "evidence_ids")
    return _checked_object(
        value,
        ComparisonDimension,
        expected,
        {
            "result": _enum_value(
                value.result,
                ComparisonResult,
                ("better", "equivalent", "worse", "unknown"),
            ),
            "rationale": value.rationale,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _comparison_dimensions(value: ComparisonDimensions) -> JsonObject:
    values: JsonObject = {
        name: _comparison_dimension(cast(ComparisonDimension, getattr(value, name)))
        for name in _DIMENSION_FIELDS
    }
    return _checked_object(value, ComparisonDimensions, _DIMENSION_FIELDS, values)


def _candidate_pair(value: CandidatePairComparison) -> JsonObject:
    expected = ("subject_candidate_id", "comparator_candidate_id", "dimensions")
    return _checked_object(
        value,
        CandidatePairComparison,
        expected,
        {
            "subject_candidate_id": value.subject_candidate_id,
            "comparator_candidate_id": value.comparator_candidate_id,
            "dimensions": _comparison_dimensions(value.dimensions),
        },
    )


def _candidate_comparison(value: CandidateComparison) -> JsonObject:
    expected = ("candidates", "comparisons")
    return _checked_object(
        value,
        CandidateComparison,
        expected,
        {
            "candidates": [_candidate(item) for item in value.candidates],
            "comparisons": [_candidate_pair(item) for item in value.comparisons],
        },
    )


def _decision_condition(value: DecisionCondition) -> JsonObject:
    expected = (
        "id",
        "target_control_class",
        "decision_area",
        "statement",
        "status",
        "resolved_by",
        "evidence_ids",
    )
    return _checked_object(
        value,
        DecisionCondition,
        expected,
        {
            "id": value.id,
            "target_control_class": _enum_value(
                value.target_control_class,
                ControlClass,
                (
                    "human-owned-work",
                    "process-redesign",
                    "deterministic-automation",
                    "fixed-ai-workflow",
                    "agentic-control",
                ),
            ),
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
            "statement": value.statement,
            "status": _enum_value(
                value.status,
                DecisionConditionStatus,
                ("met", "unmet"),
            ),
            "resolved_by": value.resolved_by,
            "evidence_ids": list(value.evidence_ids),
        },
    )


def _evidence_artefact(value: EvidenceArtefactReference) -> JsonObject:
    expected = ("id", "root", "path")
    return _checked_object(
        value,
        EvidenceArtefactReference,
        expected,
        {
            "id": value.id,
            "root": _enum_value(
                value.root,
                EvidenceArtefactRoot,
                ("workspace", "external"),
            ),
            "path": value.path,
        },
    )


def canonical_evidence_dict(entry: Evidence) -> JsonObject:
    """Return one complete schema-v1 evidence entry as canonical JSON data."""
    _check_typed_value(entry, Evidence)
    common: JsonObject = {
        "id": entry.id,
        "claim": entry.claim,
        "owner": entry.owner,
        "affects": [
            _enum_value(
                area,
                DecisionArea,
                (
                    "problem-value",
                    "agency-necessity",
                    "autonomy-permission",
                    "comparative-fit",
                ),
            )
            for area in entry.affects
        ],
        "artefacts": [_evidence_artefact(artefact) for artefact in entry.artefacts],
    }
    evidence_kind_values = ("observed", "assumption", "estimate", "missing")
    if type(entry) is ObservedEvidence:
        observed = entry
        if type(observed.observed_at) is not date:
            raise CanonicalizationError("Observed evidence requires a canonical date value.")
        values = {
            **common,
            "kind": _enum_value(observed.kind, EvidenceKind, evidence_kind_values),
            "provenance": observed.provenance,
            "observed_at": observed.observed_at.isoformat(),
        }
        return _checked_object(
            observed,
            ObservedEvidence,
            ("id", "claim", "owner", "affects", "provenance", "observed_at", "artefacts"),
            values,
            extra_keys=("kind",),
        )
    if type(entry) is AssumptionEvidence:
        assumption = entry
        values = {
            **common,
            "kind": _enum_value(assumption.kind, EvidenceKind, evidence_kind_values),
            "falsified_by": assumption.falsified_by,
        }
        return _checked_object(
            assumption,
            AssumptionEvidence,
            ("id", "claim", "owner", "affects", "falsified_by", "artefacts"),
            values,
            extra_keys=("kind",),
        )
    if type(entry) is EstimateEvidence:
        estimate = entry
        values = {
            **common,
            "kind": _enum_value(estimate.kind, EvidenceKind, evidence_kind_values),
            "method": estimate.method,
        }
        return _checked_object(
            estimate,
            EstimateEvidence,
            ("id", "claim", "owner", "affects", "method", "artefacts"),
            values,
            extra_keys=("kind",),
        )
    if type(entry) is MissingEvidence:
        missing = entry
        values = {
            **common,
            "kind": _enum_value(missing.kind, EvidenceKind, evidence_kind_values),
            "resolved_by": missing.resolved_by,
        }
        return _checked_object(
            missing,
            MissingEvidence,
            ("id", "claim", "owner", "affects", "resolved_by", "artefacts"),
            values,
            extra_keys=("kind",),
        )
    raise CanonicalizationError("Unsupported evidence subtype for canonicalization.")


def canonical_evidence_bytes(entry: Evidence) -> bytes:
    """Return canonical UTF-8 JSON bytes for one evidence-ledger entry."""
    return canonical_json_bytes(canonical_evidence_dict(entry))


def evidence_content_identity(entry: Evidence) -> str:
    """Return the SHA-256 identity of one canonical evidence entry."""
    return _content_identity(canonical_evidence_bytes(entry))


def evidence_content_identities(dossier: Dossier) -> dict[str, str]:
    """Return evidence identities keyed in canonical evidence-ID order."""
    canonical_dossier_dict(dossier)
    ordered = sorted(dossier.evidence, key=lambda entry: entry.id)
    identities: dict[str, str] = {}
    for entry in ordered:
        if entry.id in identities:
            raise CanonicalizationError("Duplicate evidence IDs cannot be canonicalized.")
        identities[entry.id] = evidence_content_identity(entry)
    return identities


def canonical_dossier_dict(dossier: Dossier) -> JsonObject:
    """Return the complete normalized schema-v1 dossier as canonical JSON data."""
    _check_typed_value(dossier, Dossier)
    if dossier.schema_version != 1:
        raise CanonicalizationError("Unsupported dossier schema version for canonicalization.")
    expected = (
        "schema_version",
        "case",
        "evidence",
        "task",
        "problem_value",
        "agency_necessity",
        "autonomy_permission",
        "candidate_comparison",
        "decision_conditions",
    )
    return _checked_object(
        dossier,
        Dossier,
        expected,
        {
            "schema_version": dossier.schema_version,
            "case": _case(dossier.case),
            "evidence": [canonical_evidence_dict(entry) for entry in dossier.evidence],
            "task": _task(dossier.task) if dossier.task is not None else None,
            "problem_value": (
                _problem_value(dossier.problem_value) if dossier.problem_value is not None else None
            ),
            "agency_necessity": (
                _agency(dossier.agency_necessity) if dossier.agency_necessity is not None else None
            ),
            "autonomy_permission": (
                _autonomy(dossier.autonomy_permission)
                if dossier.autonomy_permission is not None
                else None
            ),
            "candidate_comparison": (
                _candidate_comparison(dossier.candidate_comparison)
                if dossier.candidate_comparison is not None
                else None
            ),
            "decision_conditions": [
                _decision_condition(condition) for condition in dossier.decision_conditions
            ],
        },
    )


def canonical_dossier_bytes(dossier: Dossier) -> bytes:
    """Return strict canonical UTF-8 JSON bytes with exactly one trailing LF."""
    return canonical_json_bytes(canonical_dossier_dict(dossier))


def dossier_content_identity(dossier: Dossier) -> str:
    """Return the SHA-256 identity of the complete canonical dossier bytes."""
    return _content_identity(canonical_dossier_bytes(dossier))
