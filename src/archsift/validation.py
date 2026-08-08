"""Safe loading and structural validation of case dossiers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any, ClassVar, TypeAlias, cast

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from yaml.constructor import ConstructorError
from yaml.error import MarkedYAMLError
from yaml.nodes import MappingNode

from archsift.diagnostics import Diagnostic, ExitCode


@dataclass(frozen=True, slots=True)
class CaseIdentity:
    """Validated minimal case identity."""

    id: str
    title: str


@dataclass(frozen=True, slots=True)
class TaskAction:
    """One output or effect produced by the bounded task."""

    id: str
    description: str
    consequential: bool
    approval_boundary: str


@dataclass(frozen=True, slots=True)
class TaskBoundary:
    """The operational unit of analysis for an architecture decision."""

    operation: str
    starts_when: str
    completes_when: str
    accountable_owner: str
    actors: tuple[str, ...]
    systems_and_tools: tuple[str, ...]
    information_read: tuple[str, ...]
    actions: tuple[TaskAction, ...]
    exclusions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidencedStatement:
    """One problem-value statement linked to classified evidence."""

    statement: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProblemOutcome:
    """A measurable desired outcome and the baseline it changes."""

    id: str
    description: str
    measure: str
    target: str
    baseline_id: str
    binding: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProblemBaseline:
    """A current-state measurement used by desired outcomes."""

    id: str
    description: str
    measure: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProblemConstraint:
    """A candidate test whose binding state is explicit."""

    id: str
    description: str
    test: str
    required_result: str
    binding: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProblemValue:
    """The business-value contract that precedes architecture selection."""

    outcomes: tuple[ProblemOutcome, ...]
    baselines: tuple[ProblemBaseline, ...]
    constraints: tuple[ProblemConstraint, ...]
    affected_volume: EvidencedStatement
    material_pain: EvidencedStatement
    error_cost: EvidencedStatement
    technology_limitation: EvidencedStatement


class AgencyAnswer(StrEnum):
    """Explicit answer state for one agency-necessity question."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AgencyQuestion:
    """One evidence-backed fact used by later agency rules."""

    answer: AgencyAnswer
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResidualCase:
    """A case that a fixed workflow is asserted not to handle."""

    id: str
    description: str
    fixed_workflow_failure: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgencyNecessity:
    """Facts needed to evaluate runtime model-directed control."""

    execution_steps_predefinable: AgencyQuestion
    step_count_or_order_predictable: AgencyQuestion
    runtime_tool_choice_required: AgencyQuestion
    runtime_replanning_required: AgencyQuestion
    environmental_feedback_available: AgencyQuestion
    completion_independently_verifiable: AgencyQuestion
    effects_independently_verifiable: AgencyQuestion
    fixed_workflow_sufficient: AgencyQuestion
    residual_cases: tuple[ResidualCase, ...]


class AutonomyAnswer(StrEnum):
    """Explicit answer state for one autonomy-permission question."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AutonomyQuestion:
    """One evidence-backed fact used by later autonomy rules."""

    answer: AutonomyAnswer
    rationale: str
    evidence_ids: tuple[str, ...]


class HardVetoStatus(StrEnum):
    """Evidence state for whether a hard veto applies."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HardVeto:
    """An explicit non-scoring boundary that later rules must preserve."""

    id: str
    status: HardVetoStatus
    condition: str
    consequence: str
    action_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MandatoryHumanControl:
    """A required human-control boundary for one or more task actions."""

    id: str
    description: str
    control_point: str
    responsible_role: str
    action_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AutonomyPermission:
    """Facts and boundaries needed to evaluate permissible autonomy."""

    actions_reversible: AutonomyQuestion
    failure_blast_radius_bounded: AutonomyQuestion
    regulatory_automation_permitted: AutonomyQuestion
    data_confidence_sufficient: AutonomyQuestion
    accountable_owner_assigned: AutonomyQuestion
    decision_path_auditable: AutonomyQuestion
    timely_human_intervention_available: AutonomyQuestion
    safe_degradation_available: AutonomyQuestion
    hard_vetoes: tuple[HardVeto, ...]
    mandatory_human_controls: tuple[MandatoryHumanControl, ...]


class ControlClass(StrEnum):
    """Ordered architecture control classes from least to most runtime freedom."""

    HUMAN_OWNED_WORK = "human-owned-work"
    PROCESS_REDESIGN = "process-redesign"
    DETERMINISTIC_AUTOMATION = "deterministic-automation"
    FIXED_AI_WORKFLOW = "fixed-ai-workflow"
    AGENTIC_CONTROL = "agentic-control"


class CandidateRole(StrEnum):
    """Explicit comparison roles that never imply a recommendation."""

    CURRENT_BASELINE = "current-baseline"
    PROPOSED = "proposed"
    STRONGEST_SIMPLER = "strongest-simpler"
    AGENTIC_COMPARATOR = "agentic-comparator"


class CandidateTestResult(StrEnum):
    """Outcome or constraint result recorded for one candidate."""

    MEETS = "meets"
    FAILS = "fails"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CandidateOutcomeTest:
    """One candidate's evidence-backed result for a problem outcome."""

    outcome_id: str
    result: CandidateTestResult
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateConstraintTest:
    """One candidate's evidence-backed result for a problem constraint."""

    constraint_id: str
    result: CandidateTestResult
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One explicitly classified architecture candidate."""

    id: str
    name: str
    description: str
    control_class: ControlClass
    roles: tuple[CandidateRole, ...]
    material_deviations: tuple[str, ...]
    outcome_tests: tuple[CandidateOutcomeTest, ...]
    constraint_tests: tuple[CandidateConstraintTest, ...]


class ComparisonResult(StrEnum):
    """Directional pairwise result for one trade-off dimension."""

    BETTER = "better"
    EQUIVALENT = "equivalent"
    WORSE = "worse"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ComparisonDimension:
    """One evidence-backed directional trade-off observation."""

    result: ComparisonResult
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparisonDimensions:
    """The complete FR-008 trade-off matrix for one directed candidate pair."""

    outcome_quality: ComparisonDimension
    difficult_case_performance: ComparisonDimension
    cost: ComparisonDimension
    latency: ComparisonDimension
    human_effort: ComparisonDimension
    integration_burden: ComparisonDimension
    security_exposure: ComparisonDimension
    failure_impact: ComparisonDimension
    operability: ComparisonDimension
    evaluation_burden: ComparisonDimension
    maintainability: ComparisonDimension


@dataclass(frozen=True, slots=True)
class CandidatePairComparison:
    """Directional comparison of one candidate against another."""

    subject_candidate_id: str
    comparator_candidate_id: str
    dimensions: ComparisonDimensions


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    """Candidate roles, tests, and pairwise trade-offs for FR-008."""

    candidates: tuple[Candidate, ...]
    comparisons: tuple[CandidatePairComparison, ...]


class EvidenceKind(StrEnum):
    """Supported evidence states."""

    OBSERVED = "observed"
    ASSUMPTION = "assumption"
    ESTIMATE = "estimate"
    MISSING = "missing"


class DecisionArea(StrEnum):
    """Decision areas an evidence entry can affect."""

    PROBLEM_VALUE = "problem-value"
    AGENCY_NECESSITY = "agency-necessity"
    AUTONOMY_PERMISSION = "autonomy-permission"
    COMPARATIVE_FIT = "comparative-fit"


class DecisionConditionStatus(StrEnum):
    """Authored state of a post-selection condition."""

    MET = "met"
    UNMET = "unmet"


@dataclass(frozen=True, slots=True)
class DecisionCondition:
    """One evidence-linked obligation that cannot participate in class selection."""

    id: str
    target_control_class: ControlClass
    decision_area: DecisionArea
    statement: str
    status: DecisionConditionStatus
    resolved_by: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    """Fields shared by every immutable evidence entry."""

    id: str
    claim: str
    owner: str
    affects: tuple[DecisionArea, ...]


@dataclass(frozen=True, slots=True)
class ObservedEvidence(EvidenceEntry):
    """A claim backed by a named artefact or measurement."""

    provenance: str
    observed_at: date
    kind: ClassVar[EvidenceKind] = EvidenceKind.OBSERVED


@dataclass(frozen=True, slots=True)
class AssumptionEvidence(EvidenceEntry):
    """A belief with an explicit falsification observation."""

    falsified_by: str
    kind: ClassVar[EvidenceKind] = EvidenceKind.ASSUMPTION


@dataclass(frozen=True, slots=True)
class EstimateEvidence(EvidenceEntry):
    """A forecast with a recorded method."""

    method: str
    kind: ClassVar[EvidenceKind] = EvidenceKind.ESTIMATE


@dataclass(frozen=True, slots=True)
class MissingEvidence(EvidenceEntry):
    """A known evidence gap with a resolution observation."""

    resolved_by: str
    kind: ClassVar[EvidenceKind] = EvidenceKind.MISSING


Evidence: TypeAlias = ObservedEvidence | AssumptionEvidence | EstimateEvidence | MissingEvidence


@dataclass(frozen=True, slots=True)
class Dossier:
    """Typed version-1 dossier envelope."""

    schema_version: int
    case: CaseIdentity
    evidence: tuple[Evidence, ...] = ()
    task: TaskBoundary | None = None
    problem_value: ProblemValue | None = None
    agency_necessity: AgencyNecessity | None = None
    autonomy_permission: AutonomyPermission | None = None
    candidate_comparison: CandidateComparison | None = None
    decision_conditions: tuple[DecisionCondition, ...] = ()


@dataclass(frozen=True, slots=True)
class PrerequisiteFinding:
    """One unmet, non-scoring prerequisite for a later assessment."""

    id: str
    field: str
    requirement: str
    message: str
    remediation: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProblemValueReadiness:
    """Deterministic advisory readiness for FR-005."""

    ready: bool
    findings: tuple[PrerequisiteFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class AgencyNecessityReadiness:
    """Deterministic advisory readiness for FR-006."""

    ready: bool
    findings: tuple[PrerequisiteFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class AutonomyPermissionReadiness:
    """Deterministic advisory readiness for FR-007."""

    ready: bool
    findings: tuple[PrerequisiteFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateComparisonReadiness:
    """Deterministic advisory readiness for FR-008."""

    ready: bool
    findings: tuple[PrerequisiteFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Typed validation result, independent of terminal rendering."""

    exit_code: ExitCode
    dossier: Dossier | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


