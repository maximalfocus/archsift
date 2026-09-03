from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path

import pytest

from archsift.decision import (
    MAX_COMPARISON_MATERIALITY_EVALUATIONS,
    ArchitectureVerdict,
    AssessmentEvaluation,
    CandidateDisposition,
    CandidateElimination,
    CriterionKind,
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
    BaselineRetention,
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
    EvidencedStatement,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    ResidualCase,
    StrongestSimplerBoundary,
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
                "prepare-disposition",
                "Prepare the bounded disposition.",
                False,
                "A reviewer remains responsible for the draft.",
            ),
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


def _agentic_agency() -> AgencyNecessity:
    def question(answer: AgencyAnswer) -> AgencyQuestion:
        return AgencyQuestion(answer, "Evidence-backed agency fact.", ("agency-observed",))

    return AgencyNecessity(
        execution_steps_predefinable=question(AgencyAnswer.NO),
        step_count_or_order_predictable=question(AgencyAnswer.NO),
        runtime_tool_choice_required=question(AgencyAnswer.YES),
        runtime_replanning_required=question(AgencyAnswer.NO),
        environmental_feedback_available=question(AgencyAnswer.YES),
        completion_independently_verifiable=question(AgencyAnswer.YES),
        effects_independently_verifiable=question(AgencyAnswer.YES),
        fixed_workflow_sufficient=question(AgencyAnswer.NO),
        residual_cases=(
            ResidualCase(
                "evidence-dependent-follow-up",
                "A new evidence gap requires a runtime choice.",
                "A fixed path cannot select the next approved retrieval step.",
                ("agency-observed",),
            ),
        ),
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
                (
                    ControlClass.DETERMINISTIC_AUTOMATION,
                    ControlClass.FIXED_AI_WORKFLOW,
                    ControlClass.AGENTIC_CONTROL,
                ),
            ),
            HardVeto(
                "ignored-inactive-veto",
                HardVetoStatus.INACTIVE,
                "An inactive synthetic condition.",
                "No current restriction.",
                ("release-disposition",),
                ("autonomy-observed",),
                (ControlClass.DETERMINISTIC_AUTOMATION,),
            ),
            HardVeto(
                "a-active-veto",
                HardVetoStatus.ACTIVE,
                "Approval evidence is absent.",
                "Release is prohibited until approval exists.",
                ("release-disposition",),
                ("autonomy-observed",),
                (
                    ControlClass.DETERMINISTIC_AUTOMATION,
                    ControlClass.FIXED_AI_WORKFLOW,
                    ControlClass.AGENTIC_CONTROL,
                ),
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
        authority=(
            CandidateAuthority(
                ("prepare-disposition",),
                (),
                ("autonomy-observed",),
            )
            if control_class
            in {
                ControlClass.DETERMINISTIC_AUTOMATION,
                ControlClass.FIXED_AI_WORKFLOW,
                ControlClass.AGENTIC_CONTROL,
            }
            else None
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
    boundary = None
    if strongest_id is not None and proposed_id != strongest_id:
        required_pairs.add((proposed_id, strongest_id))
    if proposed.control_class is not ControlClass.HUMAN_OWNED_WORK:
        assert strongest_id is not None
        class_order = tuple(ControlClass)
        proposed_rank = class_order.index(proposed.control_class)
        considered_ids = tuple(
            candidate.id
            for candidate in typed_candidates
            if class_order.index(candidate.control_class) < proposed_rank
        )
        required_pairs.update(
            (strongest_id, identifier)
            for identifier in considered_ids
            if identifier != strongest_id
        )
        boundary = StrongestSimplerBoundary(
            strongest_candidate_id=strongest_id,
            scope="All represented synthetic candidates below the proposal.",
            rationale="The selected candidate is the strongest represented simpler option.",
            considered_candidate_ids=considered_ids,
            evidence_ids=("decision-observed",),
        )
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
        agency_necessity=_agentic_agency() if agentic_candidates else _agency(),
        autonomy_permission=_autonomy(),
        candidate_comparison=CandidateComparison(
            typed_candidates,
            comparisons,
            boundary,
        ),
    )


def _replace_comparison_results(
    dossier: Dossier,
    pair_index: int,
    **results: ComparisonResult,
) -> Dossier:
    assert dossier.candidate_comparison is not None
    comparisons = dossier.candidate_comparison.comparisons
    pair = comparisons[pair_index]
    dimensions = replace(
        pair.dimensions,
        **{
            name: replace(getattr(pair.dimensions, name), result=result)
            for name, result in results.items()
        },
    )
    return replace(
        dossier,
        candidate_comparison=replace(
            dossier.candidate_comparison,
            comparisons=(
                *comparisons[:pair_index],
                replace(pair, dimensions=dimensions),
                *comparisons[pair_index + 1 :],
            ),
        ),
    )


def test_verdict_values_and_rules_are_complete_versioned_and_non_scoring() -> None:
    assert {verdict.value for verdict in ArchitectureVerdict} == {
        "supported",
        "conditional",
        "insufficient-evidence",
        "no-permissible-candidate",
        "no-technology-change",
    }
    assert RULESET_VERSION == "1.13.0"
    rules = [rule for rule in list_rules() if rule.requirement == "FR-010"]
    assert [(rule.id, rule.effect) for rule in rules] == [
        ("verdict-conditional", RuleEffect.SUPPORT_CANDIDATE),
        ("verdict-insufficient-evidence", RuleEffect.REQUIRE_EVIDENCE),
        ("verdict-no-permissible-candidate", RuleEffect.BLOCK),
        ("verdict-no-technology-change", RuleEffect.SUPPORT_CANDIDATE),
        ("verdict-supported", RuleEffect.SUPPORT_CANDIDATE),
    ]
    autonomy_rules = [rule for rule in list_rules() if rule.requirement == "FR-007/FR-009"]
    assert [(rule.id, rule.effect) for rule in autonomy_rules] == [
        ("active-veto-applicability-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("active-veto-blocks-candidate", RuleEffect.BLOCK),
        ("automation-authority-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("autonomy-boundary-non-decisive", RuleEffect.NON_DECISIVE),
        ("credible-authority-evidence-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("mandatory-human-control-omitted", RuleEffect.BLOCK),
        ("mandatory-human-control-retained", RuleEffect.CONSTRAIN_AUTONOMY),
        ("overlapping-veto-status-unknown", RuleEffect.REQUIRE_EVIDENCE),
    ]
    assert all(rule.source_rationale for rule in autonomy_rules)
    agency_rules = [rule for rule in list_rules() if rule.requirement == "FR-006/FR-009"]
    assert [(rule.id, rule.effect) for rule in agency_rules] == [
        ("agentic-agency-answer-unknown", RuleEffect.REQUIRE_EVIDENCE),
        ("agentic-agency-fact-non-decisive", RuleEffect.NON_DECISIVE),
        ("agentic-agency-necessity-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("agentic-credible-agency-evidence-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("agentic-credible-residual-evidence-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("agentic-dynamic-execution-supports-agency", RuleEffect.SUPPORT_CANDIDATE),
        ("agentic-feedback-supports-agency", RuleEffect.SUPPORT_CANDIDATE),
        ("agentic-feedback-unavailable-blocks-candidate", RuleEffect.BLOCK),
        (
            "agentic-fixed-workflow-insufficiency-supports-agency",
            RuleEffect.SUPPORT_CANDIDATE,
        ),
        ("agentic-fixed-workflow-sufficient-blocks-candidate", RuleEffect.BLOCK),
        ("agentic-residual-case-missing", RuleEffect.REQUIRE_EVIDENCE),
        ("agentic-residual-case-supports-agency", RuleEffect.SUPPORT_CANDIDATE),
        ("agentic-runtime-adaptation-missing", RuleEffect.BLOCK),
        ("agentic-runtime-adaptation-supports-agency", RuleEffect.SUPPORT_CANDIDATE),
    ]
    assert all(rule.source_rationale for rule in agency_rules)


def test_verdict_invariant_unknown_comparison_is_non_decisive() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    dossier = _replace_comparison_results(dossier, 0, cost=ComparisonResult.UNKNOWN)

    first = evaluate_assessment(dossier)
    second = evaluate_assessment(dossier)

    assert first == second
    assert first.verdict is ArchitectureVerdict.SUPPORTED
    assert first.prerequisite_evaluation.ready is True
    finding = next(
        finding
        for finding in first.prerequisite_evaluation.findings
        if finding.field.endswith(".dimensions.cost.result")
    )
    assert finding.rule_id == "comparison-result-unknown-non-decisive"
    assert finding.requirement == "FR-008/FR-009"
    assert finding.effect is RuleEffect.NON_DECISIVE
    assert finding.counterpart == "counterfactual verdict: supported"
    assert "Every admissible value preserves the verdict" in finding.message


def test_verdict_changing_unknown_comparison_remains_material() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    dossier = _replace_comparison_results(dossier, 0, cost=ComparisonResult.UNKNOWN)
    assert dossier.candidate_comparison is not None
    reverse_dimensions = replace(
        _dimensions(),
        cost=replace(_dimensions().cost, result=ComparisonResult.BETTER),
    )
    dossier = replace(
        dossier,
        candidate_comparison=replace(
            dossier.candidate_comparison,
            comparisons=(
                *dossier.candidate_comparison.comparisons,
                CandidatePairComparison("human", "fixed", reverse_dimensions),
            ),
        ),
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.prerequisite_evaluation.ready is False
    finding = next(
        finding
        for finding in evaluation.prerequisite_evaluation.findings
        if finding.field.endswith("[0].dimensions.cost.result")
    )
    assert finding.rule_id == "comparison-result-unknown"
    assert finding.effect is RuleEffect.REQUIRE_EVIDENCE
    assert finding.counterpart == ("counterfactual verdicts: supported, insufficient-evidence")
    assert "Admissible values produce differing verdicts" in finding.message


def test_unknown_comparison_materiality_fails_closed_above_bound() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    dossier = _replace_comparison_results(
        dossier,
        0,
        cost=ComparisonResult.UNKNOWN,
        latency=ComparisonResult.UNKNOWN,
        human_effort=ComparisonResult.UNKNOWN,
        integration_burden=ComparisonResult.UNKNOWN,
        operability=ComparisonResult.UNKNOWN,
    )

    evaluation = evaluate_assessment(dossier)

    admissible_result_count = len(
        (ComparisonResult.BETTER, ComparisonResult.EQUIVALENT, ComparisonResult.WORSE)
    )
    assert admissible_result_count**5 > MAX_COMPARISON_MATERIALITY_EVALUATIONS
    unknown_findings = tuple(
        finding
        for finding in evaluation.prerequisite_evaluation.findings
        if finding.rule_id == "comparison-result-unknown"
    )
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert len(unknown_findings) == 5
    assert all(
        finding.counterpart == "counterfactual enumeration bound exceeded"
        for finding in unknown_findings
    )


def test_missing_strongest_simpler_boundary_abstains_before_selection() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    assert dossier.candidate_comparison is not None
    dossier = replace(
        dossier,
        candidate_comparison=replace(
            dossier.candidate_comparison,
            strongest_simpler_boundary=None,
        ),
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.recommended_class is None
    assert [
        finding.rule_id
        for finding in evaluation.prerequisite_evaluation.findings
        if "strongest_simpler_boundary" in finding.field
    ] == ["strongest-simpler-boundary-missing"]


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


def test_all_candidates_passing_the_binding_set_abstains_before_selection() -> None:
    problem = replace(
        _problem(),
        outcomes=(
            *_problem().outcomes,
            ProblemOutcome(
                "preferred-speed",
                "Reduce handling time when practical.",
                "Median minutes",
                "At most 8",
                "current-quality",
                False,
                ("decision-observed",),
            ),
        ),
        material_pain=EvidencedStatement("Synthetic review delay.", ("decision-observed",)),
    )
    human = _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS)
    process = _candidate("process", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS)
    non_binding_test = CandidateOutcomeTest(
        "preferred-speed",
        CandidateTestResult.MEETS,
        "Synthetic non-binding context.",
        ("decision-observed",),
    )
    dossier = _ready_dossier(
        replace(human, outcome_tests=(*human.outcome_tests, non_binding_test)),
        replace(process, outcome_tests=(*process.outcome_tests, non_binding_test)),
        current_id="human",
        proposed_id="human",
        strongest_id=None,
    )
    dossier = replace(dossier, problem_value=problem)

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.recommended_class is None
    assert evaluation.ordered_elimination_evaluation.least_surviving_class is (
        ControlClass.HUMAN_OWNED_WORK
    )
    finding = evaluation.prerequisite_evaluation.findings[-1]
    assert finding.rule_id == "non-discriminating-binding-set"
    assert finding.effect is RuleEffect.REQUIRE_EVIDENCE
    assert finding.field == "$.problem_value.outcomes"
    assert finding.evidence_ids == ("decision-observed",)
    assert "all represented candidates meet" in finding.message
    assert "required-quality" in finding.message
    assert "approval-required" in finding.message
    assert "preferred-speed" in finding.remediation
    assert "$.problem_value.material_pain" in finding.remediation


def test_current_baseline_without_a_binding_failure_abstains_even_when_an_option_fails() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.FAILS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    finding = evaluation.prerequisite_evaluation.findings[-1]
    assert finding.rule_id == "non-discriminating-binding-set"
    assert "current baseline 'human' fails no binding outcome" in finding.message
    assert "all represented candidates meet" not in finding.message


def test_credible_current_baseline_failure_keeps_a_discriminating_verdict() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.prerequisite_evaluation.ready is True
    assert not any(
        finding.rule_id == "non-discriminating-binding-set"
        for finding in evaluation.prerequisite_evaluation.findings
    )
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.recommended_class is ControlClass.FIXED_AI_WORKFLOW


@pytest.mark.parametrize(
    ("selected_class", "expected_verdict"),
    [
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


def _agentic_candidate_dossier() -> Dossier:
    return _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("agentic", ControlClass.AGENTIC_CONTROL, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="agentic",
        strongest_id="human",
    )


def _agentic_result(evaluation: AssessmentEvaluation) -> CandidateElimination:
    return next(
        candidate
        for candidate in evaluation.ordered_elimination_evaluation.candidates
        if candidate.candidate_id == "agentic"
    )


def test_credible_runtime_tool_choice_and_residual_insufficiency_support_agentic() -> None:
    evaluation = evaluate_assessment(_agentic_candidate_dossier())

    assert _agentic_result(evaluation).disposition is CandidateDisposition.SURVIVES
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.recommended_class is ControlClass.AGENTIC_CONTROL
    agency_findings = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.candidate_id == "agentic"
        and finding.criterion_kind
        in {
            CriterionKind.AGENCY_QUESTION,
            CriterionKind.RESIDUAL_CASE,
            CriterionKind.DERIVED_AGENCY,
        }
    ]
    by_criterion = {finding.criterion_id: finding for finding in agency_findings}
    assert by_criterion["execution_steps_predefinable"].rule_id == (
        "agentic-dynamic-execution-supports-agency"
    )
    assert by_criterion["step_count_or_order_predictable"].effect is RuleEffect.SUPPORT_CANDIDATE
    assert by_criterion["runtime_tool_choice_required"].rule_id == (
        "agentic-runtime-adaptation-supports-agency"
    )
    assert by_criterion["runtime_replanning_required"].effect is RuleEffect.NON_DECISIVE
    assert by_criterion["environmental_feedback_available"].rule_id == (
        "agentic-feedback-supports-agency"
    )
    assert by_criterion["completion_independently_verifiable"].effect is RuleEffect.NON_DECISIVE
    assert by_criterion["effects_independently_verifiable"].effect is RuleEffect.NON_DECISIVE
    assert by_criterion["fixed_workflow_sufficient"].rule_id == (
        "agentic-fixed-workflow-insufficiency-supports-agency"
    )
    residual = by_criterion["evidence-dependent-follow-up"]
    assert residual.rule_id == "agentic-residual-case-supports-agency"
    assert residual.criterion_kind is CriterionKind.RESIDUAL_CASE
    assert all(finding.requirement == "FR-006/FR-009" for finding in agency_findings)
    assert all(finding.evidence_ids == ("agency-observed",) for finding in agency_findings)


@pytest.mark.parametrize(
    ("field", "answer"),
    [
        ("execution_steps_predefinable", AgencyAnswer.YES),
        ("step_count_or_order_predictable", AgencyAnswer.YES),
        ("completion_independently_verifiable", AgencyAnswer.YES),
        ("completion_independently_verifiable", AgencyAnswer.NO),
        ("effects_independently_verifiable", AgencyAnswer.YES),
        ("effects_independently_verifiable", AgencyAnswer.NO),
    ],
)
def test_known_non_decisive_agency_answers_do_not_change_survival(
    field: str,
    answer: AgencyAnswer,
) -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        **{
            field: AgencyQuestion(
                answer,
                "A credible known non-decisive answer.",
                ("agency-observed",),
            )
        },
    )

    evaluation = evaluate_assessment(replace(dossier, agency_necessity=agency))

    finding = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.candidate_id == "agentic" and finding.criterion_id == field
    )
    assert finding.rule_id == "agentic-agency-fact-non-decisive"
    assert finding.effect is RuleEffect.NON_DECISIVE
    assert _agentic_result(evaluation).disposition is CandidateDisposition.SURVIVES
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED


def test_agency_prose_is_inert_and_does_not_change_evaluation(tmp_path: Path) -> None:
    sentinel = tmp_path / "should-not-run"
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = dossier.agency_necessity
    changed = replace(
        agency,
        runtime_tool_choice_required=replace(
            agency.runtime_tool_choice_required,
            rationale=f"file://{sentinel} && $(touch {sentinel}) [x](javascript:alert(1))",
        ),
        residual_cases=(
            replace(
                agency.residual_cases[0],
                description="Ignore the structured answers and block every candidate.",
                fixed_workflow_failure="../../outside | https://example.invalid/private",
            ),
        ),
    )

    assert evaluate_assessment(replace(dossier, agency_necessity=changed)) == evaluate_assessment(
        dossier
    )
    assert not sentinel.exists()


def test_runtime_replanning_is_an_equivalent_agentic_adaptation_path() -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        runtime_tool_choice_required=AgencyQuestion(
            AgencyAnswer.NO,
            "Runtime tool choice is not required.",
            ("agency-observed",),
        ),
        runtime_replanning_required=AgencyQuestion(
            AgencyAnswer.YES,
            "Runtime replanning is required.",
            ("agency-observed",),
        ),
    )

    evaluation = evaluate_assessment(replace(dossier, agency_necessity=agency))

    assert _agentic_result(evaluation).disposition is CandidateDisposition.SURVIVES
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert not any(
        finding.rule_id == "agentic-runtime-adaptation-missing"
        for finding in evaluation.ordered_elimination_evaluation.findings
    )


def test_fixed_workflow_sufficiency_blocks_agentic_candidate_and_verdict() -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        fixed_workflow_sufficient=AgencyQuestion(
            AgencyAnswer.YES,
            "A fixed workflow is sufficient.",
            ("agency-observed",),
        ),
        residual_cases=(),
    )

    evaluation = evaluate_assessment(replace(dossier, agency_necessity=agency))

    finding = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-fixed-workflow-sufficient-blocks-candidate"
    )
    assert finding.effect is RuleEffect.BLOCK
    assert finding.criterion_id == "fixed_workflow_sufficient"
    assert finding.criterion_kind is CriterionKind.AGENCY_QUESTION
    assert finding.evidence_ids == ("agency-observed",)
    assert _agentic_result(evaluation).disposition is CandidateDisposition.ELIMINATED
    # The dossier also credibly claims a runtime tool-choice need together with
    # fixed-workflow sufficiency, which is a decision-critical contradiction:
    # the candidate block stands, but the aggregate prerequisites stay unready
    # and the verdict abstains instead of promoting another class.
    assert any(
        finding.rule_id == "agency-necessity-contradiction"
        for finding in evaluation.prerequisite_evaluation.findings
    )
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_absent_runtime_adaptation_blocks_agentic_candidate() -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        runtime_tool_choice_required=AgencyQuestion(
            AgencyAnswer.NO,
            "Runtime tool choice is not required.",
            ("tool-choice-observed",),
        ),
        runtime_replanning_required=AgencyQuestion(
            AgencyAnswer.NO,
            "Runtime replanning is not required.",
            ("replanning-observed",),
        ),
    )

    evaluation = evaluate_assessment(
        replace(
            dossier,
            evidence=(
                *dossier.evidence,
                _observed("tool-choice-observed", DecisionArea.AGENCY_NECESSITY),
                _observed("replanning-observed", DecisionArea.AGENCY_NECESSITY),
            ),
            agency_necessity=agency,
        )
    )

    finding = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-runtime-adaptation-missing"
    )
    assert finding.effect is RuleEffect.BLOCK
    assert finding.criterion_id == ("runtime_replanning_required+runtime_tool_choice_required")
    assert finding.criterion_kind is CriterionKind.DERIVED_AGENCY
    assert finding.evidence_ids == ("replanning-observed", "tool-choice-observed")
    assert _agentic_result(evaluation).disposition is CandidateDisposition.ELIMINATED
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE


def test_unavailable_environmental_feedback_blocks_agentic_candidate() -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        environmental_feedback_available=AgencyQuestion(
            AgencyAnswer.NO,
            "Environmental feedback is unavailable.",
            ("agency-observed",),
        ),
    )

    evaluation = evaluate_assessment(replace(dossier, agency_necessity=agency))

    finding = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-feedback-unavailable-blocks-candidate"
    )
    assert finding.effect is RuleEffect.BLOCK
    assert _agentic_result(evaluation).disposition is CandidateDisposition.ELIMINATED
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE


