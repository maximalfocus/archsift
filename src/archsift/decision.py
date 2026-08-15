"""Deterministic candidate elimination and architecture verdict resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from archsift.rules import (
    RULESET_VERSION,
    AssessmentPrerequisiteEvaluation,
    RuleEffect,
    evaluate_assessment_prerequisites,
    get_rule_definition,
)
from archsift.validation import (
    AgencyAnswer,
    AgencyQuestion,
    Candidate,
    CandidateConstraintTest,
    CandidateOutcomeTest,
    CandidateTestResult,
    ControlClass,
    DecisionCondition,
    DecisionConditionStatus,
    Dossier,
    EstimateEvidence,
    Evidence,
    HardVetoStatus,
    ObservedEvidence,
)


class CriterionKind(StrEnum):
    """Candidate-specific decision fact kinds evaluated without a score."""

    OUTCOME = "outcome"
    CONSTRAINT = "constraint"
    AUTHORITY = "authority"
    HARD_VETO = "hard-veto"
    HUMAN_CONTROL = "human-control"
    AGENCY_QUESTION = "agency-question"
    RESIDUAL_CASE = "residual-case"
    DERIVED_AGENCY = "derived-agency"


class CandidateDisposition(StrEnum):
    """Evidence-calibrated eligibility of one candidate."""

    ELIMINATED = "eliminated"
    UNDETERMINED = "undetermined"
    SURVIVES = "survives"


class ControlClassDisposition(StrEnum):
    """Aggregated eligibility of one represented control class."""

    ELIMINATED = "eliminated"
    UNDETERMINED = "undetermined"
    SURVIVES = "survives"


class ArchitectureVerdict(StrEnum):
    """Mutually exclusive architecture outcomes defined by FR-010."""

    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"
    NO_PERMISSIBLE_CANDIDATE = "no-permissible-candidate"
    NO_TECHNOLOGY_CHANGE = "no-technology-change"


class EvidenceState(StrEnum):
    """Qualitative completeness of the evidence used to resolve a verdict."""

    COMPLETE = "evidence-complete"
    INCOMPLETE = "evidence-incomplete"


def _condition_dict(value: DecisionCondition) -> dict[str, object]:
    return {
        "decision_area": value.decision_area.value,
        "evidence_ids": list(value.evidence_ids),
        "id": value.id,
        "resolved_by": value.resolved_by,
        "statement": value.statement,
        "status": value.status.value,
        "target_control_class": value.target_control_class.value,
    }


@dataclass(frozen=True, slots=True)
class DecisionFinding:
    """One criterion-specific, evidence-traceable decision-rule occurrence."""

    rule_id: str
    requirement: str
    effect: RuleEffect
    candidate_id: str | None
    control_class: ControlClass | None
    criterion_id: str
    criterion_kind: CriterionKind
    evidence_ids: tuple[str, ...]
    message: str
    consequence: str
    action_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "action_ids": list(self.action_ids),
            "candidate_id": self.candidate_id,
            "consequence": self.consequence,
            "control_class": self.control_class.value if self.control_class is not None else None,
            "criterion_id": self.criterion_id,
            "criterion_kind": self.criterion_kind.value,
            "effect": self.effect.value,
            "evidence_ids": list(self.evidence_ids),
            "message": self.message,
            "requirement": self.requirement,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class CandidateElimination:
    """Ordered-elimination result for one represented candidate."""

    candidate_id: str
    control_class: ControlClass
    disposition: CandidateDisposition

    def to_dict(self) -> dict[str, str]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "candidate_id": self.candidate_id,
            "control_class": self.control_class.value,
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True, slots=True)
class ControlClassElimination:
    """Aggregated result for one control class that has authored candidates."""

    control_class: ControlClass
    candidate_ids: tuple[str, ...]
    disposition: ControlClassDisposition

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "candidate_ids": list(self.candidate_ids),
            "control_class": self.control_class.value,
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True, slots=True)
class OrderedEliminationEvaluation:
    """Non-verdict result of evaluating every represented candidate and class."""

    ruleset_version: str
    candidates: tuple[CandidateElimination, ...] = ()
    control_classes: tuple[ControlClassElimination, ...] = ()
    findings: tuple[DecisionFinding, ...] = ()
    least_surviving_class: ControlClass | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "control_classes": [control_class.to_dict() for control_class in self.control_classes],
            "findings": [finding.to_dict() for finding in self.findings],
            "least_surviving_class": (
                self.least_surviving_class.value if self.least_surviving_class is not None else None
            ),
            "ruleset_version": self.ruleset_version,
        }


@dataclass(frozen=True, slots=True)
class AssessmentEvaluation:
    """Evidence-calibrated verdict composed from existing deterministic evaluations."""

    schema_version: int
    ruleset_version: str
    verdict: ArchitectureVerdict
    verdict_rule_id: str
    evidence_state: EvidenceState
    recommended_class: ControlClass | None
    surviving_candidate_ids: tuple[str, ...]
    unmet_conditions: tuple[DecisionCondition, ...]
    active_hard_veto_ids: tuple[str, ...]
    mandatory_human_control_ids: tuple[str, ...]
    prerequisite_evaluation: AssessmentPrerequisiteEvaluation
    ordered_elimination_evaluation: OrderedEliminationEvaluation

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "active_hard_veto_ids": list(self.active_hard_veto_ids),
            "evidence_state": self.evidence_state.value,
            "mandatory_human_control_ids": list(self.mandatory_human_control_ids),
            "ordered_elimination_evaluation": self.ordered_elimination_evaluation.to_dict(),
            "prerequisite_evaluation": self.prerequisite_evaluation.to_dict(),
            "recommended_class": (
                self.recommended_class.value if self.recommended_class is not None else None
            ),
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "surviving_candidate_ids": list(self.surviving_candidate_ids),
            "unmet_conditions": [_condition_dict(item) for item in self.unmet_conditions],
            "verdict": self.verdict.value,
            "verdict_rule_id": self.verdict_rule_id,
        }


def _has_credible_evidence(
    evidence_by_id: dict[str, Evidence], evidence_ids: tuple[str, ...]
) -> bool:
    return any(
        (isinstance(entry, ObservedEvidence) and bool(entry.provenance.strip()))
        or (isinstance(entry, EstimateEvidence) and bool(entry.method.strip()))
        for identifier in evidence_ids
        if (entry := evidence_by_id.get(identifier)) is not None
    )


def _finding(
    rule_id: str,
    candidate: Candidate,
    criterion_id: str,
    criterion_kind: CriterionKind,
    evidence_ids: tuple[str, ...],
    message: str,
    action_ids: tuple[str, ...] = (),
) -> DecisionFinding:
    rule = get_rule_definition(rule_id)
    return DecisionFinding(
        rule_id=rule.id,
        requirement=rule.requirement,
        effect=rule.effect,
        candidate_id=candidate.id,
        control_class=candidate.control_class,
        criterion_id=criterion_id,
        criterion_kind=criterion_kind,
        evidence_ids=evidence_ids,
        message=message,
        consequence=rule.consequence,
        action_ids=action_ids,
    )


def _dossier_finding(
    rule_id: str,
    criterion_id: str,
    criterion_kind: CriterionKind,
    evidence_ids: tuple[str, ...],
    message: str,
    action_ids: tuple[str, ...] = (),
) -> DecisionFinding:
    """A dossier-level finding with no candidate anchor (candidate_id is None)."""
    rule = get_rule_definition(rule_id)
    return DecisionFinding(
        rule_id=rule.id,
        requirement=rule.requirement,
        effect=rule.effect,
        candidate_id=None,
        control_class=None,
        criterion_id=criterion_id,
        criterion_kind=criterion_kind,
        evidence_ids=evidence_ids,
        message=message,
        consequence=rule.consequence,
        action_ids=action_ids,
    )


def _dossier_non_decisive_findings(
    dossier: Dossier,
    evidence_by_id: dict[str, Evidence],
    candidates: tuple[Candidate, ...],
) -> tuple[DecisionFinding, ...]:
    """Explain non-decisive agency and boundary facts when no relevant candidate exists."""
    findings: list[DecisionFinding] = []
    agency = dossier.agency_necessity
    has_agentic = any(
        candidate.control_class is ControlClass.AGENTIC_CONTROL for candidate in candidates
    )
    if agency is not None and not has_agentic:
        for name in _AGENCY_QUESTION_FIELDS:
            question = getattr(agency, name)
            if not _has_credible_evidence(evidence_by_id, question.evidence_ids):
                continue
            findings.append(
                _dossier_finding(
                    "agentic-agency-fact-non-decisive",
                    name,
                    CriterionKind.AGENCY_QUESTION,
                    question.evidence_ids,
                    f"Agency question {name!r} is non-decisive: no agentic candidate is "
                    "represented.",
                )
            )
    autonomy = dossier.autonomy_permission
    has_automation = any(candidate.control_class in _AUTOMATION_CLASSES for candidate in candidates)
    if autonomy is not None and not has_automation:
        for veto in sorted(autonomy.hard_vetoes, key=lambda item: item.id):
            findings.append(
                _dossier_finding(
                    "autonomy-boundary-non-decisive",
                    veto.id,
                    CriterionKind.HARD_VETO,
                    tuple(sorted(veto.evidence_ids)),
                    f"Hard veto {veto.id!r} is non-decisive: no automation candidate is "
                    "represented.",
                )
            )
        for control in sorted(autonomy.mandatory_human_controls, key=lambda item: item.id):
            findings.append(
                _dossier_finding(
                    "autonomy-boundary-non-decisive",
                    control.id,
                    CriterionKind.HUMAN_CONTROL,
                    tuple(sorted(control.evidence_ids)),
                    f"Mandatory human control {control.id!r} is non-decisive: no automation "
                    "candidate is represented.",
                )
            )
    return tuple(findings)


def _missing_test_finding(
    candidate: Candidate,
    criterion_id: str,
    criterion_kind: CriterionKind,
) -> DecisionFinding:
    rule_id = (
        "candidate-outcome-test-missing"
        if criterion_kind is CriterionKind.OUTCOME
        else "candidate-constraint-test-missing"
    )
    return _finding(
        rule_id,
        candidate,
        criterion_id,
        criterion_kind,
        (),
        f"Candidate {candidate.id!r} has no test for binding "
        f"{criterion_kind.value} {criterion_id!r}.",
    )


def _test_finding(
    candidate: Candidate,
    criterion_id: str,
    criterion_kind: CriterionKind,
    test: CandidateOutcomeTest | CandidateConstraintTest,
    evidence_by_id: dict[str, Evidence],
) -> DecisionFinding:
    if test.result is CandidateTestResult.UNKNOWN:
        return _finding(
            "candidate-test-result-unknown",
            candidate,
            criterion_id,
            criterion_kind,
            test.evidence_ids,
            f"Candidate {candidate.id!r} has an unknown result for binding "
            f"{criterion_kind.value} {criterion_id!r}.",
        )

    if not _has_credible_evidence(evidence_by_id, test.evidence_ids):
        return _finding(
            "credible-candidate-test-evidence-missing",
            candidate,
            criterion_id,
            criterion_kind,
            test.evidence_ids,
            f"Candidate {candidate.id!r} has no observed or method-backed estimate evidence "
            f"for binding {criterion_kind.value} {criterion_id!r}.",
        )

    result = "failed" if test.result is CandidateTestResult.FAILS else "met"
    rule_id = f"binding-{criterion_kind.value}-{result}"
    return _finding(
        rule_id,
        candidate,
        criterion_id,
        criterion_kind,
        test.evidence_ids,
        f"Candidate {candidate.id!r} {result} binding {criterion_kind.value} "
        f"{criterion_id!r} with credible evidence.",
    )


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

_DYNAMIC_EXECUTION_FIELDS = {
    "execution_steps_predefinable",
    "step_count_or_order_predictable",
}
_RUNTIME_ADAPTATION_FIELDS = {
    "runtime_tool_choice_required",
    "runtime_replanning_required",
}
_MONITORABILITY_FIELDS = {
    "completion_independently_verifiable",
    "effects_independently_verifiable",
}


def _agency_question_findings(
    candidate: Candidate,
    name: str,
    question: AgencyQuestion,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DecisionFinding, ...]:
    gaps: list[DecisionFinding] = []
    if question.answer is AgencyAnswer.UNKNOWN:
        gaps.append(
            _finding(
                "agentic-agency-answer-unknown",
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"Agentic candidate {candidate.id!r} has an unknown answer for agency question "
                f"{name!r}.",
            )
        )
    if not _has_credible_evidence(evidence_by_id, question.evidence_ids):
        gaps.append(
            _finding(
                "agentic-credible-agency-evidence-missing",
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"Agentic candidate {candidate.id!r} has no observed or method-backed estimate "
                f"evidence for agency question {name!r}.",
            )
        )
    if gaps:
        return tuple(gaps)

    if name in _DYNAMIC_EXECUTION_FIELDS and question.answer is AgencyAnswer.NO:
        return (
            _finding(
                "agentic-dynamic-execution-supports-agency",
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"Agency question {name!r} credibly supports dynamic execution for agentic "
                f"candidate {candidate.id!r}.",
            ),
        )
    if name in _RUNTIME_ADAPTATION_FIELDS and question.answer is AgencyAnswer.YES:
        return (
            _finding(
                "agentic-runtime-adaptation-supports-agency",
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"Agency question {name!r} credibly supports runtime model-directed adaptation "
                f"for agentic candidate {candidate.id!r}.",
            ),
        )
    if name == "environmental_feedback_available":
        rule_id = (
            "agentic-feedback-supports-agency"
            if question.answer is AgencyAnswer.YES
            else "agentic-feedback-unavailable-blocks-candidate"
        )
        state = "available" if question.answer is AgencyAnswer.YES else "unavailable"
        return (
            _finding(
                rule_id,
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"Environmental feedback is credibly {state} for agentic candidate "
                f"{candidate.id!r}.",
            ),
        )
    if name == "fixed_workflow_sufficient":
        rule_id = (
            "agentic-fixed-workflow-insufficiency-supports-agency"
            if question.answer is AgencyAnswer.NO
            else "agentic-fixed-workflow-sufficient-blocks-candidate"
        )
        state = "insufficient" if question.answer is AgencyAnswer.NO else "sufficient"
        return (
            _finding(
                rule_id,
                candidate,
                name,
                CriterionKind.AGENCY_QUESTION,
                question.evidence_ids,
                f"A fixed workflow is credibly {state} for agentic candidate {candidate.id!r}.",
            ),
        )

    assert name in _DYNAMIC_EXECUTION_FIELDS | _RUNTIME_ADAPTATION_FIELDS | _MONITORABILITY_FIELDS
    return (
        _finding(
            "agentic-agency-fact-non-decisive",
            candidate,
            name,
            CriterionKind.AGENCY_QUESTION,
            question.evidence_ids,
            f"Agency question {name!r} is non-decisive for agentic candidate {candidate.id!r} "
            "under the runtime-agency survival contract.",
        ),
    )


def _agency_findings(
    dossier: Dossier,
    candidate: Candidate,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DecisionFinding, ...]:
    if candidate.control_class is not ControlClass.AGENTIC_CONTROL:
        return ()

    agency = dossier.agency_necessity
    if agency is None:
        return (
            _finding(
                "agentic-agency-necessity-missing",
                candidate,
                "agency_necessity",
                CriterionKind.DERIVED_AGENCY,
                (),
                f"Agentic candidate {candidate.id!r} has no agency-necessity fact section.",
            ),
        )

    questions = {name: getattr(agency, name) for name in _AGENCY_QUESTION_FIELDS}
    findings = [
        finding
        for name in _AGENCY_QUESTION_FIELDS
        for finding in _agency_question_findings(
            candidate,
            name,
            questions[name],
            evidence_by_id,
        )
    ]

    runtime_questions = tuple(questions[name] for name in sorted(_RUNTIME_ADAPTATION_FIELDS))
    if all(
        question.answer is AgencyAnswer.NO
        and _has_credible_evidence(evidence_by_id, question.evidence_ids)
        for question in runtime_questions
    ):
        evidence_ids = tuple(
            sorted(
                {
                    identifier
                    for question in runtime_questions
                    for identifier in question.evidence_ids
                }
            )
        )
        findings.append(
            _finding(
                "agentic-runtime-adaptation-missing",
                candidate,
                "runtime_replanning_required+runtime_tool_choice_required",
                CriterionKind.DERIVED_AGENCY,
                evidence_ids,
                f"Agentic candidate {candidate.id!r} credibly requires neither runtime tool "
                "choice nor runtime replanning.",
            )
        )

    fixed_question = questions["fixed_workflow_sufficient"]
    fixed_workflow_insufficient = (
        fixed_question.answer is AgencyAnswer.NO
        and _has_credible_evidence(evidence_by_id, fixed_question.evidence_ids)
    )
    if fixed_workflow_insufficient and not agency.residual_cases:
        findings.append(
            _finding(
                "agentic-residual-case-missing",
                candidate,
                "residual_cases",
                CriterionKind.RESIDUAL_CASE,
                fixed_question.evidence_ids,
                f"Agentic candidate {candidate.id!r} asserts fixed-workflow insufficiency "
                "without a residual case.",
            )
        )

    for residual in sorted(agency.residual_cases, key=lambda item: item.id):
        if not _has_credible_evidence(evidence_by_id, residual.evidence_ids):
            findings.append(
                _finding(
                    "agentic-credible-residual-evidence-missing",
                    candidate,
                    residual.id,
                    CriterionKind.RESIDUAL_CASE,
                    residual.evidence_ids,
                    f"Residual case {residual.id!r} lacks observed or method-backed estimate "
                    f"support for agentic candidate {candidate.id!r}.",
                )
            )
        elif fixed_workflow_insufficient:
            findings.append(
                _finding(
                    "agentic-residual-case-supports-agency",
                    candidate,
                    residual.id,
                    CriterionKind.RESIDUAL_CASE,
                    residual.evidence_ids,
                    f"Residual case {residual.id!r} credibly supports fixed-workflow "
                    f"insufficiency for agentic candidate {candidate.id!r}.",
                )
            )
        else:
            findings.append(
                _finding(
                    "agentic-agency-fact-non-decisive",
                    candidate,
                    residual.id,
                    CriterionKind.RESIDUAL_CASE,
                    residual.evidence_ids,
                    f"Residual case {residual.id!r} is non-decisive because credible "
                    "fixed-workflow insufficiency is not established.",
                )
            )
    return tuple(findings)


_AUTOMATION_CLASSES = {
    ControlClass.DETERMINISTIC_AUTOMATION,
    ControlClass.FIXED_AI_WORKFLOW,
    ControlClass.AGENTIC_CONTROL,
}


def _autonomy_findings(
    dossier: Dossier,
    candidate: Candidate,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DecisionFinding, ...]:
    if candidate.control_class not in _AUTOMATION_CLASSES:
        return ()

    authority = candidate.authority
    if authority is None:
        return (
            _finding(
                "automation-authority-missing",
                candidate,
                "candidate-authority",
                CriterionKind.AUTHORITY,
                (),
                f"Automation candidate {candidate.id!r} has no task-action authority scope.",
            ),
        )
    if not _has_credible_evidence(evidence_by_id, authority.evidence_ids):
        return (
            _finding(
                "credible-authority-evidence-missing",
                candidate,
                "candidate-authority",
                CriterionKind.AUTHORITY,
                authority.evidence_ids,
                f"Automation candidate {candidate.id!r} has no observed or method-backed "
                "authority evidence.",
                tuple(sorted(authority.action_ids)),
            ),
        )

    autonomy = dossier.autonomy_permission
    if autonomy is None:
        return ()

    candidate_actions = set(authority.action_ids)
    retained_controls = set(authority.retained_human_control_ids)
    findings: list[DecisionFinding] = []
    for veto in sorted(autonomy.hard_vetoes, key=lambda item: item.id):
        intersecting_actions = tuple(sorted(candidate_actions.intersection(veto.action_ids)))
        evidence_ids = tuple(sorted({*authority.evidence_ids, *veto.evidence_ids}))
        if not intersecting_actions:
            findings.append(
                _finding(
                    "autonomy-boundary-non-decisive",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Hard veto {veto.id!r} does not overlap candidate {candidate.id!r}.",
                    (),
                )
            )
        elif veto.status is HardVetoStatus.UNKNOWN:
            # Unknown applicability of an overlapping boundary is an unresolved
            # evidence state, not a non-decisive boundary: the candidate must
            # not survive with a possibly applicable veto left unaccounted for.
            findings.append(
                _finding(
                    "overlapping-veto-status-unknown",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Hard veto {veto.id!r} has unknown applicability for candidate "
                    f"{candidate.id!r}.",
                    intersecting_actions,
                )
            )
        elif veto.status is not HardVetoStatus.ACTIVE:
            findings.append(
                _finding(
                    "autonomy-boundary-non-decisive",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Hard veto {veto.id!r} is inactive for candidate {candidate.id!r}.",
                    intersecting_actions,
                )
            )
        elif veto.prohibited_control_classes is None:
            findings.append(
                _finding(
                    "active-veto-applicability-missing",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Active hard veto {veto.id!r} overlaps candidate {candidate.id!r} but "
                    "does not declare prohibited control classes.",
                    intersecting_actions,
                )
            )
        elif candidate.control_class in veto.prohibited_control_classes:
            findings.append(
                _finding(
                    "active-veto-blocks-candidate",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Active hard veto {veto.id!r} prohibits candidate {candidate.id!r} on "
                    "the intersecting task actions.",
                    intersecting_actions,
                )
            )
        else:
            findings.append(
                _finding(
                    "autonomy-boundary-non-decisive",
                    candidate,
                    veto.id,
                    CriterionKind.HARD_VETO,
                    evidence_ids,
                    f"Active hard veto {veto.id!r} does not prohibit candidate "
                    f"{candidate.id!r}'s control class.",
                    intersecting_actions,
                )
            )

    for control in sorted(autonomy.mandatory_human_controls, key=lambda item: item.id):
        intersecting_actions = tuple(sorted(candidate_actions.intersection(control.action_ids)))
        evidence_ids = tuple(sorted({*authority.evidence_ids, *control.evidence_ids}))
        if not intersecting_actions:
            findings.append(
                _finding(
                    "autonomy-boundary-non-decisive",
                    candidate,
                    control.id,
                    CriterionKind.HUMAN_CONTROL,
                    evidence_ids,
                    f"Mandatory human control {control.id!r} does not overlap candidate "
                    f"{candidate.id!r}.",
                    (),
                )
            )
        elif control.id in retained_controls:
            findings.append(
                _finding(
                    "mandatory-human-control-retained",
                    candidate,
                    control.id,
                    CriterionKind.HUMAN_CONTROL,
                    evidence_ids,
                    f"Candidate {candidate.id!r} retains mandatory human control {control.id!r}.",
                    intersecting_actions,
                )
            )
        else:
            findings.append(
                _finding(
                    "mandatory-human-control-omitted",
                    candidate,
                    control.id,
                    CriterionKind.HUMAN_CONTROL,
                    evidence_ids,
                    f"Candidate {candidate.id!r} omits mandatory human control {control.id!r}.",
                    intersecting_actions,
                )
            )
    return tuple(findings)


def _candidate_findings(
    dossier: Dossier,
    candidate: Candidate,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DecisionFinding, ...]:
    findings: list[DecisionFinding] = []
    if dossier.problem_value is None:
        return (
            *_agency_findings(dossier, candidate, evidence_by_id),
            *_autonomy_findings(dossier, candidate, evidence_by_id),
        )

    outcome_tests = {test.outcome_id: test for test in candidate.outcome_tests}
    constraint_tests = {test.constraint_id: test for test in candidate.constraint_tests}

    for outcome in sorted(
        (outcome for outcome in dossier.problem_value.outcomes if outcome.binding),
        key=lambda outcome: outcome.id,
    ):
        outcome_test = outcome_tests.get(outcome.id)
        findings.append(
            _missing_test_finding(candidate, outcome.id, CriterionKind.OUTCOME)
            if outcome_test is None
            else _test_finding(
                candidate,
                outcome.id,
                CriterionKind.OUTCOME,
                outcome_test,
                evidence_by_id,
            )
        )

    for constraint in sorted(
        (constraint for constraint in dossier.problem_value.constraints if constraint.binding),
        key=lambda constraint: constraint.id,
    ):
        constraint_test = constraint_tests.get(constraint.id)
        findings.append(
            _missing_test_finding(candidate, constraint.id, CriterionKind.CONSTRAINT)
            if constraint_test is None
            else _test_finding(
                candidate,
                constraint.id,
                CriterionKind.CONSTRAINT,
                constraint_test,
                evidence_by_id,
            )
        )

    findings.extend(_agency_findings(dossier, candidate, evidence_by_id))
    findings.extend(_autonomy_findings(dossier, candidate, evidence_by_id))
    return tuple(findings)


def _candidate_disposition(findings: tuple[DecisionFinding, ...]) -> CandidateDisposition:
    if any(finding.effect is RuleEffect.BLOCK for finding in findings):
        return CandidateDisposition.ELIMINATED
    if any(finding.effect is RuleEffect.REQUIRE_EVIDENCE for finding in findings):
        return CandidateDisposition.UNDETERMINED
    return CandidateDisposition.SURVIVES


def evaluate_ordered_elimination(dossier: Dossier) -> OrderedEliminationEvaluation:
    """Evaluate represented candidates without issuing an architecture verdict."""
    comparison = dossier.candidate_comparison
    if comparison is None or dossier.problem_value is None:
        return OrderedEliminationEvaluation(ruleset_version=RULESET_VERSION)

    class_order = {control_class: index for index, control_class in enumerate(ControlClass)}
    ordered_candidates = tuple(
        sorted(
            comparison.candidates,
            key=lambda candidate: (class_order[candidate.control_class], candidate.id),
        )
    )
    evidence_by_id = {entry.id: entry for entry in dossier.evidence}
    findings_by_candidate = {
        candidate.id: _candidate_findings(dossier, candidate, evidence_by_id)
        for candidate in ordered_candidates
    }
    candidate_results = tuple(
        CandidateElimination(
            candidate_id=candidate.id,
            control_class=candidate.control_class,
            disposition=_candidate_disposition(findings_by_candidate[candidate.id]),
        )
        for candidate in ordered_candidates
    )
    findings = tuple(
        finding
        for candidate in ordered_candidates
        for finding in findings_by_candidate[candidate.id]
    ) + _dossier_non_decisive_findings(dossier, evidence_by_id, ordered_candidates)

    class_results: list[ControlClassElimination] = []
    for control_class in ControlClass:
        members = tuple(
            candidate for candidate in candidate_results if candidate.control_class is control_class
        )
        if not members:
            continue
        if any(member.disposition is CandidateDisposition.SURVIVES for member in members):
            disposition = ControlClassDisposition.SURVIVES
        elif any(member.disposition is CandidateDisposition.UNDETERMINED for member in members):
            disposition = ControlClassDisposition.UNDETERMINED
        else:
            disposition = ControlClassDisposition.ELIMINATED
        class_results.append(
            ControlClassElimination(
                control_class=control_class,
                candidate_ids=tuple(member.candidate_id for member in members),
                disposition=disposition,
            )
        )

    least_surviving_class: ControlClass | None = None
    for class_result in class_results:
        if class_result.disposition is ControlClassDisposition.UNDETERMINED:
            break
        if class_result.disposition is ControlClassDisposition.SURVIVES:
            least_surviving_class = class_result.control_class
            break

    return OrderedEliminationEvaluation(
        ruleset_version=RULESET_VERSION,
        candidates=candidate_results,
        control_classes=tuple(class_results),
        findings=findings,
        least_surviving_class=least_surviving_class,
    )


def evaluate_assessment(dossier: Dossier) -> AssessmentEvaluation:
    """Resolve an FR-010 verdict without performing I/O or fabricating conditions."""
    prerequisites = evaluate_assessment_prerequisites(dossier)
    elimination = evaluate_ordered_elimination(dossier)
    recommended_class: ControlClass | None = None
    surviving_candidate_ids: tuple[str, ...] = ()
    unmet_conditions: tuple[DecisionCondition, ...] = ()

    if not prerequisites.ready:
        verdict = ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    elif elimination.least_surviving_class is not None:
        recommended_class = elimination.least_surviving_class
        surviving_candidate_ids = tuple(
            candidate.candidate_id
            for candidate in elimination.candidates
            if candidate.control_class is recommended_class
            and candidate.disposition is CandidateDisposition.SURVIVES
        )
        unmet_conditions = tuple(
            sorted(
                (
                    condition
                    for condition in dossier.decision_conditions
                    if condition.target_control_class is recommended_class
                    and condition.status is DecisionConditionStatus.UNMET
                ),
                key=lambda condition: condition.id,
            )
        )
        if unmet_conditions:
            verdict = ArchitectureVerdict.CONDITIONAL
        elif recommended_class in {
            ControlClass.HUMAN_OWNED_WORK,
            ControlClass.PROCESS_REDESIGN,
        }:
            verdict = ArchitectureVerdict.NO_TECHNOLOGY_CHANGE
        else:
            verdict = ArchitectureVerdict.SUPPORTED
    elif any(
        result.disposition is ControlClassDisposition.UNDETERMINED
        for result in elimination.control_classes
    ):
        verdict = ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    elif elimination.control_classes and all(
        result.disposition is ControlClassDisposition.ELIMINATED
        for result in elimination.control_classes
    ):
        verdict = ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE
    else:
        # Fail closed if a future elimination state does not establish a
        # minimum-sufficient class or complete evidenced elimination.
        verdict = ArchitectureVerdict.INSUFFICIENT_EVIDENCE

    evidence_state = (
        EvidenceState.INCOMPLETE
        if verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
        else EvidenceState.COMPLETE
    )
    verdict_rule_id = f"verdict-{verdict.value}"
    get_rule_definition(verdict_rule_id)

    autonomy = dossier.autonomy_permission
    active_hard_veto_ids = (
        tuple(
            sorted(veto.id for veto in autonomy.hard_vetoes if veto.status is HardVetoStatus.ACTIVE)
        )
        if autonomy is not None
        else ()
    )
    mandatory_human_control_ids = (
        tuple(sorted(control.id for control in autonomy.mandatory_human_controls))
        if autonomy is not None
        else ()
    )

    return AssessmentEvaluation(
        schema_version=dossier.schema_version,
        ruleset_version=RULESET_VERSION,
        verdict=verdict,
        verdict_rule_id=verdict_rule_id,
        evidence_state=evidence_state,
        recommended_class=recommended_class,
        surviving_candidate_ids=surviving_candidate_ids,
        unmet_conditions=unmet_conditions,
        active_hard_veto_ids=active_hard_veto_ids,
        mandatory_human_control_ids=mandatory_human_control_ids,
        prerequisite_evaluation=prerequisites,
        ordered_elimination_evaluation=elimination,
    )
