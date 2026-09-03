"""Deterministic injection-safe Markdown views of decision records."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from typing import Any, Final, cast

from archsift import artefacts as a
from archsift import decision as d
from archsift import decision_record as dr
from archsift import masking as mk
from archsift import rules as r
from archsift import validation as v
from archsift.report_text import visible_text as _visible_text

REPORT_FORMAT_VERSION: Final = 2


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
    v.EvidenceAuthor: ("accountable-person", "assistant"),
    v.EvidenceArtefactRoot: ("workspace", "external"),
    v.EvidenceKind: ("observed", "assumption", "estimate", "missing"),
    v.ElicitationScale: ("ordinal", "categorical"),
    v.TargetKind: ("quantified", "directional", "no-regression"),
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
        "registration_id",
        "registration_content_identity",
        "declared_material_type",
        "repository_commit",
        "repository_logical_path",
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
        "graph_use",
    ),
    dr.EvidenceLink: ("evidence_id", "kind", "content_identity", "decision_bearing"),
    dr.GraphEntryReference: ("id", "content_identity"),
    dr.GraphUse: (
        "graph_schema_version",
        "graph_version",
        "graph_snapshot_content_identity",
        "case_view_content_identity",
        "supported_finding_rule_ids",
        "finding_relevant_nodes",
        "finding_relevant_relations",
    ),
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
        "counterpart",
    ),
    dr.ReassessmentTrigger: ("evidence_id", "kind", "observation", "decision_bearing"),
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
        "counterpart",
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
    v.AssumptionEvidence: (
        "id",
        "claim",
        "owner",
        "affects",
        "authorship",
        "falsified_by",
        "artefacts",
    ),
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
    v.BaselineRetention: ("declared_by", "rationale", "evidence_ids"),
    v.CandidateComparison: (
        "candidates",
        "comparisons",
        "strongest_simpler_boundary",
        "baseline_retention",
    ),
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
        "language",
        "evidence",
        "task",
        "problem_value",
        "agency_necessity",
        "autonomy_permission",
        "candidate_comparison",
        "decision_conditions",
    ),
    v.EstimateEvidence: (
        "id",
        "claim",
        "owner",
        "affects",
        "authorship",
        "method",
        "artefacts",
        "elicitation",
    ),
    v.EvidenceAuthorship: ("authored_by", "attested_by_accountable_person"),
    v.EvidenceArtefactReference: (
        "id",
        "root",
        "path",
        "registration_id",
        "registration_logical_path",
    ),
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
    v.MissingEvidence: (
        "id",
        "claim",
        "owner",
        "affects",
        "authorship",
        "resolved_by",
        "artefacts",
    ),
    v.ObservedEvidence: (
        "id",
        "claim",
        "owner",
        "affects",
        "authorship",
        "provenance",
        "observed_at",
        "artefacts",
    ),
    v.Elicitation: ("roles", "coverage", "scale"),
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
        "target_kind",
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
    v.StrongestSimplerBoundary: (
        "strongest_candidate_id",
        "scope",
        "rationale",
        "considered_candidate_ids",
        "evidence_ids",
    ),
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


def _scalar_text(value: object, *, maskable: bool) -> str:
    if value is None:
        return "(not provided)"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        # NFR-009: every authored string selected for output is masked before
        # the injection-safe escape, so the review view never emits a matched
        # sensitive value even when the underlying record keeps it. Structural
        # fields (identifiers, paths, identities, versions, controlled
        # vocabularies) are never masked.
        rendered = mk.mask_sensitive_text(value) if maskable else value
        return _visible_text(rendered)
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


def _emit_scalar(lines: list[str], label: str, value: object, *, maskable: bool = True) -> None:
    lines.extend((f"**{_label(label)}**", "", f"    {_scalar_text(value, maskable=maskable)}", ""))


def _emit_value(
    lines: list[str],
    label: str,
    value: object,
    *,
    maskable: bool = True,
    omit_evidence_authorship: bool = False,
) -> None:
    safe_label = _label(label)
    if type(value) is tuple:
        lines.extend((f"**{safe_label}**", ""))
        if not value:
            lines.extend(("    (none)", ""))
            return
        for index, item in enumerate(value, start=1):
            _emit_value(
                lines,
                f"{safe_label} item {index}",
                item,
                maskable=maskable,
                omit_evidence_authorship=omit_evidence_authorship,
            )
        return
    if is_dataclass(value):
        value_type = type(value)
        expected = _EXPECTED_FIELDS.get(value_type)
        if expected is None:
            raise MarkdownReportError(f"Unsupported {value_type.__name__} report type.")
        _assert_contract(value, value_type)
        lines.extend((f"**{safe_label}**", ""))
        for field_name in expected:
            if (
                omit_evidence_authorship
                and field_name == "authorship"
                and isinstance(value, v.EvidenceEntry)
            ):
                continue
            field_maskable = maskable and field_name not in mk.STRUCTURAL_KEYS
            _emit_value(
                lines,
                field_name.replace("_", " ").title(),
                getattr(value, field_name),
                maskable=field_maskable,
                omit_evidence_authorship=omit_evidence_authorship,
            )
        return
    _emit_scalar(lines, safe_label, value, maskable=maskable)


def _section(
    lines: list[str],
    title: str,
    label: str,
    value: object,
    *,
    omit_evidence_authorship: bool = False,
) -> None:
    lines.extend((f"## {_label(title)}", ""))
    _emit_value(lines, label, value, omit_evidence_authorship=omit_evidence_authorship)


def render_markdown_decision_report(record: dr.DecisionRecord) -> bytes:
    """Return one deterministic Markdown review view without re-evaluating or performing I/O."""
    _assert_contract(record, dr.DecisionRecord)
    _assert_contract(record.dossier, v.Dossier)
    _assert_contract(record.assessment, d.AssessmentEvaluation)

    lines = ["# ArchSift Decision Report", ""]
    lines.extend(("## Record Metadata", ""))
    _emit_scalar(lines, "Report Format Version", REPORT_FORMAT_VERSION, maskable=False)
    _emit_scalar(lines, "Record Schema Version", record.record_schema_version, maskable=False)
    _emit_scalar(lines, "Record Content Identity", record.record_content_identity, maskable=False)
    _emit_scalar(lines, "Dossier Schema Version", record.dossier_schema_version, maskable=False)
    # NFR-010: the review view states the language it is written in.
    _emit_scalar(lines, "Case Language", record.dossier.language, maskable=False)
    _emit_scalar(lines, "Dossier Content Identity", record.dossier_content_identity, maskable=False)
    _emit_scalar(lines, "Ruleset Version", record.ruleset_version, maskable=False)
    _emit_scalar(lines, "Tool Version", record.tool_version, maskable=False)
    _emit_value(lines, "Assessment Configuration", record.configuration)
    _emit_scalar(
        lines,
        "Configuration Content Identity",
        record.configuration_content_identity,
        maskable=False,
    )
    if record.graph_use is not None:
        _section(lines, "Graph Use", "Graph Use", record.graph_use)

    _section(lines, "Case Identity", "Case", record.dossier.case)
    _section(lines, "Task Boundary", "Task", record.dossier.task)
    _section(
        lines,
        "Evidence Ledger",
        "Evidence",
        record.dossier.evidence,
        omit_evidence_authorship=record.dossier_schema_version == 1,
    )

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
    _emit_scalar(
        lines, "Assessment Schema Version", record.assessment.schema_version, maskable=False
    )
    _emit_scalar(
        lines, "Assessment Ruleset Version", record.assessment.ruleset_version, maskable=False
    )
    _emit_scalar(lines, "Verdict", record.assessment.verdict, maskable=False)
    _emit_scalar(lines, "Verdict Rule ID", record.assessment.verdict_rule_id, maskable=False)
    _emit_scalar(
        lines, "Qualitative Evidence State", record.assessment.evidence_state, maskable=False
    )
    recommendation: object = record.assessment.recommended_class
    if recommendation is None:
        if record.assessment.verdict is d.ArchitectureVerdict.INSUFFICIENT_EVIDENCE:
            recommendation = "(abstention)"
        elif record.assessment.verdict is d.ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE:
            recommendation = "(no permissible candidate)"
        else:
            raise MarkdownReportError("A recommending verdict has no recommended class.")
    _emit_scalar(lines, "Recommendation", recommendation, maskable=False)
    _emit_value(
        lines,
        "Surviving Candidate IDs",
        record.assessment.surviving_candidate_ids,
        maskable=False,
    )
    _emit_value(lines, "Unmet Conditions", record.assessment.unmet_conditions)
    _emit_value(
        lines, "Active Hard Veto IDs", record.assessment.active_hard_veto_ids, maskable=False
    )
    _emit_value(
        lines,
        "Mandatory Human Control IDs",
        record.assessment.mandatory_human_control_ids,
        maskable=False,
    )

    lines.extend(("## Assessment Trace", ""))
    _emit_value(lines, "Prerequisite Evaluation", record.assessment.prerequisite_evaluation)
    _emit_value(
        lines,
        "Ordered Elimination Evaluation",
        record.assessment.ordered_elimination_evaluation,
    )

    _section(lines, "Evidence Identities", "Evidence Links", record.evidence_links)
    lines.extend(("## Recorded Context", ""))
    _emit_value(
        lines,
        "Recorded Context Evidence IDs",
        tuple(link.evidence_id for link in record.evidence_links if not link.decision_bearing),
    )
    _section(lines, "Artefact Identities", "Artefact Links", record.artefact_links)
    _section(lines, "Unresolved Gaps", "Unresolved Gaps", record.unresolved_gaps)
    _section(
        lines,
        "Reassessment Triggers",
        "Reassessment Triggers",
        record.reassessment_triggers,
    )

    lines.extend(("## Masking Notice", ""))
    _emit_scalar(lines, "Policy Version", mk.MASKING_POLICY_VERSION)
    _emit_scalar(lines, "Warning", mk.MASKING_WARNING)

    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
