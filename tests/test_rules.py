from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.rules import (
    RULESET_VERSION,
    RuleEffect,
    evaluate_assessment_prerequisites,
    list_prerequisite_rules,
)
from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    AutonomyAnswer,
    AutonomyPermission,
    AutonomyQuestion,
    CaseIdentity,
    DecisionArea,
    Dossier,
    EvidencedStatement,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    ObservedEvidence,
    ProblemBaseline,
    ProblemOutcome,
    ProblemValue,
    TaskAction,
    TaskBoundary,
)


def _question(answer: AgencyAnswer, evidence_id: str = "agency-observed") -> AgencyQuestion:
    return AgencyQuestion(answer, "Evidence-backed agency fact.", (evidence_id,))


def _autonomy_question(answer: AutonomyAnswer) -> AutonomyQuestion:
    return AutonomyQuestion(answer, "Evidence-backed autonomy fact.", ("autonomy-observed",))


def _ready_dossier() -> Dossier:
    task = TaskBoundary(
        operation="Review one bounded case.",
        starts_when="A complete case arrives.",
        completes_when="A disposition is recorded.",
        accountable_owner="Operations owner",
        actors=("Reviewer", "Approver"),
        systems_and_tools=("Case register",),
        information_read=("Case data",),
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
    problem = ProblemValue(
        outcomes=(
            ProblemOutcome(
                "reduce-time",
                "Reduce handling time.",
                "Median minutes",
                "At most 8",
                "current-time",
                True,
                ("problem-observed",),
            ),
        ),
        baselines=(
            ProblemBaseline(
                "current-time",
                "Current handling time.",
                "Median minutes",
                "12",
                ("problem-observed",),
            ),
        ),
        constraints=(),
        affected_volume=EvidencedStatement("Material volume.", ("problem-observed",)),
        material_pain=EvidencedStatement("Manual delay.", ("problem-observed",)),
        error_cost=EvidencedStatement("Rework cost.", ("problem-observed",)),
        technology_limitation=EvidencedStatement("Search delay.", ("problem-observed",)),
    )
    agency = AgencyNecessity(
        execution_steps_predefinable=_question(AgencyAnswer.YES),
        step_count_or_order_predictable=_question(AgencyAnswer.YES),
        runtime_tool_choice_required=_question(AgencyAnswer.NO),
        runtime_replanning_required=_question(AgencyAnswer.NO),
        environmental_feedback_available=_question(AgencyAnswer.YES),
        completion_independently_verifiable=_question(AgencyAnswer.YES),
        effects_independently_verifiable=_question(AgencyAnswer.YES),
        fixed_workflow_sufficient=_question(AgencyAnswer.YES),
        residual_cases=(),
    )
    autonomy = AutonomyPermission(
        actions_reversible=_autonomy_question(AutonomyAnswer.NO),
        failure_blast_radius_bounded=_autonomy_question(AutonomyAnswer.YES),
        regulatory_automation_permitted=_autonomy_question(AutonomyAnswer.NO),
        data_confidence_sufficient=_autonomy_question(AutonomyAnswer.YES),
        accountable_owner_assigned=_autonomy_question(AutonomyAnswer.YES),
        decision_path_auditable=_autonomy_question(AutonomyAnswer.YES),
        timely_human_intervention_available=_autonomy_question(AutonomyAnswer.YES),
        safe_degradation_available=_autonomy_question(AutonomyAnswer.YES),
        hard_vetoes=(
            HardVeto(
                "no-autonomous-release",
                HardVetoStatus.ACTIVE,
                "Release would occur without approval.",
                "Autonomous release is prohibited.",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
        ),
        mandatory_human_controls=(
            MandatoryHumanControl(
                "approve-release",
                "Approve before release.",
                "Immediately before release.",
                "Approver",
                ("release-disposition",),
                ("autonomy-observed",),
            ),
        ),
    )
    return Dossier(
        schema_version=1,
        case=CaseIdentity("rules", "Rules test"),
        evidence=(
            ObservedEvidence(
                "problem-observed",
                "Measured current handling time.",
                "Process analyst",
                (DecisionArea.PROBLEM_VALUE,),
                provenance="Sanitised measurement.",
                observed_at=date(2026, 8, 7),
            ),
            ObservedEvidence(
                "agency-observed",
                "Measured bounded execution behavior.",
                "Engineering lead",
                (DecisionArea.AGENCY_NECESSITY,),
                provenance="Sanitised workflow trial.",
                observed_at=date(2026, 8, 7),
            ),
            ObservedEvidence(
                "autonomy-observed",
                "Reviewed approval control.",
                "Risk reviewer",
                (DecisionArea.AUTONOMY_PERMISSION,),
                provenance="Sanitised control review.",
                observed_at=date(2026, 8, 7),
            ),
        ),
        task=task,
        problem_value=problem,
        agency_necessity=agency,
        autonomy_permission=autonomy,
    )


def test_rule_catalog_is_versioned_complete_canonical_and_immutable() -> None:
    rules = list_prerequisite_rules()
    ids = [rule.id for rule in rules]

    assert RULESET_VERSION == "1.2.0"
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids)) == 26
    assert set(ids) == {
        "agency-answer-unknown",
        "agency-necessity-missing",
        "autonomy-answer-unknown",
        "autonomy-permission-missing",
        "baseline-reference-unresolved",
        "binding-outcome-missing",
        "candidate-comparison-missing",
        "candidate-constraint-test-missing",
        "candidate-outcome-test-missing",
        "candidate-problem-value-missing",
        "candidate-role-incompatible",
        "candidate-test-result-unknown",
        "credible-agency-evidence-missing",
        "credible-candidate-test-evidence-missing",
        "credible-comparison-evidence-missing",
        "credible-autonomy-evidence-missing",
        "credible-baseline-missing",
        "credible-hard-veto-evidence-missing",
        "credible-human-control-evidence-missing",
        "credible-residual-case-evidence-missing",
        "hard-veto-status-unknown",
        "comparison-result-unknown",
        "problem-value-missing",
        "required-candidate-role-missing",
        "required-comparison-missing",
        "task-boundary-missing",
    }
    assert all(rule.effect is RuleEffect.REQUIRE_EVIDENCE for rule in rules)
    assert all(
        rule.id.strip()
        and rule.requirement.strip()
        and rule.description.strip()
        and rule.consequence.strip()
        and rule.source_rationale.strip()
        for rule in rules
    )
    with pytest.raises(FrozenInstanceError):
        rules[0].description = "changed"  # type: ignore[misc]