def test_unsupported_residual_case_leaves_agentic_candidate_undetermined() -> None:
    assumption = AssumptionEvidence(
        "agency-assumption",
        "The residual case may require runtime adaptation.",
        "Architecture reviewer",
        (DecisionArea.AGENCY_NECESSITY,),
        falsified_by="A representative fixed workflow handles the residual case.",
    )
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    residual = replace(
        dossier.agency_necessity.residual_cases[0],
        evidence_ids=("agency-assumption",),
    )
    dossier = replace(
        dossier,
        evidence=(*dossier.evidence, assumption),
        agency_necessity=replace(dossier.agency_necessity, residual_cases=(residual,)),
    )

    evaluation = evaluate_assessment(dossier)

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-credible-residual-evidence-missing"
    )
    assert gap.effect is RuleEffect.REQUIRE_EVIDENCE
    assert gap.criterion_id == "evidence-dependent-follow-up"
    assert gap.evidence_ids == ("agency-assumption",)
    assert _agentic_result(evaluation).disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert any(
        finding.rule_id == "credible-residual-case-evidence-missing"
        for finding in evaluation.prerequisite_evaluation.findings
    )


def test_unknown_unsupported_agency_answer_preserves_both_candidate_gaps() -> None:
    assumption = AssumptionEvidence(
        "runtime-choice-assumption",
        "Runtime tool choice may be required.",
        "Architecture reviewer",
        (DecisionArea.AGENCY_NECESSITY,),
        falsified_by="A representative workflow trial establishes a known answer.",
    )
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    agency = replace(
        dossier.agency_necessity,
        runtime_tool_choice_required=AgencyQuestion(
            AgencyAnswer.UNKNOWN,
            "Runtime tool choice is unresolved.",
            ("runtime-choice-assumption",),
        ),
    )

    evaluation = evaluate_assessment(
        replace(
            dossier,
            evidence=(*dossier.evidence, assumption),
            agency_necessity=agency,
        )
    )

    gaps = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.criterion_id == "runtime_tool_choice_required"
        and finding.effect is RuleEffect.REQUIRE_EVIDENCE
    ]
    assert [gap.rule_id for gap in gaps] == [
        "agentic-agency-answer-unknown",
        "agentic-credible-agency-evidence-missing",
    ]
    assert all(gap.evidence_ids == ("runtime-choice-assumption",) for gap in gaps)
    assert _agentic_result(evaluation).disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    prerequisite_rule_ids = [
        finding.rule_id
        for finding in evaluation.prerequisite_evaluation.findings
        if "runtime_tool_choice_required" in finding.field
    ]
    assert prerequisite_rule_ids == [
        "agency-answer-unknown",
        "credible-agency-evidence-missing",
    ]


