from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from archsift.decision import (
    ArchitectureVerdict,
    EvidenceState,
    evaluate_assessment,
)
from archsift.rules import RULESET_VERSION, RuleEffect, list_rules
from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    AutonomyAnswer,
    AutonomyPermission,
    AutonomyQuestion,
    Candidate,
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
    EvidencedStatement,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    TaskAction,
    TaskBoundary,
)


def _observed(
    identifier: str,
    area: DecisionArea,
) -> ObservedEvidence:
    return ObservedEvidence(
        identifier,
        "A synthetic decision observation.",
        "Architecture reviewer",
        (area,),
        provenance="evidence/synthetic-observation.txt",
        observed_at=date(2026, 8, 8),
    )


def _problem() -> ProblemValue:
    return ProblemValue(
        outcomes=(
            ProblemOutcome(
                "required-quality",
                "Meet required quality.",
                "Accepted cases",
                "At least 95 percent",
                "current-quality",
                True,
                ("decision-observed",),
            ),
        ),
        baselines=(
            ProblemBaseline(
                "current-quality",
                "Current result.",
                "Accepted cases",
                "90 percent",
                ("decision-observed",),
            ),
        ),
        constraints=(
            ProblemConstraint(
                "approval-required",
                "Human approval is required.",
                "Check approval before release.",
                "Approval exists",
                True,
                ("decision-observed",),
            ),
        ),
        affected_volume=EvidencedStatement("Material volume.", ("decision-observed",)),
        material_pain=EvidencedStatement("Material delay.", ("decision-observed",)),
        error_cost=EvidencedStatement("Material rework.", ("decision-observed",)),
        technology_limitation=EvidencedStatement(
            "Current tooling limits retrieval.",
            ("decision-observed",),
        ),
    )


def _task() -> TaskBoundary:
    return TaskBoundary(
        operation="Review one bounded synthetic case.",
        starts_when="A complete case arrives.",
        completes_when="An approved disposition is recorded.",
        accountable_owner="Operations owner",
        actors=("Reviewer", "Approver"),
        systems_and_tools=("Case register",),
        information_read=("Synthetic case data",),
        actions=(
            TaskAction(
                "release-disposition",
                "Release the approved disposition.",
                True,
                "An approver must approve before release.",
            ),
        ),
        exclusions=("Changing policy",),
    )


def _agency() -> AgencyNecessity:
    def question(answer: AgencyAnswer) -> AgencyQuestion:
        return AgencyQuestion(answer, "Evidence-backed agency fact.", ("agency-observed",))

    return AgencyNecessity(
        execution_steps_predefinable=question(AgencyAnswer.YES),
        step_count_or_order_predictable=question(AgencyAnswer.YES),
        runtime_tool_choice_required=question(AgencyAnswer.NO),
        runtime_replanning_required=question(AgencyAnswer.NO),
        environmental_feedback_available=question(AgencyAnswer.YES),
        completion_independently_verifiable=question(AgencyAnswer.YES),
        effects_independently_verifiable=question(AgencyAnswer.YES),
        fixed_workflow_sufficient=question(AgencyAnswer.YES),
        residual_cases=(),
    )