_SCHEMA_RESOURCE = "schemas/dossier-v1.schema.json"
_AGENCY_QUESTION_FIELDS = (
    "execution_steps_predefinable",
    "step_count_or_order_predictable",
    "runtime_tool_choice_required",
    "runtime_replanning_required",
    "environmental_feedback_available",
    "completion_independently_verifiable",
    "effects_independently_verifiable",
    "fixed_workflow_sufficient",
)
_AUTONOMY_QUESTION_FIELDS = (
    "actions_reversible",
    "failure_blast_radius_bounded",
    "regulatory_automation_permitted",
    "data_confidence_sufficient",
    "accountable_owner_assigned",
    "decision_path_auditable",
    "timely_human_intervention_available",
    "safe_degradation_available",
)
_COMPARISON_DIMENSION_FIELDS = (
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
_CONTROL_CLASS_ORDER = tuple(ControlClass)


class _DossierLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and keeps scalar types explicit."""

    # JSON Schema owns scalar interpretation. PyYAML otherwise turns an
    # unquoted YYYY-MM-DD value into datetime.date before format validation
    # and resolves unquoted yes/no/on/off into booleans; both would bypass
    # the schema's type checks. Only YAML's true/false forms stay booleans.
    yaml_implicit_resolvers: dict[str, list[tuple[str, re.Pattern[str]]]] = {  # noqa: RUF012
        key: [
            (tag, pattern)
            for tag, pattern in resolvers
            if tag != "tag:yaml.org,2002:timestamp"
            and not (tag == "tag:yaml.org,2002:bool" and key in ("y", "Y", "n", "N", "o", "O"))
        ]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            if key_node.tag in ("tag:yaml.org,2002:merge", "tag:yaml.org,2002:value"):
                # Merge ("<<") and value ("=") keys have no registered
                # constructor; flatten_mapping resolves them during
                # construction, so they are never duplicate real keys.
                continue
            key: Any = self.construct_object(key_node, deep=False)
            key_id: Any = key
            try:
                hash(key)
            except TypeError:
                key_id = repr(key)
            if key_id in seen:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key_id)
        return super().construct_mapping(node, deep=deep)


def _yaml_load_message(error: Exception) -> str:
    """Return a stable, path-independent description of a load failure."""
    if isinstance(error, MarkedYAMLError):
        # PyYAML str(error) embeds the absolute stream path via its marks;
        # context/problem text and line/column positions are stable instead.
        detail = " ".join(part for part in (error.context or "", error.problem or "") if part)
        mark = error.problem_mark
        if mark is not None:
            detail = f"{detail} (line {mark.line + 1}, column {mark.column + 1})"
        return detail or error.__class__.__name__
    if isinstance(error, OSError):
        # strerror is stable; str(error) embeds the absolute file path.
        return error.strerror or error.__class__.__name__
    return str(error)


def _diagnostic(
    identifier: str,
    message: str,
    field: str,
    requirement: str,
    remediation: str,
) -> Diagnostic:
    return Diagnostic(identifier, message, "case.yaml", field, requirement, remediation)


def _field_path(parts: Sequence[object]) -> str:
    return "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts)


def _schema() -> Mapping[str, Any]:
    content = files("archsift").joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")
    parsed: Any = json.loads(content)
    if not isinstance(parsed, Mapping):
        raise TypeError("packaged dossier schema must be an object")
    return parsed


def _remediation(error: ValidationError, field: str) -> str:
    if error.validator == "required":
        required = cast(Sequence[str], error.validator_value)
        instance = cast(Mapping[str, object], error.instance)
        missing = sorted(set(required) - set(instance))
        named = re.fullmatch(r"'([^']+)' is a required property", error.message)
        if named is not None and named.group(1) in missing:
            missing = [named.group(1)]
        names = ", ".join(f"{field}.{name}" for name in missing)
        label = "field" if len(missing) == 1 else "fields"
        return f"Add the required {label} {names} using the documented schema."
    if error.validator == "additionalProperties":
        return "Remove the unknown field or use a supported schema version that defines it."
    if error.validator == "type":
        return f"Set {field} to a value of type {error.validator_value}."
    if error.validator in {"minItems", "minLength"}:
        return f"Set {field} to a non-empty value."
    if error.validator == "maxItems" and error.validator_value == 0:
        return f"Set {field} to an empty array."
    if error.validator == "pattern":
        return f"Set {field} to a value containing at least one non-whitespace character."
    if error.validator == "uniqueItems":
        return f"Remove duplicate values from {field}."
    if error.validator == "enum":
        allowed = ", ".join(repr(value) for value in cast(Sequence[object], error.validator_value))
        return f"Set {field} to one of: {allowed}."
    if error.validator == "format":
        return f"Set {field} to a real calendar date in YYYY-MM-DD format."
    if error.validator == "not" and isinstance(error.instance, Mapping):
        kind = error.instance.get("kind", "this evidence kind")
        return f"Remove metadata fields that do not apply to evidence kind {kind!r}."
    return "Update the field to satisfy the packaged version-1 schema."


def _schema_diagnostics(error: ValidationError) -> tuple[Diagnostic, ...]:
    base_field = _field_path(list(error.absolute_path))
    if base_field.startswith("$.evidence"):
        requirement = "FR-004"
    elif base_field.startswith("$.task"):
        requirement = "FR-003"
    elif base_field.startswith("$.problem_value"):
        requirement = "FR-005"
    elif base_field.startswith("$.agency_necessity"):
        requirement = "FR-006"
    elif base_field.startswith("$.autonomy_permission"):
        requirement = "FR-007"
    elif base_field.startswith("$.candidate_comparison"):
        requirement = "FR-008"
    elif base_field.startswith("$.decision_conditions"):
        requirement = "FR-010"
    else:
        requirement = "FR-002"
    if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
        error_schema = cast(Mapping[str, Any], error.schema)
        properties = cast(Mapping[str, Any], error_schema.get("properties", {}))
        # YAML mappings may use non-string keys (1: x, true: x, null: x);
        # Sort by type and representation to avoid incomparable key types and
        # string-form ties such as integer 1 versus string "1".
        unknown = sorted(
            set(error.instance) - set(properties),
            key=lambda value: (type(value).__qualname__, repr(value)),
        )
        return tuple(
            _diagnostic(
                "unknown-field",
                f"Unknown field {name!r} is not permitted by schema version 1.",
                f"{base_field}.{name}",
                requirement,
                "Remove the unknown field or use a supported schema version that defines it.",
            )
            for name in unknown
        )
    return (
        _diagnostic(
            "schema-validation-failed",
            error.message,
            base_field,
            requirement,
            _remediation(error, base_field),
        ),
    )


def _duplicate_evidence_diagnostics(entries: Sequence[Mapping[str, Any]]) -> tuple[Diagnostic, ...]:
    first_by_id: dict[str, int] = {}
    diagnostics: list[Diagnostic] = []
    for index, entry in enumerate(entries):
        identifier = cast(str, entry["id"])
        first = first_by_id.setdefault(identifier, index)
        if first != index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-evidence-id",
                    f"Evidence ID {identifier!r} duplicates the entry at $.evidence[{first}].id.",
                    f"$.evidence[{index}].id",
                    "FR-004",
                    "Give every evidence entry a unique stable ID and update later references.",
                )
            )
    return tuple(diagnostics)


def _duplicate_task_action_diagnostics(task: Mapping[str, Any] | None) -> tuple[Diagnostic, ...]:
    if task is None:
        return ()
    actions = cast(Sequence[Mapping[str, Any]], task["actions"])
    first_by_id: dict[str, int] = {}
    diagnostics: list[Diagnostic] = []
    for index, action in enumerate(actions):
        identifier = cast(str, action["id"])
        first = first_by_id.setdefault(identifier, index)
        if first != index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-task-action-id",
                    f"Task action ID {identifier!r} duplicates the action at "
                    f"$.task.actions[{first}].id.",
                    f"$.task.actions[{index}].id",
                    "FR-003",
                    "Give every task action a unique stable ID and update later references.",
                )
            )
    return tuple(diagnostics)


def _problem_value_semantic_diagnostics(
    problem: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[Diagnostic, ...]:
    if problem is None:
        return ()

    diagnostics: list[Diagnostic] = []
    outcomes = cast(Sequence[Mapping[str, Any]], problem["outcomes"])
    baselines = cast(Sequence[Mapping[str, Any]], problem["baselines"])
    constraints = cast(Sequence[Mapping[str, Any]], problem["constraints"])

    first_criterion: dict[str, str] = {}
    for collection, entries in (("outcomes", outcomes), ("constraints", constraints)):
        for index, entry in enumerate(entries):
            identifier = cast(str, entry["id"])
            path = f"$.problem_value.{collection}[{index}].id"
            first = first_criterion.setdefault(identifier, path)
            if first != path:
                diagnostics.append(
                    _diagnostic(
                        "duplicate-problem-criterion-id",
                        f"Problem criterion ID {identifier!r} duplicates {first}.",
                        path,
                        "FR-005",
                        "Give every outcome and constraint a unique stable ID.",
                    )
                )

    first_baseline: dict[str, str] = {}
    for index, baseline in enumerate(baselines):
        identifier = cast(str, baseline["id"])
        path = f"$.problem_value.baselines[{index}].id"
        first = first_baseline.setdefault(identifier, path)
        if first != path:
            diagnostics.append(
                _diagnostic(
                    "duplicate-problem-baseline-id",
                    f"Problem baseline ID {identifier!r} duplicates {first}.",
                    path,
                    "FR-005",
                    "Give every baseline a unique stable ID and update outcome references.",
                )
            )

    baseline_ids = set(first_baseline)
    for index, outcome in enumerate(outcomes):
        baseline_id = cast(str, outcome["baseline_id"])
        if baseline_id not in baseline_ids:
            diagnostics.append(
                _diagnostic(
                    "missing-problem-baseline-reference",
                    f"Baseline ID {baseline_id!r} does not exist in problem_value.baselines.",
                    f"$.problem_value.outcomes[{index}].baseline_id",
                    "FR-005",
                    "Add the referenced baseline or use an existing baseline ID.",
                )
            )

    references: list[tuple[str, str]] = []
    for collection, entries in (
        ("outcomes", outcomes),
        ("baselines", baselines),
        ("constraints", constraints),
    ):
        for entry_index, entry in enumerate(entries):
            for reference_index, identifier in enumerate(
                cast(Sequence[str], entry["evidence_ids"])
            ):
                references.append(
                    (
                        f"$.problem_value.{collection}[{entry_index}].evidence_ids[{reference_index}]",
                        identifier,
                    )
                )
    for name in ("affected_volume", "material_pain", "error_cost", "technology_limitation"):
        statement = cast(Mapping[str, Any], problem[name])
        for reference_index, identifier in enumerate(
            cast(Sequence[str], statement["evidence_ids"])
        ):
            references.append(
                (f"$.problem_value.{name}.evidence_ids[{reference_index}]", identifier)
            )

    evidence_by_id = {cast(str, entry["id"]): entry for entry in evidence}
    for path, identifier in references:
        referenced_entry = evidence_by_id.get(identifier)
        if referenced_entry is None:
            diagnostics.append(
                _diagnostic(
                    "missing-problem-value-evidence-reference",
                    f"Evidence ID {identifier!r} does not exist in the evidence ledger.",
                    path,
                    "FR-005",
                    "Add the evidence entry or use an existing evidence ID.",
                )
            )
        elif "problem-value" not in cast(Sequence[str], referenced_entry["affects"]):
            diagnostics.append(
                _diagnostic(
                    "problem-value-evidence-area-mismatch",
                    f"Evidence ID {identifier!r} is not classified for problem-value.",
                    path,
                    "FR-005",
                    "Add problem-value to that evidence entry's affects list or cite "
                    "relevant evidence.",
                )
            )
    return tuple(diagnostics)


def _agency_necessity_semantic_diagnostics(
    agency: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[Diagnostic, ...]:
    if agency is None:
        return ()

    diagnostics: list[Diagnostic] = []
    residual_cases = cast(Sequence[Mapping[str, Any]], agency["residual_cases"])
    first_by_id: dict[str, int] = {}
    for index, residual in enumerate(residual_cases):
        identifier = cast(str, residual["id"])
        first = first_by_id.setdefault(identifier, index)
        if first != index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-residual-case-id",
                    f"Residual case ID {identifier!r} duplicates the case at "
                    f"$.agency_necessity.residual_cases[{first}].id.",
                    f"$.agency_necessity.residual_cases[{index}].id",
                    "FR-006",
                    "Give every residual case a unique stable ID.",
                )
            )

    references: list[tuple[str, str]] = []
    for name in _AGENCY_QUESTION_FIELDS:
        question = cast(Mapping[str, Any], agency[name])
        for reference_index, identifier in enumerate(cast(Sequence[str], question["evidence_ids"])):
            references.append(
                (f"$.agency_necessity.{name}.evidence_ids[{reference_index}]", identifier)
            )
    for case_index, residual in enumerate(residual_cases):
        for reference_index, identifier in enumerate(cast(Sequence[str], residual["evidence_ids"])):
            references.append(
                (
                    f"$.agency_necessity.residual_cases[{case_index}]."
                    f"evidence_ids[{reference_index}]",
                    identifier,
                )
            )

    evidence_by_id = {cast(str, entry["id"]): entry for entry in evidence}
    for path, identifier in references:
        referenced_entry = evidence_by_id.get(identifier)
        if referenced_entry is None:
            diagnostics.append(
                _diagnostic(
                    "missing-agency-evidence-reference",
                    f"Evidence ID {identifier!r} does not exist in the evidence ledger.",
                    path,
                    "FR-006",
                    "Add the evidence entry or use an existing evidence ID.",
                )
            )
        elif "agency-necessity" not in cast(Sequence[str], referenced_entry["affects"]):
            diagnostics.append(
                _diagnostic(
                    "agency-evidence-area-mismatch",
                    f"Evidence ID {identifier!r} is not classified for agency-necessity.",
                    path,
                    "FR-006",
                    "Add agency-necessity to that evidence entry's affects list or cite "
                    "relevant evidence.",
                )
            )
    return tuple(diagnostics)


def _autonomy_permission_semantic_diagnostics(
    autonomy: Mapping[str, Any] | None,
    task: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[Diagnostic, ...]:
    if autonomy is None:
        return ()

    diagnostics: list[Diagnostic] = []
    hard_vetoes = cast(Sequence[Mapping[str, Any]], autonomy["hard_vetoes"])
    human_controls = cast(Sequence[Mapping[str, Any]], autonomy["mandatory_human_controls"])

    for collection, entries, label, diagnostic_id in (
        ("hard_vetoes", hard_vetoes, "Hard veto", "duplicate-hard-veto-id"),
        (
            "mandatory_human_controls",
            human_controls,
            "Mandatory human control",
            "duplicate-human-control-id",
        ),
    ):
        first_by_id: dict[str, int] = {}
        for index, entry in enumerate(entries):
            identifier = cast(str, entry["id"])
            first = first_by_id.setdefault(identifier, index)
            if first != index:
                diagnostics.append(
                    _diagnostic(
                        diagnostic_id,
                        f"{label} ID {identifier!r} duplicates the entry at "
                        f"$.autonomy_permission.{collection}[{first}].id.",
                        f"$.autonomy_permission.{collection}[{index}].id",
                        "FR-007",
                        f"Give every {label.lower()} a unique stable ID.",
                    )
                )

    evidence_references: list[tuple[str, str]] = []
    for name in _AUTONOMY_QUESTION_FIELDS:
        question = cast(Mapping[str, Any], autonomy[name])
        for reference_index, identifier in enumerate(cast(Sequence[str], question["evidence_ids"])):
            evidence_references.append(
                (f"$.autonomy_permission.{name}.evidence_ids[{reference_index}]", identifier)
            )
    for collection, entries in (
        ("hard_vetoes", hard_vetoes),
        ("mandatory_human_controls", human_controls),
    ):
        for entry_index, entry in enumerate(entries):
            for reference_index, identifier in enumerate(
                cast(Sequence[str], entry["evidence_ids"])
            ):
                evidence_references.append(
                    (
                        f"$.autonomy_permission.{collection}[{entry_index}]."
                        f"evidence_ids[{reference_index}]",
                        identifier,
                    )
                )

    evidence_by_id = {cast(str, entry["id"]): entry for entry in evidence}
    for path, identifier in evidence_references:
        referenced_entry = evidence_by_id.get(identifier)
        if referenced_entry is None:
            diagnostics.append(
                _diagnostic(
                    "missing-autonomy-evidence-reference",
                    f"Evidence ID {identifier!r} does not exist in the evidence ledger.",
                    path,
                    "FR-007",
                    "Add the evidence entry or use an existing evidence ID.",
                )
            )
        elif "autonomy-permission" not in cast(Sequence[str], referenced_entry["affects"]):
            diagnostics.append(
                _diagnostic(
                    "autonomy-evidence-area-mismatch",
                    f"Evidence ID {identifier!r} is not classified for autonomy-permission.",
                    path,
                    "FR-007",
                    "Add autonomy-permission to that evidence entry's affects list or cite "
                    "relevant evidence.",
                )
            )

    task_action_ids = (
        {cast(str, action["id"]) for action in cast(Sequence[Mapping[str, Any]], task["actions"])}
        if task is not None
        else set()
    )
    for collection, entries in (
        ("hard_vetoes", hard_vetoes),
        ("mandatory_human_controls", human_controls),
    ):
        for entry_index, entry in enumerate(entries):
            for reference_index, identifier in enumerate(cast(Sequence[str], entry["action_ids"])):
                if identifier not in task_action_ids:
                    diagnostics.append(
                        _diagnostic(
                            "missing-autonomy-task-action-reference",
                            f"Task action ID {identifier!r} does not exist in task.actions.",
                            f"$.autonomy_permission.{collection}[{entry_index}]."
                            f"action_ids[{reference_index}]",
                            "FR-007",
                            "Add the referenced task action or use an existing task action ID.",
                        )
                    )
    return tuple(diagnostics)


def _candidate_comparison_semantic_diagnostics(
    comparison: Mapping[str, Any] | None,
    problem: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[Diagnostic, ...]:
    if comparison is None:
        return ()

    diagnostics: list[Diagnostic] = []
    candidates = cast(Sequence[Mapping[str, Any]], comparison["candidates"])
    comparisons = cast(Sequence[Mapping[str, Any]], comparison["comparisons"])
    first_candidate: dict[str, int] = {}
    first_role: dict[str, str] = {}
    evidence_references: list[tuple[str, str]] = []

    outcome_ids = (
        {
            cast(str, outcome["id"])
            for outcome in cast(Sequence[Mapping[str, Any]], problem["outcomes"])
        }
        if problem is not None
        else set()
    )
    constraint_ids = (
        {
            cast(str, constraint["id"])
            for constraint in cast(Sequence[Mapping[str, Any]], problem["constraints"])
        }
        if problem is not None
        else set()
    )

    for candidate_index, candidate in enumerate(candidates):
        identifier = cast(str, candidate["id"])
        first_index = first_candidate.setdefault(identifier, candidate_index)
        if first_index != candidate_index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-candidate-id",
                    f"Candidate ID {identifier!r} duplicates the candidate at "
                    f"$.candidate_comparison.candidates[{first_index}].id.",
                    f"$.candidate_comparison.candidates[{candidate_index}].id",
                    "FR-008",
                    "Give every candidate a unique stable ID and update comparison references.",
                )
            )

        local_roles: dict[str, int] = {}
        for role_index, role in enumerate(cast(Sequence[str], candidate["roles"])):
            role_path = f"$.candidate_comparison.candidates[{candidate_index}].roles[{role_index}]"
            local_first = local_roles.setdefault(role, role_index)
            if local_first != role_index:
                diagnostics.append(
                    _diagnostic(
                        "duplicate-candidate-role",
                        f"Candidate role {role!r} duplicates "
                        f"$.candidate_comparison.candidates[{candidate_index}]."
                        f"roles[{local_first}].",
                        role_path,
                        "FR-008",
                        "List each role at most once for a candidate.",
                    )
                )
            global_first = first_role.setdefault(role, role_path)
            if global_first != role_path and local_first == role_index:
                diagnostics.append(
                    _diagnostic(
                        "conflicting-candidate-role",
                        f"Candidate role {role!r} is already assigned at {global_first}.",
                        role_path,
                        "FR-008",
                        "Assign each comparison role to at most one candidate.",
                    )
                )

        for collection, reference_field, expected_ids, other_ids in (
            ("outcome_tests", "outcome_id", outcome_ids, constraint_ids),
            ("constraint_tests", "constraint_id", constraint_ids, outcome_ids),
        ):
            tests = cast(Sequence[Mapping[str, Any]], candidate[collection])
            first_test: dict[str, int] = {}
            for test_index, test in enumerate(tests):
                criterion_id = cast(str, test[reference_field])
                reference_path = (
                    f"$.candidate_comparison.candidates[{candidate_index}]."
                    f"{collection}[{test_index}].{reference_field}"
                )
                first_test_index = first_test.setdefault(criterion_id, test_index)
                if first_test_index != test_index:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate-candidate-test-id",
                            f"Candidate test ID {criterion_id!r} duplicates the test at "
                            f"$.candidate_comparison.candidates[{candidate_index}]."
                            f"{collection}[{first_test_index}].{reference_field}.",
                            reference_path,
                            "FR-008",
                            f"Test each {reference_field.removesuffix('_id')} at most once per "
                            "candidate.",
                        )
                    )
                if criterion_id not in expected_ids:
                    if criterion_id in other_ids:
                        diagnostics.append(
                            _diagnostic(
                                "candidate-test-kind-mismatch",
                                f"Problem criterion ID {criterion_id!r} belongs to the other "
                                "problem-value collection.",
                                reference_path,
                                "FR-008",
                                f"Move the test to the correct collection or reference an "
                                f"existing {reference_field.removesuffix('_id')} ID.",
                            )
                        )
                    else:
                        diagnostics.append(
                            _diagnostic(
                                "missing-candidate-criterion-reference",
                                f"Problem criterion ID {criterion_id!r} does not exist in the "
                                "referenced problem-value collection.",
                                reference_path,
                                "FR-008",
                                "Add the referenced problem criterion or use an existing ID.",
                            )
                        )
                for evidence_index, evidence_id in enumerate(
                    cast(Sequence[str], test["evidence_ids"])
                ):
                    evidence_references.append(
                        (
                            f"$.candidate_comparison.candidates[{candidate_index}]."
                            f"{collection}[{test_index}].evidence_ids[{evidence_index}]",
                            evidence_id,
                        )
                    )

    candidate_ids = set(first_candidate)
    first_pair: dict[tuple[str, str], int] = {}
    for comparison_index, pair in enumerate(comparisons):
        subject_id = cast(str, pair["subject_candidate_id"])
        comparator_id = cast(str, pair["comparator_candidate_id"])
        for field, identifier in (
            ("subject_candidate_id", subject_id),
            ("comparator_candidate_id", comparator_id),
        ):
            if identifier not in candidate_ids:
                diagnostics.append(
                    _diagnostic(
                        "missing-comparison-candidate-reference",
                        f"Candidate ID {identifier!r} does not exist in candidates.",
                        f"$.candidate_comparison.comparisons[{comparison_index}].{field}",
                        "FR-008",
                        "Add the referenced candidate or use an existing candidate ID.",
                    )
                )
        if subject_id == comparator_id:
            diagnostics.append(
                _diagnostic(
                    "self-candidate-comparison",
                    f"Candidate {subject_id!r} cannot be compared with itself.",
                    f"$.candidate_comparison.comparisons[{comparison_index}]."
                    "comparator_candidate_id",
                    "FR-008",
                    "Set subject_candidate_id and comparator_candidate_id to distinct IDs.",
                )
            )
        pair_key = (subject_id, comparator_id)
        first_pair_index = first_pair.setdefault(pair_key, comparison_index)
        if first_pair_index != comparison_index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-candidate-comparison",
                    f"Directed comparison {subject_id!r} versus {comparator_id!r} duplicates "
                    f"$.candidate_comparison.comparisons[{first_pair_index}].",
                    f"$.candidate_comparison.comparisons[{comparison_index}].subject_candidate_id",
                    "FR-008",
                    "Keep at most one comparison for each directed candidate pair.",
                )
            )
        dimensions = cast(Mapping[str, Any], pair["dimensions"])
        for dimension_name in _COMPARISON_DIMENSION_FIELDS:
            dimension = cast(Mapping[str, Any], dimensions[dimension_name])
            for evidence_index, evidence_id in enumerate(
                cast(Sequence[str], dimension["evidence_ids"])
            ):
                evidence_references.append(
                    (
                        f"$.candidate_comparison.comparisons[{comparison_index}]."
                        f"dimensions.{dimension_name}.evidence_ids[{evidence_index}]",
                        evidence_id,
                    )
                )

    evidence_by_id = {cast(str, entry["id"]): entry for entry in evidence}
    for path, identifier in evidence_references:
        referenced_entry = evidence_by_id.get(identifier)
        if referenced_entry is None:
            diagnostics.append(
                _diagnostic(
                    "missing-comparative-evidence-reference",
                    f"Evidence ID {identifier!r} does not exist in the evidence ledger.",
                    path,
                    "FR-008",
                    "Add the evidence entry or use an existing evidence ID.",
                )
            )
        elif "comparative-fit" not in cast(Sequence[str], referenced_entry["affects"]):
            diagnostics.append(
                _diagnostic(
                    "comparative-evidence-area-mismatch",
                    f"Evidence ID {identifier!r} is not classified for comparative-fit.",
                    path,
                    "FR-008",
                    "Add comparative-fit to that evidence entry's affects list or cite "
                    "relevant evidence.",
                )
            )
    return tuple(diagnostics)


def _decision_condition_semantic_diagnostics(
    conditions: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    first_by_id: dict[str, int] = {}
    evidence_by_id = {cast(str, entry["id"]): entry for entry in evidence}

    for condition_index, condition in enumerate(conditions):
        identifier = cast(str, condition["id"])
        first = first_by_id.setdefault(identifier, condition_index)
        if first != condition_index:
            diagnostics.append(
                _diagnostic(
                    "duplicate-decision-condition-id",
                    f"Decision condition ID {identifier!r} duplicates the entry at "
                    f"$.decision_conditions[{first}].id.",
                    f"$.decision_conditions[{condition_index}].id",
                    "FR-010",
                    "Give every decision condition a unique stable ID.",
                )
            )

        area = cast(str, condition["decision_area"])
        for evidence_index, evidence_id in enumerate(
            cast(Sequence[str], condition["evidence_ids"])
        ):
            path = f"$.decision_conditions[{condition_index}].evidence_ids[{evidence_index}]"
            entry = evidence_by_id.get(evidence_id)
            if entry is None:
                diagnostics.append(
                    _diagnostic(
                        "missing-decision-condition-evidence-reference",
                        f"Evidence ID {evidence_id!r} does not exist in the evidence ledger.",
                        path,
                        "FR-010",
                        "Add the evidence entry or use an existing evidence ID.",
                    )
                )
            elif area not in cast(Sequence[str], entry["affects"]):
                diagnostics.append(
                    _diagnostic(
                        "decision-condition-evidence-area-mismatch",
                        f"Evidence ID {evidence_id!r} is not classified for {area}.",
                        path,
                        "FR-010",
                        f"Add {area} to that evidence entry's affects list or cite "
                        "relevant evidence.",
                    )
                )
    return tuple(diagnostics)


def _typed_decision_conditions(
    conditions: Sequence[Mapping[str, Any]],
) -> tuple[DecisionCondition, ...]:
    return tuple(
        DecisionCondition(
            id=cast(str, raw["id"]),
            target_control_class=ControlClass(cast(str, raw["target_control_class"])),
            decision_area=DecisionArea(cast(str, raw["decision_area"])),
            statement=cast(str, raw["statement"]),
            status=DecisionConditionStatus(cast(str, raw["status"])),
            resolved_by=cast(str, raw["resolved_by"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in conditions
    )


def _typed_task(task: Mapping[str, Any] | None) -> TaskBoundary | None:
    if task is None:
        return None
    actions = tuple(
        TaskAction(
            id=cast(str, action["id"]),
            description=cast(str, action["description"]),
            consequential=cast(bool, action["consequential"]),
            approval_boundary=cast(str, action["approval_boundary"]),
        )
        for action in cast(Sequence[Mapping[str, Any]], task["actions"])
    )
    return TaskBoundary(
        operation=cast(str, task["operation"]),
        starts_when=cast(str, task["starts_when"]),
        completes_when=cast(str, task["completes_when"]),
        accountable_owner=cast(str, task["accountable_owner"]),
        actors=tuple(cast(Sequence[str], task["actors"])),
        systems_and_tools=tuple(cast(Sequence[str], task["systems_and_tools"])),
        information_read=tuple(cast(Sequence[str], task["information_read"])),
        actions=actions,
        exclusions=tuple(cast(Sequence[str], task["exclusions"])),
    )


def _typed_problem_value(problem: Mapping[str, Any] | None) -> ProblemValue | None:
    if problem is None:
        return None

    def statement(name: str) -> EvidencedStatement:
        raw = cast(Mapping[str, Any], problem[name])
        return EvidencedStatement(
            statement=cast(str, raw["statement"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )

    outcomes = tuple(
        ProblemOutcome(
            id=cast(str, raw["id"]),
            description=cast(str, raw["description"]),
            measure=cast(str, raw["measure"]),
            target=cast(str, raw["target"]),
            baseline_id=cast(str, raw["baseline_id"]),
            binding=cast(bool, raw["binding"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], problem["outcomes"])
    )
    baselines = tuple(
        ProblemBaseline(
            id=cast(str, raw["id"]),
            description=cast(str, raw["description"]),
            measure=cast(str, raw["measure"]),
            value=cast(str, raw["value"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], problem["baselines"])
    )
    constraints = tuple(
        ProblemConstraint(
            id=cast(str, raw["id"]),
            description=cast(str, raw["description"]),
            test=cast(str, raw["test"]),
            required_result=cast(str, raw["required_result"]),
            binding=cast(bool, raw["binding"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], problem["constraints"])
    )
    return ProblemValue(
        outcomes=outcomes,
        baselines=baselines,
        constraints=constraints,
        affected_volume=statement("affected_volume"),
        material_pain=statement("material_pain"),
        error_cost=statement("error_cost"),
        technology_limitation=statement("technology_limitation"),
    )


def _typed_agency_necessity(agency: Mapping[str, Any] | None) -> AgencyNecessity | None:
    if agency is None:
        return None

    def question(name: str) -> AgencyQuestion:
        raw = cast(Mapping[str, Any], agency[name])
        return AgencyQuestion(
            answer=AgencyAnswer(cast(str, raw["answer"])),
            rationale=cast(str, raw["rationale"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )

    residual_cases = tuple(
        ResidualCase(
            id=cast(str, raw["id"]),
            description=cast(str, raw["description"]),
            fixed_workflow_failure=cast(str, raw["fixed_workflow_failure"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], agency["residual_cases"])
    )
    return AgencyNecessity(
        execution_steps_predefinable=question("execution_steps_predefinable"),
        step_count_or_order_predictable=question("step_count_or_order_predictable"),
        runtime_tool_choice_required=question("runtime_tool_choice_required"),
        runtime_replanning_required=question("runtime_replanning_required"),
        environmental_feedback_available=question("environmental_feedback_available"),
        completion_independently_verifiable=question("completion_independently_verifiable"),
        effects_independently_verifiable=question("effects_independently_verifiable"),
        fixed_workflow_sufficient=question("fixed_workflow_sufficient"),
        residual_cases=residual_cases,
    )


def _typed_autonomy_permission(
    autonomy: Mapping[str, Any] | None,
) -> AutonomyPermission | None:
    if autonomy is None:
        return None

    def question(name: str) -> AutonomyQuestion:
        raw = cast(Mapping[str, Any], autonomy[name])
        return AutonomyQuestion(
            answer=AutonomyAnswer(cast(str, raw["answer"])),
            rationale=cast(str, raw["rationale"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )

    hard_vetoes = tuple(
        HardVeto(
            id=cast(str, raw["id"]),
            status=HardVetoStatus(cast(str, raw["status"])),
            condition=cast(str, raw["condition"]),
            consequence=cast(str, raw["consequence"]),
            action_ids=tuple(cast(Sequence[str], raw["action_ids"])),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], autonomy["hard_vetoes"])
    )
    human_controls = tuple(
        MandatoryHumanControl(
            id=cast(str, raw["id"]),
            description=cast(str, raw["description"]),
            control_point=cast(str, raw["control_point"]),
            responsible_role=cast(str, raw["responsible_role"]),
            action_ids=tuple(cast(Sequence[str], raw["action_ids"])),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )
        for raw in cast(Sequence[Mapping[str, Any]], autonomy["mandatory_human_controls"])
    )
    return AutonomyPermission(
        actions_reversible=question("actions_reversible"),
        failure_blast_radius_bounded=question("failure_blast_radius_bounded"),
        regulatory_automation_permitted=question("regulatory_automation_permitted"),
        data_confidence_sufficient=question("data_confidence_sufficient"),
        accountable_owner_assigned=question("accountable_owner_assigned"),
        decision_path_auditable=question("decision_path_auditable"),
        timely_human_intervention_available=question("timely_human_intervention_available"),
        safe_degradation_available=question("safe_degradation_available"),
        hard_vetoes=hard_vetoes,
        mandatory_human_controls=human_controls,
    )


def _typed_candidate_comparison(
    comparison: Mapping[str, Any] | None,
) -> CandidateComparison | None:
    if comparison is None:
        return None

    candidates = tuple(
        Candidate(
            id=cast(str, raw["id"]),
            name=cast(str, raw["name"]),
            description=cast(str, raw["description"]),
            control_class=ControlClass(cast(str, raw["control_class"])),
            roles=tuple(CandidateRole(value) for value in cast(Sequence[str], raw["roles"])),
            material_deviations=tuple(cast(Sequence[str], raw["material_deviations"])),
            outcome_tests=tuple(
                CandidateOutcomeTest(
                    outcome_id=cast(str, test["outcome_id"]),
                    result=CandidateTestResult(cast(str, test["result"])),
                    rationale=cast(str, test["rationale"]),
                    evidence_ids=tuple(cast(Sequence[str], test["evidence_ids"])),
                )
                for test in cast(Sequence[Mapping[str, Any]], raw["outcome_tests"])
            ),
            constraint_tests=tuple(
                CandidateConstraintTest(
                    constraint_id=cast(str, test["constraint_id"]),
                    result=CandidateTestResult(cast(str, test["result"])),
                    rationale=cast(str, test["rationale"]),
                    evidence_ids=tuple(cast(Sequence[str], test["evidence_ids"])),
                )
                for test in cast(Sequence[Mapping[str, Any]], raw["constraint_tests"])
            ),
        )
        for raw in cast(Sequence[Mapping[str, Any]], comparison["candidates"])
    )

    def typed_dimension(raw: Mapping[str, Any]) -> ComparisonDimension:
        return ComparisonDimension(
            result=ComparisonResult(cast(str, raw["result"])),
            rationale=cast(str, raw["rationale"]),
            evidence_ids=tuple(cast(Sequence[str], raw["evidence_ids"])),
        )

    comparisons = tuple(
        CandidatePairComparison(
            subject_candidate_id=cast(str, raw["subject_candidate_id"]),
            comparator_candidate_id=cast(str, raw["comparator_candidate_id"]),
            dimensions=ComparisonDimensions(
                **{
                    name: typed_dimension(cast(Mapping[str, Any], raw["dimensions"][name]))
                    for name in _COMPARISON_DIMENSION_FIELDS
                }
            ),
        )
        for raw in cast(Sequence[Mapping[str, Any]], comparison["comparisons"])
    )
    return CandidateComparison(candidates=candidates, comparisons=comparisons)


def _typed_evidence(entries: Sequence[Mapping[str, Any]]) -> tuple[Evidence, ...]:
    typed: list[Evidence] = []
    for entry in entries:
        identifier = cast(str, entry["id"])
        claim = cast(str, entry["claim"])
        owner = cast(str, entry["owner"])
        affects = tuple(DecisionArea(value) for value in cast(Sequence[str], entry["affects"]))
        kind = EvidenceKind(cast(str, entry["kind"]))
        if kind is EvidenceKind.OBSERVED:
            typed.append(
                ObservedEvidence(
                    identifier,
                    claim,
                    owner,
                    affects,
                    provenance=cast(str, entry["provenance"]),
                    observed_at=date.fromisoformat(cast(str, entry["observed_at"])),
                )
            )
        elif kind is EvidenceKind.ASSUMPTION:
            typed.append(
                AssumptionEvidence(
                    identifier,
                    claim,
                    owner,
                    affects,
                    falsified_by=cast(str, entry["falsified_by"]),
                )
            )
        elif kind is EvidenceKind.ESTIMATE:
            typed.append(
                EstimateEvidence(
                    identifier,
                    claim,
                    owner,
                    affects,
                    method=cast(str, entry["method"]),
                )
            )
        else:
            typed.append(
                MissingEvidence(
                    identifier,
                    claim,
                    owner,
                    affects,
                    resolved_by=cast(str, entry["resolved_by"]),
                )
            )
    return tuple(typed)


def _is_credible_support(entry: Evidence | None) -> bool:
    return (isinstance(entry, ObservedEvidence) and bool(entry.provenance.strip())) or (
        isinstance(entry, EstimateEvidence) and bool(entry.method.strip())
    )


def evaluate_problem_value_readiness(dossier: Dossier) -> ProblemValueReadiness:
    """Evaluate FR-005 prerequisites without selecting or scoring an architecture."""
    problem = dossier.problem_value
    if problem is None:
        return ProblemValueReadiness(
            False,
            (
                PrerequisiteFinding(
                    "problem-value-missing",
                    "$.problem_value",
                    "FR-005",
                    "The dossier does not define its problem-value contract.",
                    "Add measurable outcomes, baselines, constraints, and the four required "
                    "statements.",
                ),
            ),
        )

    findings: list[PrerequisiteFinding] = []
    binding_outcomes = [
        (index, outcome) for index, outcome in enumerate(problem.outcomes) if outcome.binding
    ]
    if not binding_outcomes:
        findings.append(
            PrerequisiteFinding(
                "binding-outcome-missing",
                "$.problem_value.outcomes",
                "FR-005",
                "No measurable outcome is marked as binding.",
                "Mark at least one required outcome as binding or add one.",
            )
        )

    baselines = {baseline.id: baseline for baseline in problem.baselines}
    evidence = {entry.id: entry for entry in dossier.evidence}
    for index, outcome in binding_outcomes:
        baseline = baselines.get(outcome.baseline_id)
        if baseline is None:
            findings.append(
                PrerequisiteFinding(
                    "baseline-reference-unresolved",
                    f"$.problem_value.outcomes[{index}].baseline_id",
                    "FR-005",
                    f"Binding outcome {outcome.id!r} has no resolved baseline.",
                    "Validate the dossier and reference an existing baseline.",
                )
            )
            continue
        credible = any(
            _is_credible_support(evidence.get(identifier)) for identifier in baseline.evidence_ids
        )
        if not credible:
            findings.append(
                PrerequisiteFinding(
                    "credible-baseline-missing",
                    f"$.problem_value.outcomes[{index}].baseline_id",
                    "FR-005",
                    f"Binding outcome {outcome.id!r} uses baseline {baseline.id!r} without "
                    "observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate from that "
                    "baseline.",
                    baseline.evidence_ids,
                )
            )
    return ProblemValueReadiness(not findings, tuple(findings))


def evaluate_agency_necessity_readiness(dossier: Dossier) -> AgencyNecessityReadiness:
    """Evaluate FR-006 fact readiness without deciding whether agency is necessary."""
    agency = dossier.agency_necessity
    if agency is None:
        return AgencyNecessityReadiness(
            False,
            (
                PrerequisiteFinding(
                    "agency-necessity-missing",
                    "$.agency_necessity",
                    "FR-006",
                    "The dossier does not define its agency-necessity facts.",
                    "Answer all eight agency questions and record residual cases explicitly.",
                ),
            ),
        )

    findings: list[PrerequisiteFinding] = []
    evidence = {entry.id: entry for entry in dossier.evidence}
    for name in _AGENCY_QUESTION_FIELDS:
        question = cast(AgencyQuestion, getattr(agency, name))
        if question.answer is AgencyAnswer.UNKNOWN:
            findings.append(
                PrerequisiteFinding(
                    "agency-answer-unknown",
                    f"$.agency_necessity.{name}.answer",
                    "FR-006",
                    f"Agency question {name!r} is unanswered.",
                    "Replace unknown with yes or no when the evidence supports an answer.",
                    question.evidence_ids,
                )
            )
        if not any(
            _is_credible_support(evidence.get(identifier)) for identifier in question.evidence_ids
        ):
            findings.append(
                PrerequisiteFinding(
                    "credible-agency-evidence-missing",
                    f"$.agency_necessity.{name}.evidence_ids",
                    "FR-006",
                    f"Agency question {name!r} lacks observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate.",
                    question.evidence_ids,
                )
            )

    for index, residual in enumerate(agency.residual_cases):
        if not any(
            _is_credible_support(evidence.get(identifier)) for identifier in residual.evidence_ids
        ):
            findings.append(
                PrerequisiteFinding(
                    "credible-residual-case-evidence-missing",
                    f"$.agency_necessity.residual_cases[{index}].evidence_ids",
                    "FR-006",
                    f"Residual case {residual.id!r} lacks observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate.",
                    residual.evidence_ids,
                )
            )
    return AgencyNecessityReadiness(not findings, tuple(findings))


def evaluate_autonomy_permission_readiness(dossier: Dossier) -> AutonomyPermissionReadiness:
    """Evaluate FR-007 fact readiness without deciding whether autonomy is permitted."""
    autonomy = dossier.autonomy_permission
    if autonomy is None:
        return AutonomyPermissionReadiness(
            False,
            (
                PrerequisiteFinding(
                    "autonomy-permission-missing",
                    "$.autonomy_permission",
                    "FR-007",
                    "The dossier does not define its autonomy-permission facts.",
                    "Answer all eight autonomy questions and record hard vetoes and human "
                    "controls explicitly.",
                ),
            ),
        )

    findings: list[PrerequisiteFinding] = []
    evidence = {entry.id: entry for entry in dossier.evidence}
    for name in _AUTONOMY_QUESTION_FIELDS:
        question = cast(AutonomyQuestion, getattr(autonomy, name))
        if question.answer is AutonomyAnswer.UNKNOWN:
            findings.append(
                PrerequisiteFinding(
                    "autonomy-answer-unknown",
                    f"$.autonomy_permission.{name}.answer",
                    "FR-007",
                    f"Autonomy question {name!r} is unanswered.",
                    "Replace unknown with yes or no when the evidence supports an answer.",
                    question.evidence_ids,
                )
            )
        if not any(
            _is_credible_support(evidence.get(identifier)) for identifier in question.evidence_ids
        ):
            findings.append(
                PrerequisiteFinding(
                    "credible-autonomy-evidence-missing",
                    f"$.autonomy_permission.{name}.evidence_ids",
                    "FR-007",
                    f"Autonomy question {name!r} lacks observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate.",
                    question.evidence_ids,
                )
            )

    for index, veto in enumerate(autonomy.hard_vetoes):
        if veto.status is HardVetoStatus.UNKNOWN:
            findings.append(
                PrerequisiteFinding(
                    "hard-veto-status-unknown",
                    f"$.autonomy_permission.hard_vetoes[{index}].status",
                    "FR-007",
                    f"Hard veto {veto.id!r} has unknown applicability.",
                    "Replace unknown with active or inactive when evidence establishes it.",
                    veto.evidence_ids,
                )
            )
        if not any(
            _is_credible_support(evidence.get(identifier)) for identifier in veto.evidence_ids
        ):
            findings.append(
                PrerequisiteFinding(
                    "credible-hard-veto-evidence-missing",
                    f"$.autonomy_permission.hard_vetoes[{index}].evidence_ids",
                    "FR-007",
                    f"Hard veto {veto.id!r} lacks observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate.",
                    veto.evidence_ids,
                )
            )

    for index, control in enumerate(autonomy.mandatory_human_controls):
        if not any(
            _is_credible_support(evidence.get(identifier)) for identifier in control.evidence_ids
        ):
            findings.append(
                PrerequisiteFinding(
                    "credible-human-control-evidence-missing",
                    f"$.autonomy_permission.mandatory_human_controls[{index}].evidence_ids",
                    "FR-007",
                    f"Mandatory human control {control.id!r} lacks observed or estimated support.",
                    "Cite at least one observed entry or method-backed estimate.",
                    control.evidence_ids,
                )
            )
    return AutonomyPermissionReadiness(not findings, tuple(findings))


def evaluate_candidate_comparison_readiness(dossier: Dossier) -> CandidateComparisonReadiness:
    """Evaluate FR-008 comparison readiness without selecting or ranking a candidate."""
    comparison = dossier.candidate_comparison
    if comparison is None:
        return CandidateComparisonReadiness(
            False,
            (
                PrerequisiteFinding(
                    "candidate-comparison-missing",
                    "$.candidate_comparison",
                    "FR-008",
                    "The dossier does not define candidate-comparison facts.",
                    "Add candidates, roles, tests, and directional trade-off comparisons.",
                ),
            ),
        )

    findings: list[PrerequisiteFinding] = []
    evidence = {entry.id: entry for entry in dossier.evidence}
    role_candidates: dict[CandidateRole, tuple[int, Candidate]] = {}
    role_paths: dict[CandidateRole, str] = {}
    for candidate_index, candidate in enumerate(comparison.candidates):
        for role_index, role in enumerate(candidate.roles):
            role_candidates.setdefault(role, (candidate_index, candidate))
            role_paths.setdefault(
                role,
                f"$.candidate_comparison.candidates[{candidate_index}].roles[{role_index}]",
            )

    def require_role(role: CandidateRole) -> tuple[int, Candidate] | None:
        assigned = role_candidates.get(role)
        if assigned is None:
            findings.append(
                PrerequisiteFinding(
                    "required-candidate-role-missing",
                    "$.candidate_comparison.candidates",
                    "FR-008",
                    f"No candidate has the required role {role.value!r}.",
                    f"Assign {role.value!r} to exactly one applicable candidate.",
                )
            )
        return assigned

    current = require_role(CandidateRole.CURRENT_BASELINE)
    proposed = require_role(CandidateRole.PROPOSED)
    strongest = role_candidates.get(CandidateRole.STRONGEST_SIMPLER)
    agentic = role_candidates.get(CandidateRole.AGENTIC_COMPARATOR)

    if proposed is not None:
        proposed_rank = _CONTROL_CLASS_ORDER.index(proposed[1].control_class)
        if proposed_rank > 0:
            if strongest is None:
                require_role(CandidateRole.STRONGEST_SIMPLER)
            elif _CONTROL_CLASS_ORDER.index(strongest[1].control_class) >= proposed_rank:
                findings.append(
                    PrerequisiteFinding(
                        "candidate-role-incompatible",
                        role_paths[CandidateRole.STRONGEST_SIMPLER],
                        "FR-008",
                        f"Candidate {strongest[1].id!r} is not strictly simpler than proposed "
                        f"candidate {proposed[1].id!r}.",
                        "Assign strongest-simpler to a candidate with a lower control class.",
                    )
                )
        elif strongest is not None:
            findings.append(
                PrerequisiteFinding(
                    "candidate-role-incompatible",
                    role_paths[CandidateRole.STRONGEST_SIMPLER],
                    "FR-008",
                    "A human-owned-work proposal has no simpler control class.",
                    "Remove the strongest-simpler role for this proposal.",
                )
            )

    agentic_candidates = [
        candidate
        for candidate in comparison.candidates
        if candidate.control_class is ControlClass.AGENTIC_CONTROL
    ]
    if agentic_candidates and agentic is None:
        require_role(CandidateRole.AGENTIC_COMPARATOR)
    if agentic is not None and agentic[1].control_class is not ControlClass.AGENTIC_CONTROL:
        findings.append(
            PrerequisiteFinding(
                "candidate-role-incompatible",
                role_paths[CandidateRole.AGENTIC_COMPARATOR],
                "FR-008",
                f"Candidate {agentic[1].id!r} is not an agentic-control candidate.",
                "Assign agentic-comparator to an agentic-control candidate.",
            )
        )

    problem = dossier.problem_value
    if problem is None:
        findings.append(
            PrerequisiteFinding(
                "candidate-problem-value-missing",
                "$.problem_value",
                "FR-008",
                "Candidate coverage cannot be checked without the problem-value contract.",
                "Add problem-value outcomes and constraints before completing comparisons.",
            )
        )
    else:
        for candidate_index, candidate in enumerate(comparison.candidates):
            tested_outcomes = {test.outcome_id for test in candidate.outcome_tests}
            for outcome in problem.outcomes:
                if outcome.id not in tested_outcomes:
                    findings.append(
                        PrerequisiteFinding(
                            "candidate-outcome-test-missing",
                            f"$.candidate_comparison.candidates[{candidate_index}].outcome_tests",
                            "FR-008",
                            f"Candidate {candidate.id!r} does not test outcome {outcome.id!r}.",
                            "Add exactly one test for every problem-value outcome.",
                        )
                    )
            tested_constraints = {test.constraint_id for test in candidate.constraint_tests}
            for constraint in problem.constraints:
                if constraint.id not in tested_constraints:
                    findings.append(
                        PrerequisiteFinding(
                            "candidate-constraint-test-missing",
                            f"$.candidate_comparison.candidates[{candidate_index}]."
                            "constraint_tests",
                            "FR-008",
                            f"Candidate {candidate.id!r} does not test constraint "
                            f"{constraint.id!r}.",
                            "Add exactly one test for every problem-value constraint.",
                        )
                    )

    for candidate_index, candidate in enumerate(comparison.candidates):
        test_groups: tuple[
            tuple[str, Sequence[CandidateOutcomeTest | CandidateConstraintTest]], ...
        ] = (
            ("outcome_tests", candidate.outcome_tests),
            ("constraint_tests", candidate.constraint_tests),
        )
        for collection, tests in test_groups:
            for test_index, test in enumerate(tests):
                if test.result is CandidateTestResult.UNKNOWN:
                    findings.append(
                        PrerequisiteFinding(
                            "candidate-test-result-unknown",
                            f"$.candidate_comparison.candidates[{candidate_index}]."
                            f"{collection}[{test_index}].result",
                            "FR-008",
                            f"Candidate {candidate.id!r} has an unknown {collection} result.",
                            "Replace unknown with meets or fails when evidence supports it.",
                            test.evidence_ids,
                        )
                    )
                if not any(
                    _is_credible_support(evidence.get(identifier))
                    for identifier in test.evidence_ids
                ):
                    findings.append(
                        PrerequisiteFinding(
                            "credible-candidate-test-evidence-missing",
                            f"$.candidate_comparison.candidates[{candidate_index}]."
                            f"{collection}[{test_index}].evidence_ids",
                            "FR-008",
                            f"Candidate {candidate.id!r} has a test without observed or "
                            "estimated support.",
                            "Cite at least one observed entry or method-backed estimate.",
                            test.evidence_ids,
                        )
                    )

    authored_pairs = {
        (pair.subject_candidate_id, pair.comparator_candidate_id) for pair in comparison.comparisons
    }
    required_pairs: list[tuple[str, str]] = []
    if current is not None:
        current_id = current[1].id
        required_pairs.extend(
            (candidate.id, current_id)
            for candidate in comparison.candidates
            if candidate.id != current_id
        )
    if proposed is not None and strongest is not None and proposed[1].id != strongest[1].id:
        required_pairs.append((proposed[1].id, strongest[1].id))
    for subject_id, comparator_id in dict.fromkeys(required_pairs):
        if (subject_id, comparator_id) not in authored_pairs:
            findings.append(
                PrerequisiteFinding(
                    "required-comparison-missing",
                    "$.candidate_comparison.comparisons",
                    "FR-008",
                    f"Required directed comparison {subject_id!r} versus "
                    f"{comparator_id!r} is missing.",
                    "Add the directed pair with all 11 trade-off dimensions.",
                )
            )

    for comparison_index, pair in enumerate(comparison.comparisons):
        for dimension_name in _COMPARISON_DIMENSION_FIELDS:
            dimension = cast(ComparisonDimension, getattr(pair.dimensions, dimension_name))
            if dimension.result is ComparisonResult.UNKNOWN:
                findings.append(
                    PrerequisiteFinding(
                        "comparison-result-unknown",
                        f"$.candidate_comparison.comparisons[{comparison_index}]."
                        f"dimensions.{dimension_name}.result",
                        "FR-008",
                        f"Comparison dimension {dimension_name!r} is unknown for "
                        f"{pair.subject_candidate_id!r} versus {pair.comparator_candidate_id!r}.",
                        "Replace unknown with better, equivalent, or worse when supported.",
                        dimension.evidence_ids,
                    )
                )
            if not any(
                _is_credible_support(evidence.get(identifier))
                for identifier in dimension.evidence_ids
            ):
                findings.append(
                    PrerequisiteFinding(
                        "credible-comparison-evidence-missing",
                        f"$.candidate_comparison.comparisons[{comparison_index}]."
                        f"dimensions.{dimension_name}.evidence_ids",
                        "FR-008",
                        f"Comparison dimension {dimension_name!r} lacks observed or estimated "
                        "support.",
                        "Cite at least one observed entry or method-backed estimate.",
                        dimension.evidence_ids,
                    )
                )
    return CandidateComparisonReadiness(not findings, tuple(findings))


def _case_file(workspace: Path) -> tuple[Path | None, ValidationResult | None]:
    try:
        root = workspace.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "workspace-missing",
                    "The case workspace directory does not exist.",
                    "$",
                    "FR-001",
                    "Create it with `archsift init <case>` or provide an existing workspace.",
                ),
            ),
        )
    except (OSError, RuntimeError):
        # Symbolic-link loops and permission errors are path-boundary
        # failures, not malformed input or internal errors.
        return None, ValidationResult(
            ExitCode.UNSAFE_PATH,
            diagnostics=(
                _diagnostic(
                    "workspace-unresolvable",
                    "The case workspace path cannot be resolved to a directory.",
                    "$",
                    "NFR-004",
                    "Fix symlink loops or permissions so the path resolves to a real directory.",
                ),
            ),
        )
    if not root.is_dir():
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "workspace-not-directory",
                    "The case workspace path is not a directory.",
                    "$",
                    "FR-001",
                    "Provide the directory containing case.yaml.",
                ),
            ),
        )

    candidate = root / "case.yaml"
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "case-file-missing",
                    "The workspace does not contain case.yaml.",
                    "$",
                    "FR-001",
                    "Run `archsift init <case>` or add the required case.yaml file.",
                ),
            ),
        )
    except (OSError, RuntimeError):
        # A symbolic-link loop in case.yaml is a path-boundary failure, not
        # malformed YAML or an internal error: it fails closed without
        # reading anything.
        return None, ValidationResult(
            ExitCode.UNSAFE_PATH,
            diagnostics=(
                _diagnostic(
                    "case-file-unresolvable",
                    "case.yaml cannot be resolved to a regular file.",
                    "$",
                    "NFR-004",
                    "Fix symlink loops or permissions so case.yaml resolves inside the workspace.",
                ),
            ),
        )
    if not resolved.is_relative_to(root):
        return None, ValidationResult(
            ExitCode.UNSAFE_PATH,
            diagnostics=(
                _diagnostic(
                    "case-file-outside-workspace",
                    "case.yaml resolves outside the case workspace.",
                    "$",
                    "NFR-004",
                    "Replace the link with a regular case.yaml file inside the workspace.",
                ),
            ),
        )
    if not resolved.is_file():
        return None, ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "case-file-not-regular",
                    "case.yaml is not a regular file.",
                    "$",
                    "FR-002",
                    "Replace it with a UTF-8 YAML file.",
                ),
            ),
        )
    return resolved, None


def validate_workspace(workspace: Path) -> ValidationResult:
    """Safely load and validate one versioned case workspace."""
    case_file, failure = _case_file(workspace)
    if failure is not None:
        return failure
    assert case_file is not None

    try:
        # utf-8-sig accepts plain UTF-8 and strips a leading BOM so Windows
        # tooling output remains valid YAML.
        with case_file.open(encoding="utf-8-sig") as stream:
            # _DossierLoader keeps the SafeLoader constructor set while
            # rejecting mappings with duplicate keys.
            loaded: Any = yaml.load(stream, Loader=_DossierLoader)
    except (OSError, UnicodeError, RecursionError, yaml.YAMLError) as error:
        # RecursionError covers pathologically nested documents; both are
        # malformed input, not internal failures.
        return ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "malformed-yaml",
                    f"case.yaml could not be loaded as UTF-8 YAML: {_yaml_load_message(error)}.",
                    "$",
                    "FR-012",
                    "Correct the YAML syntax and encoding, then run validation again.",
                ),
            ),
        )

    if not isinstance(loaded, Mapping):
        return ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "dossier-not-mapping",
                    "The dossier root must be a YAML mapping.",
                    "$",
                    "FR-002",
                    "Replace the document with a mapping containing schema_version and case.",
                ),
            ),
        )

    if "schema_version" not in loaded:
        return ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "schema-version-missing",
                    "The required schema_version field is missing.",
                    "$.schema_version",
                    "FR-002",
                    "Add `schema_version: 1` at the dossier root.",
                ),
            ),
        )
    if type(loaded["schema_version"]) is not int or loaded["schema_version"] != 1:
        return ValidationResult(
            ExitCode.UNSUPPORTED_SCHEMA,
            diagnostics=(
                _diagnostic(
                    "schema-version-unsupported",
                    f"Schema version {loaded['schema_version']!r} is not supported.",
                    "$.schema_version",
                    "FR-002",
                    "Use schema_version 1 or upgrade ArchSift when a newer version is supported.",
                ),
            ),
        )

    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(loaded),
        key=lambda item: (_field_path(list(item.absolute_path)), item.validator, item.message),
    )
    if errors:
        diagnostics = tuple(
            diagnostic for error in errors for diagnostic in _schema_diagnostics(error)
        )
        return ValidationResult(ExitCode.VALIDATION_FAILED, diagnostics=diagnostics)

    raw_evidence = cast(Sequence[Mapping[str, Any]], loaded.get("evidence", ()))
    raw_task = cast(Mapping[str, Any] | None, loaded.get("task"))
    raw_problem_value = cast(Mapping[str, Any] | None, loaded.get("problem_value"))
    raw_agency_necessity = cast(Mapping[str, Any] | None, loaded.get("agency_necessity"))
    raw_autonomy_permission = cast(Mapping[str, Any] | None, loaded.get("autonomy_permission"))
    raw_candidate_comparison = cast(Mapping[str, Any] | None, loaded.get("candidate_comparison"))
    raw_decision_conditions = cast(
        Sequence[Mapping[str, Any]], loaded.get("decision_conditions", ())
    )
    semantic_diagnostics = sorted(
        (
            *_duplicate_evidence_diagnostics(raw_evidence),
            *_duplicate_task_action_diagnostics(raw_task),
            *_problem_value_semantic_diagnostics(raw_problem_value, raw_evidence),
            *_agency_necessity_semantic_diagnostics(raw_agency_necessity, raw_evidence),
            *_autonomy_permission_semantic_diagnostics(
                raw_autonomy_permission, raw_task, raw_evidence
            ),
            *_candidate_comparison_semantic_diagnostics(
                raw_candidate_comparison, raw_problem_value, raw_evidence
            ),
            *_decision_condition_semantic_diagnostics(raw_decision_conditions, raw_evidence),
        ),
        key=lambda diagnostic: (diagnostic.field, diagnostic.id, diagnostic.message),
    )
    if semantic_diagnostics:
        return ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=tuple(semantic_diagnostics),
        )

    case = loaded["case"]
    assert isinstance(case, Mapping)
    dossier = Dossier(
        schema_version=1,
        case=CaseIdentity(id=str(case["id"]), title=str(case["title"])),
        evidence=_typed_evidence(raw_evidence),
        task=_typed_task(raw_task),
        problem_value=_typed_problem_value(raw_problem_value),
        agency_necessity=_typed_agency_necessity(raw_agency_necessity),
        autonomy_permission=_typed_autonomy_permission(raw_autonomy_permission),
        candidate_comparison=_typed_candidate_comparison(raw_candidate_comparison),
        decision_conditions=_typed_decision_conditions(raw_decision_conditions),
    )
    return ValidationResult(ExitCode.SUCCESS, dossier=dossier)