def test_missing_agency_section_leaves_agentic_candidate_undetermined() -> None:
    evaluation = evaluate_assessment(replace(_agentic_candidate_dossier(), agency_necessity=None))

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-agency-necessity-missing"
    )
    assert gap.criterion_id == "agency_necessity"
    assert gap.criterion_kind is CriterionKind.DERIVED_AGENCY
    assert gap.evidence_ids == ()
    assert _agentic_result(evaluation).disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_missing_residual_case_leaves_agentic_candidate_undetermined() -> None:
    dossier = _agentic_candidate_dossier()
    assert dossier.agency_necessity is not None
    dossier = replace(
        dossier,
        agency_necessity=replace(dossier.agency_necessity, residual_cases=()),
    )

    evaluation = evaluate_assessment(dossier)

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "agentic-residual-case-missing"
    )
    assert gap.criterion_id == "residual_cases"
    assert gap.criterion_kind is CriterionKind.RESIDUAL_CASE
    assert gap.evidence_ids == ("agency-observed",)
    assert _agentic_result(evaluation).disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_agency_support_cannot_override_binding_candidate_failure() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("agentic", ControlClass.AGENTIC_CONTROL, CandidateTestResult.FAILS),
        current_id="human",
        proposed_id="agentic",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert any(
        finding.candidate_id == "agentic"
        and finding.rule_id == "agentic-runtime-adaptation-supports-agency"
        for finding in evaluation.ordered_elimination_evaluation.findings
    )
    assert _agentic_result(evaluation).disposition is CandidateDisposition.ELIMINATED
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE


