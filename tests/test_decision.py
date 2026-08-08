from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from archsift.decision import (
    CandidateDisposition,
    ControlClassDisposition,
    CriterionKind,
    evaluate_ordered_elimination,
)
from archsift.rules import RULESET_VERSION, RuleEffect, list_rules
from archsift.validation import (
    AssumptionEvidence,
    Candidate,
    CandidateComparison,
    CandidateConstraintTest,
    CandidateOutcomeTest,
    CandidateTestResult,
    CaseIdentity,
    ControlClass,
    DecisionArea,
    Dossier,
    EstimateEvidence,
    Evidence,
    EvidencedStatement,
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
)


def _observed(identifier: str = "observed") -> ObservedEvidence:
    return ObservedEvidence(
        identifier,
        "A sanitised candidate observation.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        provenance="evidence/sanitised-result.txt",
        observed_at=date(2026, 8, 8),
    )


def _assumption(identifier: str = "assumption") -> AssumptionEvidence:
    return AssumptionEvidence(
        identifier,
        "A simpler candidate may fail.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        falsified_by="A representative trial shows the candidate meets the criterion.",
    )


def _estimate(identifier: str = "estimate") -> EstimateEvidence:
    return EstimateEvidence(
        identifier,
        "A method-backed forecast of candidate performance.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        method="Representative-case measurement with documented sampling.",
    )


def _missing(identifier: str = "missing") -> MissingEvidence:
    return MissingEvidence(
        identifier,
        "The candidate result has not been observed.",
        "Architecture reviewer",
        (DecisionArea.COMPARATIVE_FIT,),
        resolved_by="Run the representative candidate trial.",
    )


def _problem(*, non_binding: bool = False) -> ProblemValue:
    outcomes = [
        ProblemOutcome(
            "required-quality",
            "Meet required quality.",
            "Accepted cases",
            "At least 95 percent",
            "current-quality",
            True,
            ("observed",),
        )
    ]
    if non_binding:
        outcomes.append(
            ProblemOutcome(
                "preferred-speed",
                "Improve non-binding speed.",
                "Median minutes",
                "At most 5",
                "current-quality",
                False,
                ("observed",),
            )
        )
    return ProblemValue(
        outcomes=tuple(outcomes),
        baselines=(
            ProblemBaseline(
                "current-quality",
                "Current result.",
                "Accepted cases",
                "90 percent",
                ("observed",),
            ),
        ),
        constraints=(
            ProblemConstraint(
                "approval-required",
                "Human approval is required.",
                "Check approval before release.",
                "Approval exists",
                True,
                ("observed",),
            ),
        ),
        affected_volume=EvidencedStatement("Material volume.", ("observed",)),
        material_pain=EvidencedStatement("Material delay.", ("observed",)),
        error_cost=EvidencedStatement("Material rework.", ("observed",)),
        technology_limitation=EvidencedStatement("Current tooling limits search.", ("observed",)),
    )


def _outcome_test(
    result: CandidateTestResult,
    evidence_id: str = "observed",
    *,
    outcome_id: str = "required-quality",
) -> CandidateOutcomeTest:
    return CandidateOutcomeTest(
        outcome_id,
        result,
        "Evidence-backed outcome result.",
        (evidence_id,),
    )


def _constraint_test(
    result: CandidateTestResult = CandidateTestResult.MEETS,
    evidence_id: str = "observed",
) -> CandidateConstraintTest:
    return CandidateConstraintTest(
        "approval-required",
        result,
        "Evidence-backed constraint result.",
        (evidence_id,),
    )


def _candidate(
    identifier: str,
    control_class: ControlClass,
    outcome_result: CandidateTestResult = CandidateTestResult.MEETS,
    *,
    evidence_id: str = "observed",
    constraint_result: CandidateTestResult = CandidateTestResult.MEETS,
    extra_outcome_tests: tuple[CandidateOutcomeTest, ...] = (),
) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Candidate {identifier}",
        description="A sanitised architecture candidate.",
        control_class=control_class,
        roles=(),
        material_deviations=(),
        outcome_tests=(
            _outcome_test(outcome_result, evidence_id),
            *extra_outcome_tests,
        ),
        constraint_tests=(_constraint_test(constraint_result, evidence_id),),
    )