def _autonomy() -> AutonomyPermission:
    def question(answer: AutonomyAnswer) -> AutonomyQuestion:
        return AutonomyQuestion(answer, "Evidence-backed autonomy fact.", ("autonomy-observed",))

    return AutonomyPermission(
        actions_reversible=question(AutonomyAnswer.NO),
        failure_blast_radius_bounded=question(AutonomyAnswer.YES),
        regulatory_automation_permitted=question(AutonomyAnswer.NO),
        data_confidence_sufficient=question(AutonomyAnswer.YES),
        accountable_owner_assigned=question(AutonomyAnswer.YES),
        decision_path_auditable=question(AutonomyAnswer.YES),
        timely_human_intervention_available=question(AutonomyAnswer.YES),
        safe_degradation_available=question(AutonomyAnswer.YES),
        hard_vetoes=(
            HardVeto(
                "z-active-veto",
                HardVetoStatus.ACTIVE,
                "Release would occur without approval.",
                "Autonomous release is prohibited.",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
            HardVeto(
                "ignored-inactive-veto",
                HardVetoStatus.INACTIVE,
                "An inactive synthetic condition.",
                "No current restriction.",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
            HardVeto(
                "a-active-veto",
                HardVetoStatus.ACTIVE,
                "Approval evidence is absent.",
                "Release is prohibited until approval exists.",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
        ),
        mandatory_human_controls=(
            MandatoryHumanControl(
                "z-review-control",
                "Review before release.",
                "Immediately before release.",
                "Reviewer",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
            MandatoryHumanControl(
                "a-approval-control",
                "Approve before release.",
                "After review and before release.",
                "Approver",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
        ),
    )


def _candidate(
    identifier: str,
    control_class: ControlClass,
    outcome_result: CandidateTestResult,
    *,
    outcome_evidence_id: str = "decision-observed",
    constraint_evidence_id: str = "decision-observed",
) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Candidate {identifier}",
        description="An independently authored synthetic architecture candidate.",
        control_class=control_class,
        roles=(),
        material_deviations=(),
        outcome_tests=(
            CandidateOutcomeTest(
                "required-quality",
                outcome_result,
                "Synthetic outcome result.",
                (outcome_evidence_id,),
            ),
        ),
        constraint_tests=(
            CandidateConstraintTest(
                "approval-required",
                CandidateTestResult.MEETS,
                "Synthetic approval-boundary result.",
                (constraint_evidence_id,),
            ),
        ),
    )


def _dimensions(evidence_id: str = "decision-observed") -> ComparisonDimensions:
    dimension = ComparisonDimension(
        ComparisonResult.EQUIVALENT,
        "Synthetic directional comparison.",
        (evidence_id,),
    )
    return ComparisonDimensions(
        outcome_quality=dimension,
        difficult_case_performance=dimension,
        cost=dimension,
        latency=dimension,
        human_effort=dimension,
        integration_burden=dimension,
        security_exposure=dimension,
        failure_impact=dimension,
        operability=dimension,
        evaluation_burden=dimension,
        maintainability=dimension,
    )


def _ready_dossier(
    *candidates: Candidate,
    current_id: str,
    proposed_id: str,
    strongest_id: str | None,
    extra_evidence: tuple[Evidence, ...] = (),
) -> Dossier:
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    proposed = candidates_by_id[proposed_id]
    roles_by_id: dict[str, list[CandidateRole]] = {candidate.id: [] for candidate in candidates}
    roles_by_id[current_id].append(CandidateRole.CURRENT_BASELINE)
    roles_by_id[proposed_id].append(CandidateRole.PROPOSED)
    if proposed.control_class is not ControlClass.HUMAN_OWNED_WORK:
        assert strongest_id is not None
        roles_by_id[strongest_id].append(CandidateRole.STRONGEST_SIMPLER)
    agentic_candidates = [
        candidate
        for candidate in candidates
        if candidate.control_class is ControlClass.AGENTIC_CONTROL
    ]
    if agentic_candidates:
        roles_by_id[agentic_candidates[0].id].append(CandidateRole.AGENTIC_COMPARATOR)

    typed_candidates = tuple(
        replace(candidate, roles=tuple(roles_by_id[candidate.id])) for candidate in candidates
    )
    required_pairs = {
        (candidate.id, current_id) for candidate in candidates if candidate.id != current_id
    }
    if strongest_id is not None and proposed_id != strongest_id:
        required_pairs.add((proposed_id, strongest_id))
    comparisons = tuple(
        CandidatePairComparison(subject, comparator, _dimensions())
        for subject, comparator in sorted(required_pairs)
    )
    return Dossier(
        schema_version=1,
        case=CaseIdentity("assessment", "Assessment verdict"),
        evidence=(
            _observed("decision-observed", DecisionArea.COMPARATIVE_FIT),
            _observed("agency-observed", DecisionArea.AGENCY_NECESSITY),
            _observed("autonomy-observed", DecisionArea.AUTONOMY_PERMISSION),
            *extra_evidence,
        ),
        task=_task(),
        problem_value=_problem(),
        agency_necessity=_agency(),
        autonomy_permission=_autonomy(),
        candidate_comparison=CandidateComparison(typed_candidates, comparisons),
    )


def test_verdict_values_and_rules_are_complete_versioned_and_non_scoring() -> None:
    assert {verdict.value for verdict in ArchitectureVerdict} == {
        "supported",
        "conditional",
        "insufficient-evidence",
        "no-permissible-candidate",
        "no-technology-change",
    }
    assert RULESET_VERSION == "1.4.0"
    rules = [rule for rule in list_rules() if rule.requirement == "FR-010"]
    assert [(rule.id, rule.effect) for rule in rules] == [
        ("verdict-conditional", RuleEffect.SUPPORT_CANDIDATE),
        ("verdict-insufficient-evidence", RuleEffect.REQUIRE_EVIDENCE),
        ("verdict-no-permissible-candidate", RuleEffect.BLOCK),
        ("verdict-no-technology-change", RuleEffect.SUPPORT_CANDIDATE),
        ("verdict-supported", RuleEffect.SUPPORT_CANDIDATE),
    ]


def test_incomplete_prerequisites_abstain_with_exact_nested_findings() -> None:
    evaluation = evaluate_assessment(
        Dossier(schema_version=1, case=CaseIdentity("incomplete", "Incomplete"))
    )

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.verdict_rule_id == "verdict-insufficient-evidence"
    assert evaluation.evidence_state is EvidenceState.INCOMPLETE
    assert evaluation.recommended_class is None
    assert evaluation.surviving_candidate_ids == ()
    assert [finding.rule_id for finding in evaluation.prerequisite_evaluation.findings] == [
        "task-boundary-missing",
        "problem-value-missing",
        "agency-necessity-missing",
        "autonomy-permission-missing",
        "candidate-comparison-missing",
    ]
    assert evaluation.ordered_elimination_evaluation.control_classes == ()
    payload = evaluation.to_dict()
    assert set(payload) == {
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
    }
    assert payload["recommended_class"] is None
    assert payload["prerequisite_evaluation"]["ready"] is False  # type: ignore[index]


def test_assumption_only_simpler_failure_cannot_promote_complexity() -> None:
    assumption = AssumptionEvidence(
        "assumption",
        "The simpler candidate may miss the required outcome.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        falsified_by="A representative trial meets the required outcome.",
    )
    dossier = _ready_dossier(
        _candidate(
            "human",
            ControlClass.HUMAN_OWNED_WORK,
            CandidateTestResult.FAILS,
            outcome_evidence_id="assumption",
        ),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
        extra_evidence=(assumption,),
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.recommended_class is None
    prerequisite_gap = next(
        finding
        for finding in evaluation.prerequisite_evaluation.findings
        if finding.rule_id == "credible-candidate-test-evidence-missing"
    )
    decision_gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "credible-candidate-test-evidence-missing"
    )
    assert prerequisite_gap.evidence_ids == decision_gap.evidence_ids == ("assumption",)


def test_complete_elimination_is_no_permissible_candidate() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.FAILS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.prerequisite_evaluation.ready is True
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE
    assert evaluation.verdict_rule_id == "verdict-no-permissible-candidate"
    assert evaluation.evidence_state is EvidenceState.COMPLETE
    assert evaluation.recommended_class is None
    assert evaluation.surviving_candidate_ids == ()
    blocking = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.effect is RuleEffect.BLOCK
    ]
    assert [(finding.candidate_id, finding.criterion_id) for finding in blocking] == [
        ("human", "required-quality"),
        ("fixed", "required-quality"),
    ]
    assert all(finding.evidence_ids == ("decision-observed",) for finding in blocking)


@pytest.mark.parametrize(
    ("selected_class", "expected_verdict"),
    [
        (ControlClass.HUMAN_OWNED_WORK, ArchitectureVerdict.NO_TECHNOLOGY_CHANGE),
        (ControlClass.PROCESS_REDESIGN, ArchitectureVerdict.NO_TECHNOLOGY_CHANGE),
        (ControlClass.DETERMINISTIC_AUTOMATION, ArchitectureVerdict.SUPPORTED),
        (ControlClass.FIXED_AI_WORKFLOW, ArchitectureVerdict.SUPPORTED),
        (ControlClass.AGENTIC_CONTROL, ArchitectureVerdict.SUPPORTED),
    ],
)
def test_minimum_surviving_class_resolves_positive_verdict(
    selected_class: ControlClass,
    expected_verdict: ArchitectureVerdict,
) -> None:
    if selected_class is ControlClass.HUMAN_OWNED_WORK:
        candidates = (
            _candidate("human", selected_class, CandidateTestResult.MEETS),
            _candidate("process", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
        )
        proposed_id = "human"
        strongest_id = None
    else:
        candidates = (
            _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
            _candidate("selected", selected_class, CandidateTestResult.MEETS),
        )
        proposed_id = "selected"
        strongest_id = "human"

    evaluation = evaluate_assessment(
        _ready_dossier(
            *candidates,
            current_id="human",
            proposed_id=proposed_id,
            strongest_id=strongest_id,
        )
    )

    assert evaluation.verdict is expected_verdict
    assert evaluation.recommended_class is selected_class
    assert evaluation.surviving_candidate_ids == (
        "human" if selected_class is ControlClass.HUMAN_OWNED_WORK else "selected",
    )
    assert evaluation.evidence_state is EvidenceState.COMPLETE
    assert evaluation.verdict_rule_id == f"verdict-{expected_verdict.value}"


def test_multiple_survivors_are_exposed_without_candidate_ranking() -> None:
    dossier = _ready_dossier(
        _candidate("z-option", ControlClass.DETERMINISTIC_AUTOMATION, CandidateTestResult.MEETS),
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("a-option", ControlClass.DETERMINISTIC_AUTOMATION, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="z-option",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.recommended_class is ControlClass.DETERMINISTIC_AUTOMATION
    assert evaluation.surviving_candidate_ids == ("a-option", "z-option")


def _condition(
    identifier: str,
    target: ControlClass,
    status: DecisionConditionStatus = DecisionConditionStatus.UNMET,
) -> DecisionCondition:
    return DecisionCondition(
        id=identifier,
        target_control_class=target,
        decision_area=DecisionArea.COMPARATIVE_FIT,
        statement=f"Satisfy synthetic condition {identifier}.\x1b",
        status=status,
        resolved_by=f"Observe synthetic resolution {identifier}.",
        evidence_ids=("decision-observed",),
    )


@pytest.mark.parametrize(
    "selected_class",
    [ControlClass.HUMAN_OWNED_WORK, ControlClass.FIXED_AI_WORKFLOW],
)
def test_matching_unmet_conditions_resolve_conditional_after_class_selection(
    selected_class: ControlClass,
) -> None:
    if selected_class is ControlClass.HUMAN_OWNED_WORK:
        dossier = _ready_dossier(
            _candidate("human", selected_class, CandidateTestResult.MEETS),
            _candidate("process", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
            current_id="human",
            proposed_id="human",
            strongest_id=None,
        )
    else:
        dossier = _ready_dossier(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
            _candidate("fixed", selected_class, CandidateTestResult.MEETS),
            current_id="human",
            proposed_id="fixed",
            strongest_id="human",
        )
    dossier = replace(
        dossier,
        decision_conditions=(
            _condition("z-condition", selected_class),
            _condition("met-condition", selected_class, DecisionConditionStatus.MET),
            _condition("a-condition", selected_class),
            _condition("other-class", ControlClass.AGENTIC_CONTROL),
        ),
    )

    without_conditions = evaluate_assessment(replace(dossier, decision_conditions=()))
    evaluation = evaluate_assessment(dossier)

    assert evaluation.prerequisite_evaluation == without_conditions.prerequisite_evaluation
    assert (
        evaluation.ordered_elimination_evaluation
        == without_conditions.ordered_elimination_evaluation
    )
    assert evaluation.recommended_class == without_conditions.recommended_class
    assert evaluation.surviving_candidate_ids == without_conditions.surviving_candidate_ids
    assert evaluation.verdict is ArchitectureVerdict.CONDITIONAL
    assert evaluation.verdict_rule_id == "verdict-conditional"
    assert evaluation.recommended_class is selected_class
    assert evaluation.evidence_state is EvidenceState.COMPLETE
    assert [condition.id for condition in evaluation.unmet_conditions] == [
        "a-condition",
        "z-condition",
    ]
    payload = evaluation.to_dict()
    assert [condition["id"] for condition in payload["unmet_conditions"]] == [  # type: ignore[index]
        "a-condition",
        "z-condition",
    ]
    assert payload["unmet_conditions"][0]["statement"].endswith(".\x1b")  # type: ignore[index]


def test_met_and_non_selected_conditions_do_not_change_positive_verdict() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    dossier = replace(
        dossier,
        decision_conditions=(
            _condition(
                "met-fixed",
                ControlClass.FIXED_AI_WORKFLOW,
                DecisionConditionStatus.MET,
            ),
            _condition("unmet-agentic", ControlClass.AGENTIC_CONTROL),
        ),
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.recommended_class is ControlClass.FIXED_AI_WORKFLOW
    assert evaluation.unmet_conditions == ()


def test_conditions_do_not_override_incomplete_evidence_or_complete_elimination() -> None:
    incomplete = replace(
        Dossier(schema_version=1, case=CaseIdentity("incomplete", "Incomplete")),
        decision_conditions=(_condition("incomplete-condition", ControlClass.FIXED_AI_WORKFLOW),),
    )
    eliminated = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.FAILS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    eliminated = replace(
        eliminated,
        decision_conditions=(_condition("blocked-condition", ControlClass.FIXED_AI_WORKFLOW),),
    )

    incomplete_result = evaluate_assessment(incomplete)
    eliminated_result = evaluate_assessment(eliminated)

    assert incomplete_result.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert incomplete_result.unmet_conditions == ()
    assert eliminated_result.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE
    assert eliminated_result.unmet_conditions == ()


def test_vetoes_controls_and_estimates_do_not_invent_conditional_verdict() -> None:
    estimate = EstimateEvidence(
        "estimate",
        "A method-backed synthetic candidate forecast.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        method="Representative synthetic trial with documented sampling.",
    )
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate(
            "fixed",
            ControlClass.FIXED_AI_WORKFLOW,
            CandidateTestResult.MEETS,
            outcome_evidence_id="estimate",
            constraint_evidence_id="estimate",
        ),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
        extra_evidence=(estimate,),
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.verdict is not ArchitectureVerdict.CONDITIONAL
    assert evaluation.active_hard_veto_ids == ("a-active-veto", "z-active-veto")
    assert evaluation.mandatory_human_control_ids == (
        "a-approval-control",
        "z-review-control",
    )


def test_unmet_prerequisite_precedes_complete_candidate_elimination() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.FAILS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(replace(dossier, agency_necessity=None))

    assert all(
        result.disposition.value == "eliminated"
        for result in evaluation.ordered_elimination_evaluation.control_classes
    )
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.verdict_rule_id == "verdict-insufficient-evidence"


def test_assessment_is_immutable_and_independent_of_authored_candidate_order() -> None:
    human = _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS)
    fixed = _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS)
    first = evaluate_assessment(
        _ready_dossier(
            fixed,
            human,
            current_id="human",
            proposed_id="fixed",
            strongest_id="human",
        )
    )
    second = evaluate_assessment(
        _ready_dossier(
            human,
            fixed,
            current_id="human",
            proposed_id="fixed",
            strongest_id="human",
        )
    )

    assert first == second
    assert first.to_dict() == second.to_dict()
    serialized = json.dumps(first.to_dict(), sort_keys=True)
    assert "timestamp" not in serialized
    assert "weighted" not in serialized
    assert "percentage" not in serialized
    with pytest.raises(FrozenInstanceError):
        first.verdict = ArchitectureVerdict.CONDITIONAL  # type: ignore[misc]