def test_non_discriminating_lower_class_survivor_abstains_before_agentic_promotion() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS),
        _candidate("agentic", ControlClass.AGENTIC_CONTROL, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="agentic",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    assert _agentic_result(evaluation).disposition is CandidateDisposition.SURVIVES
    assert evaluation.recommended_class is None
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.prerequisite_evaluation.findings[-1].rule_id == (
        "non-discriminating-binding-set"
    )
    assert evaluation.surviving_candidate_ids == ()


def test_adverse_agency_facts_do_not_apply_to_simpler_candidates() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    fixed = next(
        candidate
        for candidate in evaluation.ordered_elimination_evaluation.candidates
        if candidate.candidate_id == "fixed"
    )
    assert fixed.disposition is CandidateDisposition.SURVIVES
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert not any(
        finding.criterion_kind
        in {
            CriterionKind.AGENCY_QUESTION,
            CriterionKind.RESIDUAL_CASE,
            CriterionKind.DERIVED_AGENCY,
        }
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.candidate_id == "fixed"
    )


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
    [ControlClass.FIXED_AI_WORKFLOW],
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
    fixed_findings = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.candidate_id == "fixed"
        and finding.criterion_kind.value in {"hard-veto", "human-control"}
    ]
    assert fixed_findings
    assert all(finding.effect is RuleEffect.NON_DECISIVE for finding in fixed_findings)
    assert all(finding.action_ids == () for finding in fixed_findings)