def test_rules_cli_human_json_and_quiet_are_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["rules"]) == ExitCode.SUCCESS
    human_first = capsys.readouterr()
    assert main(["rules"]) == ExitCode.SUCCESS
    human_second = capsys.readouterr()
    assert human_first == human_second
    assert human_first.err == ""
    assert f"ArchSift ruleset {RULESET_VERSION}" in human_first.out
    assert "binding-outcome-failed [block; FR-009]" in human_first.out
    assert "task-boundary-missing [require-evidence; FR-003]" in human_first.out

    assert main(["rules", "--json"]) == ExitCode.SUCCESS
    json_first = capsys.readouterr()
    assert main(["rules", "--json"]) == ExitCode.SUCCESS
    json_second = capsys.readouterr()
    assert json_first == json_second
    assert json_first.err == ""
    payload = json.loads(json_first.out)
    assert payload["ruleset_version"] == RULESET_VERSION
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["diagnostics"] == []
    assert [rule["id"] for rule in payload["rules"]] == sorted(
        rule["id"] for rule in payload["rules"]
    )
    assert set(payload["rules"][0]) == {
        "consequence",
        "description",
        "effect",
        "id",
        "requirement",
        "source_rationale",
    }
    assert "verdict" not in payload

    assert main(["rules", "--quiet"]) == ExitCode.SUCCESS
    quiet = capsys.readouterr()
    assert quiet.out == quiet.err == ""


def test_absent_sections_produce_stable_area_order_without_invented_evidence() -> None:
    dossier = Dossier(schema_version=1, case=CaseIdentity("empty", "Empty"))

    first = evaluate_assessment_prerequisites(dossier)
    second = evaluate_assessment_prerequisites(dossier)

    assert first == second
    assert first.ruleset_version == RULESET_VERSION
    assert first.ready is False
    assert [(finding.rule_id, finding.field) for finding in first.findings] == [
        ("task-boundary-missing", "$.task"),
        ("problem-value-missing", "$.problem_value"),
        ("agency-necessity-missing", "$.agency_necessity"),
        ("autonomy-permission-missing", "$.autonomy_permission"),
        ("candidate-comparison-missing", "$.candidate_comparison"),
    ]
    assert all(finding.evidence_ids == () for finding in first.findings)
    assert all(finding.consequence and finding.remediation for finding in first.findings)


def test_ready_adverse_facts_and_active_veto_only_leave_candidate_gap() -> None:
    dossier = _ready_dossier()

    evaluation = evaluate_assessment_prerequisites(dossier)

    assert evaluation.ready is False
    assert [finding.rule_id for finding in evaluation.findings] == ["candidate-comparison-missing"]
    assert dossier.agency_necessity is not None
    assert dossier.agency_necessity.runtime_tool_choice_required.answer is AgencyAnswer.NO
    assert dossier.autonomy_permission is not None
    assert dossier.autonomy_permission.actions_reversible.answer is AutonomyAnswer.NO
    assert dossier.autonomy_permission.hard_vetoes[0].status is HardVetoStatus.ACTIVE


def test_findings_carry_exact_authored_evidence_ids_in_field_order() -> None:
    dossier = _ready_dossier()
    assert dossier.agency_necessity is not None
    uncertain_question = _question(AgencyAnswer.UNKNOWN, "agency-assumption")
    agency = replace(dossier.agency_necessity, runtime_replanning_required=uncertain_question)
    uncertain_evidence = AssumptionEvidence(
        "agency-assumption",
        "Runtime replanning may be needed.",
        "Engineering lead",
        (DecisionArea.AGENCY_NECESSITY,),
        falsified_by="A representative fixed-workflow trial handles every bounded branch.",
    )
    dossier = replace(
        dossier,
        agency_necessity=agency,
        evidence=(*dossier.evidence, uncertain_evidence),
    )

    evaluation = evaluate_assessment_prerequisites(dossier)

    assert evaluation.ready is False
    relevant = [
        finding
        for finding in evaluation.findings
        if finding.field.startswith("$.agency_necessity.runtime_replanning_required")
    ]
    assert [finding.rule_id for finding in relevant] == [
        "agency-answer-unknown",
        "credible-agency-evidence-missing",
    ]
    assert all(finding.evidence_ids == ("agency-assumption",) for finding in relevant)
    assert all(finding.effect is RuleEffect.REQUIRE_EVIDENCE for finding in relevant)
    assert all(finding.requirement == "FR-006" for finding in relevant)