def _dossier(
    *candidates: Candidate,
    evidence: tuple[Evidence, ...] | None = None,
    problem: ProblemValue | None = None,
) -> Dossier:
    return Dossier(
        schema_version=1,
        case=CaseIdentity("ordered-elimination", "Ordered elimination"),
        evidence=evidence if evidence is not None else (_observed(),),
        problem_value=problem or _problem(),
        candidate_comparison=CandidateComparison(candidates, ()),
    )


def test_decision_rules_are_versioned_canonical_and_non_scoring() -> None:
    rules = list_rules()
    decision_rules = [rule for rule in rules if rule.requirement == "FR-009"]

    assert RULESET_VERSION == "1.3.0"
    assert [rule.id for rule in rules] == sorted(rule.id for rule in rules)
    assert [(rule.id, rule.effect) for rule in decision_rules] == [
        ("binding-constraint-failed", RuleEffect.BLOCK),
        ("binding-constraint-met", RuleEffect.SUPPORT_CANDIDATE),
        ("binding-outcome-failed", RuleEffect.BLOCK),
        ("binding-outcome-met", RuleEffect.SUPPORT_CANDIDATE),
    ]
    assert all(rule.effect.value != "score" for rule in rules)


def test_evidenced_simpler_failure_selects_least_surviving_represented_class() -> None:
    dossier = _dossier(
        _candidate(
            "human-current",
            ControlClass.HUMAN_OWNED_WORK,
            CandidateTestResult.FAILS,
        ),
        _candidate("fixed-workflow", ControlClass.FIXED_AI_WORKFLOW),
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert [candidate.disposition for candidate in evaluation.candidates] == [
        CandidateDisposition.ELIMINATED,
        CandidateDisposition.SURVIVES,
    ]
    assert [result.disposition for result in evaluation.control_classes] == [
        ControlClassDisposition.ELIMINATED,
        ControlClassDisposition.SURVIVES,
    ]
    assert evaluation.least_surviving_class is ControlClass.FIXED_AI_WORKFLOW
    failure = next(finding for finding in evaluation.findings if finding.effect is RuleEffect.BLOCK)
    assert failure.rule_id == "binding-outcome-failed"
    assert failure.candidate_id == "human-current"
    assert failure.control_class is ControlClass.HUMAN_OWNED_WORK
    assert failure.criterion_id == "required-quality"
    assert failure.criterion_kind is CriterionKind.OUTCOME
    assert failure.evidence_ids == ("observed",)
    assert failure.requirement == "FR-009"
    assert failure.consequence


def test_assumption_only_simpler_failure_cannot_promote_complexity() -> None:
    dossier = _dossier(
        _candidate(
            "human-current",
            ControlClass.HUMAN_OWNED_WORK,
            CandidateTestResult.FAILS,
            evidence_id="assumption",
        ),
        _candidate("fixed-workflow", ControlClass.FIXED_AI_WORKFLOW),
        evidence=(_observed(), _assumption()),
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert evaluation.candidates[0].disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.control_classes[0].disposition is ControlClassDisposition.UNDETERMINED
    assert evaluation.control_classes[1].disposition is ControlClassDisposition.SURVIVES
    assert evaluation.least_surviving_class is None
    gap = evaluation.findings[0]
    assert gap.rule_id == "credible-candidate-test-evidence-missing"
    assert gap.effect is RuleEffect.REQUIRE_EVIDENCE
    assert gap.evidence_ids == ("assumption",)
    assert not any(finding.effect is RuleEffect.BLOCK for finding in evaluation.findings[:2])


def test_missing_evidence_cannot_turn_a_failure_into_a_block() -> None:
    dossier = _dossier(
        _candidate(
            "human-current",
            ControlClass.HUMAN_OWNED_WORK,
            CandidateTestResult.FAILS,
            evidence_id="missing",
        ),
        evidence=(_observed(), _missing()),
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert evaluation.candidates[0].disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.findings[0].rule_id == "credible-candidate-test-evidence-missing"
    assert evaluation.findings[0].effect is RuleEffect.REQUIRE_EVIDENCE
    assert evaluation.findings[0].evidence_ids == ("missing",)


def test_method_backed_estimate_can_establish_a_binding_failure() -> None:
    dossier = _dossier(
        _candidate(
            "human-current",
            ControlClass.HUMAN_OWNED_WORK,
            CandidateTestResult.FAILS,
            evidence_id="estimate",
        ),
        evidence=(_observed(), _estimate()),
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert evaluation.candidates[0].disposition is CandidateDisposition.ELIMINATED
    assert evaluation.findings[0].rule_id == "binding-outcome-failed"
    assert evaluation.findings[0].effect is RuleEffect.BLOCK
    assert evaluation.findings[0].evidence_ids == ("estimate",)


def test_unknown_result_requires_evidence_even_when_its_reference_is_credible() -> None:
    dossier = _dossier(
        _candidate(
            "deterministic",
            ControlClass.DETERMINISTIC_AUTOMATION,
            CandidateTestResult.UNKNOWN,
        )
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert evaluation.candidates[0].disposition is CandidateDisposition.UNDETERMINED
    assert evaluation.least_surviving_class is None
    assert evaluation.findings[0].rule_id == "candidate-test-result-unknown"
    assert evaluation.findings[0].effect is RuleEffect.REQUIRE_EVIDENCE


def test_block_precedes_support_for_candidate_disposition() -> None:
    dossier = _dossier(
        _candidate(
            "fixed",
            ControlClass.FIXED_AI_WORKFLOW,
            constraint_result=CandidateTestResult.FAILS,
        )
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert [finding.effect for finding in evaluation.findings] == [
        RuleEffect.SUPPORT_CANDIDATE,
        RuleEffect.BLOCK,
    ]
    assert evaluation.candidates[0].disposition is CandidateDisposition.ELIMINATED
    assert evaluation.control_classes[0].disposition is ControlClassDisposition.ELIMINATED
    assert evaluation.least_surviving_class is None


def test_non_binding_failure_is_comparison_context_only() -> None:
    candidate = _candidate(
        "fixed",
        ControlClass.FIXED_AI_WORKFLOW,
        extra_outcome_tests=(
            _outcome_test(
                CandidateTestResult.FAILS,
                outcome_id="preferred-speed",
            ),
        ),
    )
    evaluation = evaluate_ordered_elimination(
        _dossier(candidate, problem=_problem(non_binding=True))
    )

    assert evaluation.candidates[0].disposition is CandidateDisposition.SURVIVES
    assert evaluation.least_surviving_class is ControlClass.FIXED_AI_WORKFLOW
    assert {finding.criterion_id for finding in evaluation.findings} == {
        "required-quality",
        "approval-required",
    }


def test_class_survives_when_one_of_multiple_candidates_survives() -> None:
    dossier = _dossier(
        _candidate(
            "z-blocked",
            ControlClass.DETERMINISTIC_AUTOMATION,
            CandidateTestResult.FAILS,
        ),
        _candidate("a-survivor", ControlClass.DETERMINISTIC_AUTOMATION),
    )

    evaluation = evaluate_ordered_elimination(dossier)

    assert [candidate.candidate_id for candidate in evaluation.candidates] == [
        "a-survivor",
        "z-blocked",
    ]
    assert evaluation.control_classes[0].candidate_ids == ("a-survivor", "z-blocked")
    assert evaluation.control_classes[0].disposition is ControlClassDisposition.SURVIVES
    assert evaluation.least_surviving_class is ControlClass.DETERMINISTIC_AUTOMATION


def test_evaluation_is_immutable_serializable_and_independent_of_candidate_order() -> None:
    simpler = _candidate(
        "human",
        ControlClass.HUMAN_OWNED_WORK,
        CandidateTestResult.FAILS,
    )
    proposed = _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW)

    first = evaluate_ordered_elimination(_dossier(proposed, simpler))
    second = evaluate_ordered_elimination(_dossier(simpler, proposed))

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["least_surviving_class"] == "fixed-ai-workflow"
    assert first.to_dict()["ruleset_version"] == RULESET_VERSION
    with pytest.raises(FrozenInstanceError):
        first.ruleset_version = "changed"  # type: ignore[misc]


def test_block_remains_decisive_when_another_binding_test_lacks_evidence() -> None:
    candidate = _candidate(
        "fixed",
        ControlClass.FIXED_AI_WORKFLOW,
        CandidateTestResult.FAILS,
    )
    candidate = replace(candidate, constraint_tests=(_constraint_test(evidence_id="assumption"),))
    evaluation = evaluate_ordered_elimination(
        _dossier(candidate, evidence=(_observed(), _assumption()))
    )

    assert {finding.effect for finding in evaluation.findings} == {
        RuleEffect.BLOCK,
        RuleEffect.REQUIRE_EVIDENCE,
    }
    assert evaluation.candidates[0].disposition is CandidateDisposition.ELIMINATED