def _release_authority_candidate(*, retained_controls: tuple[str, ...]) -> Candidate:
    candidate = _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS)
    assert candidate.authority is not None
    return replace(
        candidate,
        authority=replace(
            candidate.authority,
            action_ids=("release-disposition",),
            retained_human_control_ids=retained_controls,
        ),
    )


def _inactive_veto_autonomy(autonomy: AutonomyPermission) -> AutonomyPermission:
    return replace(
        autonomy,
        hard_vetoes=tuple(
            replace(veto, status=HardVetoStatus.INACTIVE) for veto in autonomy.hard_vetoes
        ),
    )


def test_retained_human_controls_constrain_without_inventing_a_condition() -> None:
    fixed = _release_authority_candidate(
        retained_controls=("a-approval-control", "z-review-control")
    )
    assert fixed.authority is not None
    fixed = replace(
        fixed,
        authority=replace(fixed.authority, evidence_ids=("authority-distinct",)),
    )
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        fixed,
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
        extra_evidence=(_observed("authority-distinct", DecisionArea.AUTONOMY_PERMISSION),),
    )
    assert dossier.autonomy_permission is not None
    dossier = replace(
        dossier,
        autonomy_permission=_inactive_veto_autonomy(dossier.autonomy_permission),
    )

    evaluation = evaluate_assessment(dossier)

    retained = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "mandatory-human-control-retained"
    ]
    assert [finding.criterion_id for finding in retained] == [
        "a-approval-control",
        "z-review-control",
    ]
    assert all(finding.effect is RuleEffect.CONSTRAIN_AUTONOMY for finding in retained)
    assert all(finding.action_ids == ("release-disposition",) for finding in retained)
    assert all(
        finding.evidence_ids == ("authority-distinct", "autonomy-observed") for finding in retained
    )
    assert evaluation.verdict is ArchitectureVerdict.SUPPORTED
    assert evaluation.unmet_conditions == ()


