"""Deterministic injection-safe Markdown views of decision records."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from typing import Any, Final, cast

from archsift import artefacts as a
from archsift import decision as d
from archsift import decision_record as dr
from archsift import rules as r
from archsift import validation as v

REPORT_FORMAT_VERSION: Final = 1

# Fixed code-point ranges avoid Unicode-database drift across supported Python versions.
_NON_PRINTING_RANGES: Final = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF9, 0xFFFB),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
    (0xE0100, 0xE01EF),
)


class MarkdownReportError(ValueError):
    """A decision record cannot be rendered without ambiguity."""


_EXPECTED_ENUM_VALUES: Final[dict[type[Enum], tuple[str, ...]]] = {
    d.ArchitectureVerdict: (
        "supported",
        "conditional",
        "insufficient-evidence",
        "no-permissible-candidate",
        "no-technology-change",
    ),
    d.CandidateDisposition: ("eliminated", "undetermined", "survives"),
    d.ControlClassDisposition: ("eliminated", "undetermined", "survives"),
    d.CriterionKind: (
        "outcome",
        "constraint",
        "authority",
        "hard-veto",
        "human-control",
        "agency-question",
        "residual-case",
        "derived-agency",
    ),
    d.EvidenceState: ("evidence-complete", "evidence-incomplete"),
    dr.UnresolvedGapSource: ("prerequisite", "decision"),
    r.RuleEffect: (
        "block",
        "require-evidence",
        "support-candidate",
        "constrain-autonomy",
        "non-decisive",
    ),
    v.AgencyAnswer: ("yes", "no", "unknown"),
    v.AutonomyAnswer: ("yes", "no", "unknown"),
    v.CandidateRole: (
        "current-baseline",
        "proposed",
        "strongest-simpler",
        "agentic-comparator",
    ),
    v.CandidateTestResult: ("meets", "fails", "unknown"),
    v.ComparisonResult: ("better", "equivalent", "worse", "unknown"),
    v.ControlClass: (
        "human-owned-work",
        "process-redesign",
        "deterministic-automation",
        "fixed-ai-workflow",
        "agentic-control",
    ),
    v.DecisionArea: (
        "problem-value",
        "agency-necessity",
        "autonomy-permission",
        "comparative-fit",
    ),
    v.DecisionConditionStatus: ("met", "unmet"),
    v.EvidenceArtefactRoot: ("workspace", "external"),
    v.EvidenceKind: ("observed", "assumption", "estimate", "missing"),
    v.HardVetoStatus: ("active", "inactive", "unknown"),
}

if any(
    tuple(item.value for item in enum_type) != values
    for enum_type, values in _EXPECTED_ENUM_VALUES.items()
):  # pragma: no cover - package invariant
    raise RuntimeError("Markdown report enum coverage is incomplete.")

_EXPECTED_FIELDS: Final[dict[type[object], tuple[str, ...]]] = {
    a.EvidenceArtefactIdentity: (
        "evidence_id",
        "artefact_id",
        "root",
        "path",
        "byte_length",
        "content_identity",
    ),
    d.AssessmentEvaluation: (
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
    ),
    d.CandidateElimination: ("candidate_id", "control_class", "disposition"),
    d.ControlClassElimination: ("control_class", "candidate_ids", "disposition"),
    d.DecisionFinding: (
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
    ),
    d.OrderedEliminationEvaluation: (
        "ruleset_version",
        "candidates",
        "control_classes",
        "findings",
        "least_surviving_class",
    ),
    dr.AssessmentConfiguration: ("schema_version", "entries"),
    dr.AssessmentConfigurationEntry: ("key", "value"),
    dr.DecisionGap: (
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
    ),
    dr.DecisionRecord: (
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
    ),
    dr.EvidenceLink: ("evidence_id", "kind", "content_identity"),
    dr.PrerequisiteGap: (
        "source",
        "rule_id",
        "field",
        "requirement",
        "effect",
        "message",
        "consequence",
        "remediation",
        "evidence_ids",
    ),
    dr.ReassessmentTrigger: ("evidence_id", "kind", "observation"),
    r.AssessmentPrerequisiteEvaluation: ("ruleset_version", "ready", "findings"),
    r.AssessmentPrerequisiteFinding: (
        "rule_id",
        "field",
        "requirement",
        "effect",
        "message",
        "consequence",
        "remediation",
        "evidence_ids",
    ),
    v.AgencyNecessity: (
        "execution_steps_predefinable",
        "step_count_or_order_predictable",
        "runtime_tool_choice_required",
        "runtime_replanning_required",
        "environmental_feedback_available",
        "completion_independently_verifiable",
        "effects_independently_verifiable",
        "fixed_workflow_sufficient",
        "residual_cases",
    ),
    v.AgencyQuestion: ("answer", "rationale", "evidence_ids"),
    v.AssumptionEvidence: ("id", "claim", "owner", "affects", "falsified_by", "artefacts"),
    v.AutonomyPermission: (
        "actions_reversible",
        "failure_blast_radius_bounded",
        "regulatory_automation_permitted",
        "data_confidence_sufficient",
        "accountable_owner_assigned",
        "decision_path_auditable",
        "timely_human_intervention_available",
        "safe_degradation_available",
        "hard_vetoes",
        "mandatory_human_controls",
    ),
    v.AutonomyQuestion: ("answer", "rationale", "evidence_ids"),
    v.Candidate: (
        "id",
        "name",
        "description",
        "control_class",
        "roles",
        "material_deviations",
        "outcome_tests",
        "constraint_tests",
        "authority",
    ),
    v.CandidateAuthority: ("action_ids", "retained_human_control_ids", "evidence_ids"),
    v.CandidateComparison: ("candidates", "comparisons"),
    v.CandidateConstraintTest: ("constraint_id", "result", "rationale", "evidence_ids"),
    v.CandidateOutcomeTest: ("outcome_id", "result", "rationale", "evidence_ids"),
    v.CandidatePairComparison: ("subject_candidate_id", "comparator_candidate_id", "dimensions"),
    v.CaseIdentity: ("id", "title"),
    v.ComparisonDimension: ("result", "rationale", "evidence_ids"),
    v.ComparisonDimensions: (
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
    ),
    v.DecisionCondition: (
        "id",
        "target_control_class",
        "decision_area",
        "statement",
        "status",
        "resolved_by",
        "evidence_ids",
    ),
    v.Dossier: (
        "schema_version",
        "case",
        "evidence",
        "task",
        "problem_value",
        "agency_necessity",
        "autonomy_permission",
        "candidate_comparison",
        "decision_conditions",
    ),
    v.EstimateEvidence: ("id", "claim", "owner", "affects", "method", "artefacts"),
    v.EvidenceArtefactReference: ("id", "root", "path"),
    v.EvidencedStatement: ("statement", "evidence_ids"),
    v.HardVeto: (
        "id",
        "status",
        "condition",
        "consequence",
        "action_ids",
        "evidence_ids",
        "prohibited_control_classes",
    ),
    v.MandatoryHumanControl: (
        "id",
        "description",
        "control_point",
        "responsible_role",
        "action_ids",
        "evidence_ids",
    ),
    v.MissingEvidence: ("id", "claim", "owner", "affects", "resolved_by", "artefacts"),
    v.ObservedEvidence: (
        "id",
        "claim",
        "owner",
        "affects",
        "provenance",
        "observed_at",
        "artefacts",
    ),
    v.ProblemBaseline: ("id", "description", "measure", "value", "evidence_ids"),
    v.ProblemConstraint: (
        "id",
        "description",
        "test",
        "required_result",
        "binding",
        "evidence_ids",
    ),
    v.ProblemOutcome: (
        "id",
        "description",
        "measure",
        "target",
        "baseline_id",
        "binding",
        "evidence_ids",
    ),
    v.ProblemValue: (
        "outcomes",
        "baselines",
        "constraints",
        "affected_volume",
        "material_pain",
        "error_cost",
        "technology_limitation",
    ),
    v.ResidualCase: ("id", "description", "fixed_workflow_failure", "evidence_ids"),
    v.TaskAction: ("id", "description", "consequential", "approval_boundary"),
    v.TaskBoundary: (
        "operation",
        "starts_when",
        "completes_when",
        "accountable_owner",
        "actors",
        "systems_and_tools",
        "information_read",
        "actions",
        "exclusions",
    ),
}
if any(
    tuple(field.name for field in fields(cast(Any, value_type))) != expected
    for value_type, expected in _EXPECTED_FIELDS.items()
):  # pragma: no cover - package invariant
    raise RuntimeError("Markdown report dataclass coverage is incomplete.")


def _assert_contract(value: object, expected_type: type[object]) -> None:
    if type(value) is not expected_type or not is_dataclass(value):
        raise MarkdownReportError(f"Unsupported {expected_type.__name__} report value.")
    actual = tuple(field.name for field in fields(value))
    expected = _EXPECTED_FIELDS.get(expected_type)
    if expected is None or actual != expected:
        raise MarkdownReportError(f"Unsupported {expected_type.__name__} report contract.")


def _visible_text(value: str) -> str:
    rendered: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character == "\\":
            rendered.append("\\\\")
        elif codepoint in {0x2028, 0x2029} or any(
            start <= codepoint <= end for start, end in _NON_PRINTING_RANGES
        ):
            prefix, width = ("u", 4) if codepoint <= 0xFFFF else ("U", 8)
            rendered.append(f"\\{prefix}{codepoint:0{width}x}")
        else:
            rendered.append(character)
    return "".join(rendered)


def _scalar_text(value: object) -> str:
    if value is None:
        return "(not provided)"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return _visible_text(value)
    if isinstance(value, Enum):
        enum_type = type(value)
        enum_value = value.value
        expected = _EXPECTED_ENUM_VALUES.get(enum_type)
        if type(enum_value) is not str or expected is None or enum_value not in expected:
            raise MarkdownReportError(f"Unsupported {enum_type.__name__} report value.")
        return _visible_text(enum_value)
    if type(value) is date:
        return value.isoformat()
    raise MarkdownReportError(f"Unsupported {type(value).__name__} report scalar.")


def _label(name: str) -> str:
    if not name or any(not (character.isalnum() or character in " -/()") for character in name):
        raise MarkdownReportError("Report labels must be fixed safe text.")
    return name


def _emit_scalar(lines: list[str], label: str, value: object) -> None:
    lines.extend((f"**{_label(label)}**", "", f"    {_scalar_text(value)}", ""))


def _emit_value(lines: list[str], label: str, value: object) -> None:
    safe_label = _label(label)
    if type(value) is tuple:
        lines.extend((f"**{safe_label}**", ""))
        if not value:
            lines.extend(("    (none)", ""))
            return
        for index, item in enumerate(value, start=1):
            _emit_value(lines, f"{safe_label} item {index}", item)
        return
    if is_dataclass(value):
        value_type = type(value)
        expected = _EXPECTED_FIELDS.get(value_type)
        if expected is None:
            raise MarkdownReportError(f"Unsupported {value_type.__name__} report type.")
        _assert_contract(value, value_type)
        lines.extend((f"**{safe_label}**", ""))
        for field_name in expected:
            _emit_value(lines, field_name.replace("_", " ").title(), getattr(value, field_name))
        return
    _emit_scalar(lines, safe_label, value)


def _section(lines: list[str], title: str, label: str, value: object) -> None:
    lines.extend((f"## {_label(title)}", ""))
    _emit_value(lines, label, value)


def render_markdown_decision_report(record: dr.DecisionRecord) -> bytes:
    """Return one deterministic Markdown review view without re-evaluating or performing I/O."""
    _assert_contract(record, dr.DecisionRecord)
    _assert_contract(record.dossier, v.Dossier)
    _assert_contract(record.assessment, d.AssessmentEvaluation)

    lines = ["# ArchSift Decision Report", ""]
    lines.extend(("## Record Metadata", ""))
    _emit_scalar(lines, "Report Format Version", REPORT_FORMAT_VERSION)
    _emit_scalar(lines, "Record Schema Version", record.record_schema_version)
    _emit_scalar(lines, "Record Content Identity", record.record_content_identity)
    _emit_scalar(lines, "Dossier Schema Version", record.dossier_schema_version)
    _emit_scalar(lines, "Dossier Content Identity", record.dossier_content_identity)
    _emit_scalar(lines, "Ruleset Version", record.ruleset_version)
    _emit_scalar(lines, "Tool Version", record.tool_version)
    _emit_value(lines, "Assessment Configuration", record.configuration)
    _emit_scalar(lines, "Configuration Content Identity", record.configuration_content_identity)

    _section(lines, "Case Identity", "Case", record.dossier.case)
    _section(lines, "Task Boundary", "Task", record.dossier.task)
    _section(lines, "Evidence Ledger", "Evidence", record.dossier.evidence)

    lines.extend(("## Decision Areas", "", "### Problem Value", ""))
    _emit_value(lines, "Problem Value", record.dossier.problem_value)
    lines.extend(("### Agency Necessity", ""))
    _emit_value(lines, "Agency Necessity", record.dossier.agency_necessity)
    lines.extend(("### Autonomy Permission", ""))
    _emit_value(lines, "Autonomy Permission", record.dossier.autonomy_permission)
    lines.extend(("### Comparative Fit", ""))
    _emit_value(lines, "Candidate Comparison and Trade-offs", record.dossier.candidate_comparison)

    _section(
        lines, "Decision Conditions", "Decision Conditions", record.dossier.decision_conditions
    )

    lines.extend(("## Verdict and Recommendation", ""))
    _emit_scalar(lines, "Assessment Schema Version", record.assessment.schema_version)
    _emit_scalar(lines, "Assessment Ruleset Version", record.assessment.ruleset_version)
    _emit_scalar(lines, "Verdict", record.assessment.verdict)
    _emit_scalar(lines, "Verdict Rule ID", record.assessment.verdict_rule_id)
    _emit_scalar(lines, "Qualitative Evidence State", record.assessment.evidence_state)
    recommendation: object = record.assessment.recommended_class
    if recommendation is None:
        if record.assessment.verdict is d.ArchitectureVerdict.INSUFFICIENT_EVIDENCE:
            recommendation = "(abstention)"
        elif record.assessment.verdict is d.ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE:
            recommendation = "(no permissible candidate)"
        else:
            raise MarkdownReportError("A recommending verdict has no recommended class.")
    _emit_scalar(lines, "Recommendation", recommendation)
    _emit_value(lines, "Surviving Candidate IDs", record.assessment.surviving_candidate_ids)
    _emit_value(lines, "Unmet Conditions", record.assessment.unmet_conditions)
    _emit_value(lines, "Active Hard Veto IDs", record.assessment.active_hard_veto_ids)
    _emit_value(
        lines,
        "Mandatory Human Control IDs",
        record.assessment.mandatory_human_control_ids,
    )

    lines.extend(("## Assessment Trace", ""))
    _emit_value(lines, "Prerequisite Evaluation", record.assessment.prerequisite_evaluation)
    _emit_value(
        lines,
        "Ordered Elimination Evaluation",
        record.assessment.ordered_elimination_evaluation,
    )

    _section(lines, "Evidence Identities", "Evidence Links", record.evidence_links)
    _section(lines, "Artefact Identities", "Artefact Links", record.artefact_links)
    _section(lines, "Unresolved Gaps", "Unresolved Gaps", record.unresolved_gaps)
    _section(
        lines,
        "Reassessment Triggers",
        "Reassessment Triggers",
        record.reassessment_triggers,
    )

    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
