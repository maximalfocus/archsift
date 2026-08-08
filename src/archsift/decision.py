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
    Candidate,
    CandidateConstraintTest,
    CandidateOutcomeTest,
    CandidateTestResult,
    ControlClass,
    Dossier,
    EstimateEvidence,
    Evidence,
    HardVetoStatus,
    ObservedEvidence,
)


class CriterionKind(StrEnum):
    """Binding criterion kinds evaluated without combining them into a score."""

    OUTCOME = "outcome"
    CONSTRAINT = "constraint"


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


@dataclass(frozen=True, slots=True)
class DecisionFinding:
    """One criterion-specific, evidence-traceable decision-rule occurrence."""

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

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "candidate_id": self.candidate_id,
            "consequence": self.consequence,
            "control_class": self.control_class.value,
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
    )


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


def _candidate_findings(
    dossier: Dossier,
    candidate: Candidate,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DecisionFinding, ...]:
    if dossier.problem_value is None:
        return ()

    outcome_tests = {test.outcome_id: test for test in candidate.outcome_tests}
    constraint_tests = {test.constraint_id: test for test in candidate.constraint_tests}
    findings: list[DecisionFinding] = []

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
    )

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
        if recommended_class in {
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
        active_hard_veto_ids=active_hard_veto_ids,
        mandatory_human_control_ids=mandatory_human_control_ids,
        prerequisite_evaluation=prerequisites,
        ordered_elimination_evaluation=elimination,
    )