def test_omitted_mandatory_human_control_blocks_the_candidate() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _release_authority_candidate(retained_controls=()),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    assert dossier.autonomy_permission is not None
    dossier = replace(
        dossier,
        autonomy_permission=_inactive_veto_autonomy(dossier.autonomy_permission),
    )

    evaluation = evaluate_assessment(dossier)

    omitted = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "mandatory-human-control-omitted"
    ]
    assert [finding.criterion_id for finding in omitted] == [
        "a-approval-control",
        "z-review-control",
    ]
    assert all(finding.effect is RuleEffect.BLOCK for finding in omitted)
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE


def test_missing_automation_authority_leaves_candidate_undetermined() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        replace(
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
            authority=None,
        ),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "automation-authority-missing"
    )
    assert gap.effect is RuleEffect.REQUIRE_EVIDENCE
    assert gap.criterion_kind.value == "authority"
    assert gap.action_ids == ()
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_assumption_only_authority_evidence_leaves_candidate_undetermined() -> None:
    assumption = AssumptionEvidence(
        "authority-assumption",
        "The fixed workflow may control the release action.",
        "Architecture reviewer",
        (DecisionArea.AUTONOMY_PERMISSION,),
        falsified_by="Observe the candidate's actual task-action authority boundary.",
    )
    fixed = _release_authority_candidate(
        retained_controls=("a-approval-control", "z-review-control")
    )
    assert fixed.authority is not None
    fixed = replace(
        fixed,
        authority=replace(fixed.authority, evidence_ids=("authority-assumption",)),
    )
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        fixed,
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
        extra_evidence=(assumption,),
    )

    evaluation = evaluate_assessment(dossier)

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "credible-authority-evidence-missing"
    )
    assert gap.evidence_ids == ("authority-assumption",)
    assert gap.action_ids == ("release-disposition",)
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_missing_overlapping_veto_applicability_leaves_candidate_undetermined() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _release_authority_candidate(retained_controls=("a-approval-control", "z-review-control")),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    assert dossier.autonomy_permission is not None
    inactive = _inactive_veto_autonomy(dossier.autonomy_permission)
    first_veto = replace(
        inactive.hard_vetoes[0],
        status=HardVetoStatus.ACTIVE,
        prohibited_control_classes=None,
    )
    dossier = replace(
        dossier,
        autonomy_permission=replace(
            inactive,
            hard_vetoes=(first_veto, *inactive.hard_vetoes[1:]),
        ),
    )

    evaluation = evaluate_assessment(dossier)

    gap = next(
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "active-veto-applicability-missing"
    )
    assert gap.effect is RuleEffect.REQUIRE_EVIDENCE
    assert gap.action_ids == ("release-disposition",)
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_overlapping_unknown_veto_status_leaves_candidate_undetermined() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _release_authority_candidate(retained_controls=("a-approval-control", "z-review-control")),
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )
    assert dossier.autonomy_permission is not None
    inactive = _inactive_veto_autonomy(dossier.autonomy_permission)
    first_veto = replace(
        inactive.hard_vetoes[0],
        status=HardVetoStatus.UNKNOWN,
        prohibited_control_classes=(ControlClass.FIXED_AI_WORKFLOW,),
    )
    dossier = replace(
        dossier,
        autonomy_permission=replace(
            inactive,
            hard_vetoes=(first_veto, *inactive.hard_vetoes[1:]),
        ),
    )

    evaluation = evaluate_assessment(dossier)

    unknown = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.rule_id == "overlapping-veto-status-unknown"
    ]
    assert [finding.candidate_id for finding in unknown] == ["fixed"]
    assert all(finding.requirement == "FR-007/FR-009" for finding in unknown)
    assert all(finding.effect is RuleEffect.REQUIRE_EVIDENCE for finding in unknown)
    assert all(finding.criterion_kind.value == "hard-veto" for finding in unknown)
    assert all(finding.action_ids == ("release-disposition",) for finding in unknown)
    assert all("unknown applicability" in finding.message for finding in unknown)
    assert all("inactive" not in finding.message for finding in unknown)
    fixed_result = next(
        candidate
        for candidate in evaluation.ordered_elimination_evaluation.candidates
        if candidate.candidate_id == "fixed"
    )
    assert fixed_result.disposition.value == "undetermined"
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_active_veto_overlap_blocks_a_prohibited_automation_candidate() -> None:
    human = _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS)
    fixed = _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS)
    assert fixed.authority is not None
    fixed = replace(
        fixed,
        authority=replace(
            fixed.authority,
            action_ids=("release-disposition",),
            retained_human_control_ids=("a-approval-control", "z-review-control"),
        ),
    )
    dossier = _ready_dossier(
        human,
        fixed,
        current_id="human",
        proposed_id="fixed",
        strongest_id="human",
    )

    evaluation = evaluate_assessment(dossier)

    fixed_result = next(
        candidate
        for candidate in evaluation.ordered_elimination_evaluation.candidates
        if candidate.candidate_id == "fixed"
    )
    assert fixed_result.disposition.value == "eliminated"
    veto_findings = [
        finding
        for finding in evaluation.ordered_elimination_evaluation.findings
        if finding.candidate_id == "fixed" and finding.criterion_kind.value == "hard-veto"
    ]
    assert [finding.rule_id for finding in veto_findings] == [
        "active-veto-blocks-candidate",
        "autonomy-boundary-non-decisive",
        "active-veto-blocks-candidate",
    ]
    assert all(finding.action_ids == ("release-disposition",) for finding in veto_findings)
    assert evaluation.verdict is ArchitectureVerdict.NO_PERMISSIBLE_CANDIDATE


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


def test_dossier_level_non_decisive_agency_findings_when_no_agentic_candidate() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("redesign", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="redesign",
        strongest_id="human",
    )
    result = evaluate_assessment(dossier)
    findings = result.ordered_elimination_evaluation.findings
    non_decisive = [f for f in findings if f.rule_id == "agentic-agency-fact-non-decisive"]
    assert non_decisive
    assert all(f.candidate_id is None and f.control_class is None for f in non_decisive)
    assert all(f.criterion_kind is CriterionKind.AGENCY_QUESTION for f in non_decisive)
    assert all(f.effect is RuleEffect.NON_DECISIVE for f in non_decisive)
    assert result.verdict in {
        ArchitectureVerdict.NO_TECHNOLOGY_CHANGE,
        ArchitectureVerdict.SUPPORTED,
        ArchitectureVerdict.CONDITIONAL,
    }


def test_dossier_level_non_decisive_autonomy_findings_when_no_automation_candidate() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("redesign", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="redesign",
        strongest_id="human",
    )
    result = evaluate_assessment(dossier)
    findings = result.ordered_elimination_evaluation.findings
    non_decisive = [f for f in findings if f.rule_id == "autonomy-boundary-non-decisive"]
    assert non_decisive
    assert all(f.candidate_id is None and f.control_class is None for f in non_decisive)
    assert any(f.criterion_kind is CriterionKind.HARD_VETO for f in non_decisive)
    assert any(f.criterion_kind is CriterionKind.HUMAN_CONTROL for f in non_decisive)


def test_no_dossier_level_findings_when_agentic_candidate_represented() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
        _candidate("agentic", ControlClass.AGENTIC_CONTROL, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="agentic",
        strongest_id="human",
    )
    result = evaluate_assessment(dossier)
    findings = result.ordered_elimination_evaluation.findings
    assert not any(
        f.rule_id in {"agentic-agency-fact-non-decisive", "autonomy-boundary-non-decisive"}
        and f.candidate_id is None
        for f in findings
    )


def _retained(dossier: Dossier) -> Dossier:
    assert dossier.candidate_comparison is not None
    return replace(
        dossier,
        candidate_comparison=replace(
            dossier.candidate_comparison,
            baseline_retention=BaselineRetention(
                declared_by="Synthetic accountable owner",
                rationale="Synthetic decision to keep the current process.",
                evidence_ids=("decision-observed",),
            ),
        ),
    )


def test_declared_baseline_retention_satisfies_the_non_discriminating_prerequisite() -> None:
    dossier = _retained(
        _ready_dossier(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS),
            _candidate("process", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
            current_id="human",
            proposed_id="human",
            strongest_id=None,
        )
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.prerequisite_evaluation.ready is True
    assert not any(
        finding.rule_id in {"non-discriminating-binding-set", "baseline-retention-contradiction"}
        for finding in evaluation.prerequisite_evaluation.findings
    )
    assert evaluation.verdict is ArchitectureVerdict.NO_TECHNOLOGY_CHANGE
    assert evaluation.recommended_class is ControlClass.HUMAN_OWNED_WORK
    assert evaluation.surviving_candidate_ids == ("human",)


def test_declared_baseline_retention_never_promotes_or_supports_a_candidate() -> None:
    dossier = _retained(
        _ready_dossier(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS),
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
            current_id="human",
            proposed_id="fixed",
            strongest_id="human",
        )
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.NO_TECHNOLOGY_CHANGE
    assert evaluation.recommended_class is ControlClass.HUMAN_OWNED_WORK
    assert all(
        "retention" not in finding.rule_id
        for finding in evaluation.ordered_elimination_evaluation.findings
    )
    assert "human" in evaluation.surviving_candidate_ids


def test_declared_baseline_retention_beside_a_failing_baseline_is_a_contradiction() -> None:
    dossier = _retained(
        _ready_dossier(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.FAILS),
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW, CandidateTestResult.MEETS),
            current_id="human",
            proposed_id="fixed",
            strongest_id="human",
        )
    )

    evaluation = evaluate_assessment(dossier)

    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.recommended_class is None
    finding = next(
        finding
        for finding in evaluation.prerequisite_evaluation.findings
        if finding.rule_id == "baseline-retention-contradiction"
    )
    assert finding.effect is RuleEffect.REQUIRE_EVIDENCE
    assert finding.field == "$.candidate_comparison.baseline_retention"
    assert finding.counterpart == "$.candidate_comparison.candidates[0].outcome_tests[0].result"
    assert finding.evidence_ids == ("decision-observed",)
    assert "credibly fails binding outcome 'required-quality'" in finding.message


def test_non_discriminating_remediation_names_the_declaration_route() -> None:
    dossier = _ready_dossier(
        _candidate("human", ControlClass.HUMAN_OWNED_WORK, CandidateTestResult.MEETS),
        _candidate("process", ControlClass.PROCESS_REDESIGN, CandidateTestResult.MEETS),
        current_id="human",
        proposed_id="human",
        strongest_id=None,
    )

    evaluation = evaluate_assessment(dossier)

    finding = evaluation.prerequisite_evaluation.findings[-1]
    assert finding.rule_id == "non-discriminating-binding-set"
    assert "$.candidate_comparison.baseline_retention" in finding.remediation
