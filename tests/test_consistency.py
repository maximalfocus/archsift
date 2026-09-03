"""Focused regressions for the enumerated structured contradiction invariants."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from archsift.cli import main
from archsift.decision import ArchitectureVerdict, evaluate_assessment
from archsift.decision_record import (
    UnresolvedGapSource,
    compose_decision_record,
)
from archsift.diagnostics import ExitCode
from archsift.markdown_report import render_markdown_decision_report
from archsift.rules import evaluate_assessment_prerequisites, list_rules
from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    Candidate,
    CandidateAuthority,
    CandidateComparison,
    CandidateOutcomeTest,
    CandidatePairComparison,
    CandidateRole,
    CaseIdentity,
    ComparisonDimension,
    ComparisonDimensions,
    ComparisonResult,
    ControlClass,
    DecisionArea,
    Dossier,
    MissingEvidence,
    ObservedEvidence,
    ResidualCase,
    evaluate_consistency_readiness,
)
from archsift.workspace import initialize_workspace

_DIMENSIONS = (
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


def _observed(identifier: str, *, provenance: str = "evidence/synthetic.txt") -> ObservedEvidence:
    return ObservedEvidence(
        identifier,
        "A sanitised observed claim.",
        "Synthetic reviewer",
        (DecisionArea.AGENCY_NECESSITY, DecisionArea.COMPARATIVE_FIT),
        provenance=provenance,
        observed_at=date(2026, 8, 8),
    )


def _assumption(identifier: str) -> AssumptionEvidence:
    return AssumptionEvidence(
        identifier,
        "A sanitised assumption.",
        "Synthetic reviewer",
        (
            DecisionArea.AGENCY_NECESSITY,
            DecisionArea.AUTONOMY_PERMISSION,
            DecisionArea.COMPARATIVE_FIT,
        ),
        falsified_by="A named observation resolves the assumption.",
    )


def _missing(identifier: str) -> MissingEvidence:
    return MissingEvidence(
        identifier,
        "A sanitised known gap.",
        "Synthetic reviewer",
        (
            DecisionArea.AGENCY_NECESSITY,
            DecisionArea.AUTONOMY_PERMISSION,
            DecisionArea.COMPARATIVE_FIT,
        ),
        resolved_by="Collect the named observation.",
    )


def _question(answer: AgencyAnswer, evidence_id: str = "agency-observed") -> AgencyQuestion:
    return AgencyQuestion(answer, "Evidence-backed agency fact.", (evidence_id,))


def _agency(
    *,
    fixed: AgencyAnswer,
    tool: AgencyAnswer,
    replan: AgencyAnswer,
    residuals: tuple[ResidualCase, ...] = (),
) -> AgencyNecessity:
    return AgencyNecessity(
        execution_steps_predefinable=_question(AgencyAnswer.YES),
        step_count_or_order_predictable=_question(AgencyAnswer.YES),
        runtime_tool_choice_required=_question(tool),
        runtime_replanning_required=_question(replan),
        environmental_feedback_available=_question(AgencyAnswer.YES),
        completion_independently_verifiable=_question(AgencyAnswer.YES),
        effects_independently_verifiable=_question(AgencyAnswer.YES),
        fixed_workflow_sufficient=_question(fixed),
        residual_cases=residuals,
    )


def _base_dossier() -> Dossier:
    return Dossier(
        schema_version=1,
        case=CaseIdentity("consistency", "Consistency regressions"),
        evidence=(_observed("agency-observed"), _observed("comparison-observed")),
    )


def _dimension(
    result: ComparisonResult, evidence_id: str = "comparison-observed"
) -> ComparisonDimension:
    return ComparisonDimension(result, "Directional comparison.", (evidence_id,))


def _all_dimensions(result: ComparisonResult) -> ComparisonDimensions:
    return ComparisonDimensions(**{name: _dimension(result) for name in _DIMENSIONS})


def _dimensions_with(
    mismatch: str, primary: ComparisonResult, secondary: ComparisonResult
) -> ComparisonDimensions:
    values = {name: _dimension(ComparisonResult.EQUIVALENT) for name in _DIMENSIONS}
    values[mismatch] = _dimension(primary)
    return ComparisonDimensions(**values)


def _candidate(identifier: str, control_class: ControlClass) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Candidate {identifier}",
        description="A sanitised architecture candidate.",
        control_class=control_class,
        roles=(CandidateRole.CURRENT_BASELINE,)
        if identifier == "human"
        else (CandidateRole.PROPOSED,),
        material_deviations=(),
        outcome_tests=(
            CandidateOutcomeTest("reduce-time", "meets", "Known.", ("comparison-observed",)),
        ),
        constraint_tests=(),
    )


def _comparison_dossier(
    pairs: tuple[tuple[str, str, ComparisonDimensions], ...],
) -> Dossier:
    comparison = CandidateComparison(
        candidates=(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK),
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW),
        ),
        comparisons=tuple(
            CandidatePairComparison(subject, comparator, dims)
            for subject, comparator, dims in pairs
        ),
    )
    return replace(_base_dossier(), candidate_comparison=comparison)


def _authority_dossier(control_class: ControlClass) -> Dossier:
    authority = CandidateAuthority(("release-disposition",), (), ("autonomy-observed",))
    comparison = CandidateComparison(
        candidates=(
            replace(_candidate("human", control_class), authority=authority),
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW),
        ),
        comparisons=(),
    )
    return replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, _observed("autonomy-observed")),
        candidate_comparison=comparison,
    )


def _findings(dossier: Dossier) -> tuple[tuple[str, str, str | None, tuple[str, ...], str], ...]:
    return tuple(
        (item.id, item.field, item.counterpart, item.evidence_ids, item.message)
        for item in evaluate_consistency_readiness(dossier).findings
    )


def test_agency_tool_choice_contradiction_is_evidence_calibrated() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES, tool=AgencyAnswer.YES, replan=AgencyAnswer.NO
        ),
    )

    findings = _findings(dossier)

    assert findings == (
        (
            "agency-necessity-contradiction",
            "$.agency_necessity.fixed_workflow_sufficient.answer",
            "$.agency_necessity.runtime_tool_choice_required.answer",
            ("agency-observed",),
            "Agency facts contradict: fixed_workflow_sufficient is credibly 'yes' while "
            "'runtime_tool_choice_required' is credibly 'yes'.",
        ),
    )
    assert evaluate_consistency_readiness(dossier).ready is False


def test_agency_replanning_contradiction_reported_independently() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES, tool=AgencyAnswer.NO, replan=AgencyAnswer.YES
        ),
    )

    findings = _findings(dossier)

    assert findings == (
        (
            "agency-necessity-contradiction",
            "$.agency_necessity.fixed_workflow_sufficient.answer",
            "$.agency_necessity.runtime_replanning_required.answer",
            ("agency-observed",),
            "Agency facts contradict: fixed_workflow_sufficient is credibly 'yes' while "
            "'runtime_replanning_required' is credibly 'yes'.",
        ),
    )


def test_both_agency_adaptation_needs_report_each_conflicting_question() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES, tool=AgencyAnswer.YES, replan=AgencyAnswer.YES
        ),
    )

    findings = _findings(dossier)

    assert [item[0] for item in findings] == ["agency-necessity-contradiction"] * 2
    assert [item[2] for item in findings] == [
        "$.agency_necessity.runtime_tool_choice_required.answer",
        "$.agency_necessity.runtime_replanning_required.answer",
    ]


def test_fixed_workflow_yes_with_residual_case_is_a_contradiction() -> None:
    residual = ResidualCase(
        "residual-a",
        "A residual requires a runtime choice.",
        "A fixed path cannot select the next step.",
        ("agency-observed",),
    )
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES,
            tool=AgencyAnswer.NO,
            replan=AgencyAnswer.NO,
            residuals=(residual,),
        ),
    )

    findings = _findings(dossier)

    assert findings == (
        (
            "fixed-workflow-residual-contradiction",
            "$.agency_necessity.fixed_workflow_sufficient.answer",
            "$.agency_necessity.residual_cases[0].id",
            ("agency-observed",),
            "Residual case 'residual-a' records fixed-workflow failure while "
            "fixed_workflow_sufficient is credibly 'yes'.",
        ),
    )


def test_multiple_credible_residuals_produce_one_finding_each() -> None:
    residuals = (
        ResidualCase("residual-a", "A.", "Failure A.", ("agency-observed",)),
        ResidualCase("residual-b", "B.", "Failure B.", ("agency-observed",)),
    )
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES,
            tool=AgencyAnswer.NO,
            replan=AgencyAnswer.NO,
            residuals=residuals,
        ),
    )

    findings = _findings(dossier)

    assert [item[0] for item in findings] == ["fixed-workflow-residual-contradiction"] * 2


def test_fixed_workflow_no_with_residual_is_not_a_contradiction() -> None:
    residual = ResidualCase(
        "residual-a",
        "A residual requires a runtime choice.",
        "A fixed path cannot select the next step.",
        ("agency-observed",),
    )
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.NO,
            tool=AgencyAnswer.YES,
            replan=AgencyAnswer.NO,
            residuals=(residual,),
        ),
    )

    assert evaluate_consistency_readiness(dossier).ready is True


def test_assumption_only_agency_facts_are_not_upgraded_to_contradictions() -> None:
    # Blank provenance makes the occurrence non-credible on both sides.
    agency = AgencyNecessity(
        execution_steps_predefinable=_question(AgencyAnswer.YES),
        step_count_or_order_predictable=_question(AgencyAnswer.YES),
        runtime_tool_choice_required=AgencyQuestion(
            AgencyAnswer.YES, "Runtime tool choice.", ("agency-blank",)
        ),
        runtime_replanning_required=_question(AgencyAnswer.NO),
        environmental_feedback_available=_question(AgencyAnswer.YES),
        completion_independently_verifiable=_question(AgencyAnswer.YES),
        effects_independently_verifiable=_question(AgencyAnswer.YES),
        fixed_workflow_sufficient=AgencyQuestion(
            AgencyAnswer.YES, "Fixed workflow.", ("agency-blank",)
        ),
        residual_cases=(),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, _observed("agency-blank", provenance="")),
        agency_necessity=agency,
    )

    assert evaluate_consistency_readiness(dossier).ready is True


@pytest.mark.parametrize(
    "uncertain_evidence", [_assumption("agency-uncertain"), _missing("agency-uncertain")]
)
def test_assumption_or_known_gap_agency_facts_are_not_upgraded_to_contradictions(
    uncertain_evidence: AssumptionEvidence | MissingEvidence,
) -> None:
    agency = _agency(
        fixed=AgencyAnswer.YES,
        tool=AgencyAnswer.YES,
        replan=AgencyAnswer.NO,
    )
    agency = replace(
        agency,
        fixed_workflow_sufficient=replace(
            agency.fixed_workflow_sufficient,
            evidence_ids=(uncertain_evidence.id,),
        ),
        runtime_tool_choice_required=replace(
            agency.runtime_tool_choice_required,
            evidence_ids=(uncertain_evidence.id,),
        ),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, uncertain_evidence),
        agency_necessity=agency,
    )

    assert evaluate_consistency_readiness(dossier).ready is True


@pytest.mark.parametrize(
    "uncertain_evidence", [_assumption("residual-uncertain"), _missing("residual-uncertain")]
)
def test_assumption_or_known_gap_residual_is_not_upgraded_to_a_contradiction(
    uncertain_evidence: AssumptionEvidence | MissingEvidence,
) -> None:
    residual = ResidualCase(
        "residual-a",
        "A residual requires a runtime choice.",
        "A fixed path cannot select the next step.",
        (uncertain_evidence.id,),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, uncertain_evidence),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES,
            tool=AgencyAnswer.NO,
            replan=AgencyAnswer.NO,
            residuals=(residual,),
        ),
    )

    assert evaluate_consistency_readiness(dossier).ready is True


def test_contradiction_evidence_union_is_exact_unique_and_canonical() -> None:
    agency = _agency(
        fixed=AgencyAnswer.YES,
        tool=AgencyAnswer.YES,
        replan=AgencyAnswer.NO,
    )
    agency = replace(
        agency,
        fixed_workflow_sufficient=replace(
            agency.fixed_workflow_sufficient,
            evidence_ids=("z-observed", "a-observed", "z-observed"),
        ),
        runtime_tool_choice_required=replace(
            agency.runtime_tool_choice_required,
            evidence_ids=("m-observed", "a-observed"),
        ),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(
            *_base_dossier().evidence,
            _observed("z-observed"),
            _observed("a-observed"),
            _observed("m-observed"),
        ),
        agency_necessity=agency,
    )

    assert evaluate_consistency_readiness(dossier).findings[0].evidence_ids == (
        "a-observed",
        "m-observed",
        "z-observed",
    )


def test_human_owned_authority_is_a_candidate_contradiction() -> None:
    findings = _findings(_authority_dossier(ControlClass.HUMAN_OWNED_WORK))

    assert findings == (
        (
            "candidate-authority-class-contradiction",
            "$.candidate_comparison.candidates[0].authority",
            "$.candidate_comparison.candidates[0].control_class",
            ("autonomy-observed",),
            "Candidate 'human' carries an automation authority scope but its control class "
            "is 'human-owned-work'.",
        ),
    )


def test_process_redesign_authority_is_a_candidate_contradiction() -> None:
    findings = _findings(_authority_dossier(ControlClass.PROCESS_REDESIGN))

    assert [item[0] for item in findings] == ["candidate-authority-class-contradiction"]
    assert "process-redesign" in findings[0][4]


@pytest.mark.parametrize(
    "uncertain_evidence", [_assumption("autonomy-observed"), _missing("autonomy-observed")]
)
def test_human_authority_conflict_is_structural_even_with_uncertain_evidence(
    uncertain_evidence: AssumptionEvidence | MissingEvidence,
) -> None:
    dossier = _authority_dossier(ControlClass.HUMAN_OWNED_WORK)
    dossier = replace(
        dossier,
        evidence=tuple(
            uncertain_evidence if item.id == uncertain_evidence.id else item
            for item in dossier.evidence
        ),
    )

    findings = _findings(dossier)

    assert [item[0] for item in findings] == ["candidate-authority-class-contradiction"]
    assert findings[0][3] == ("autonomy-observed",)


def test_automation_candidate_authority_is_not_a_contradiction() -> None:
    authority = CandidateAuthority(("release-disposition",), (), ("autonomy-observed",))
    comparison = CandidateComparison(
        candidates=(
            _candidate("human", ControlClass.HUMAN_OWNED_WORK),
            replace(_candidate("fixed", ControlClass.FIXED_AI_WORKFLOW), authority=authority),
        ),
        comparisons=(),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, _observed("autonomy-observed")),
        candidate_comparison=comparison,
    )

    assert evaluate_consistency_readiness(dossier).ready is True


@pytest.mark.parametrize("dimension", _DIMENSIONS)
@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        (ComparisonResult.BETTER, ComparisonResult.BETTER),
        (ComparisonResult.BETTER, ComparisonResult.EQUIVALENT),
        (ComparisonResult.WORSE, ComparisonResult.WORSE),
        (ComparisonResult.WORSE, ComparisonResult.EQUIVALENT),
        (ComparisonResult.EQUIVALENT, ComparisonResult.BETTER),
        (ComparisonResult.EQUIVALENT, ComparisonResult.WORSE),
    ],
)
def test_incompatible_reciprocal_dimensions_are_contradictions(
    dimension: str,
    primary: ComparisonResult,
    secondary: ComparisonResult,
) -> None:
    primary_dims = _dimensions_with(dimension, primary, secondary)
    secondary_dims = _dimensions_with(dimension, secondary, primary)
    dossier = _comparison_dossier(
        (
            ("human", "fixed", primary_dims),
            ("fixed", "human", secondary_dims),
        )
    )

    findings = _findings(dossier)

    assert len(findings) == 1
    finding = findings[0]
    assert finding[0] == "comparison-reciprocity-contradiction"
    # Canonical direction is alphabetically first (fixed -> human), which is the
    # second authored comparison here.
    assert finding[1] == f"$.candidate_comparison.comparisons[1].dimensions.{dimension}.result"
    assert finding[2] == f"$.candidate_comparison.comparisons[0].dimensions.{dimension}.result"
    assert f"{dimension!r} between 'fixed' and 'human'" in finding[4]


@pytest.mark.parametrize("dimension", _DIMENSIONS)
@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        (ComparisonResult.BETTER, ComparisonResult.WORSE),
        (ComparisonResult.WORSE, ComparisonResult.BETTER),
        (ComparisonResult.EQUIVALENT, ComparisonResult.EQUIVALENT),
    ],
)
def test_compatible_reciprocal_dimensions_are_not_contradictions(
    dimension: str,
    primary: ComparisonResult,
    secondary: ComparisonResult,
) -> None:
    primary_dims = _dimensions_with(dimension, primary, secondary)
    secondary_dims = _dimensions_with(dimension, secondary, primary)
    dossier = _comparison_dossier(
        (
            ("human", "fixed", primary_dims),
            ("fixed", "human", secondary_dims),
        )
    )

    assert evaluate_consistency_readiness(dossier).ready is True


def test_reciprocity_checks_every_dimension_independently() -> None:
    primary_values = {name: _dimension(ComparisonResult.BETTER) for name in _DIMENSIONS}
    secondary_values = {name: _dimension(ComparisonResult.BETTER) for name in _DIMENSIONS}
    dossier = _comparison_dossier(
        (
            ("human", "fixed", ComparisonDimensions(**primary_values)),
            ("fixed", "human", ComparisonDimensions(**secondary_values)),
        )
    )

    findings = _findings(dossier)

    assert [item[0] for item in findings] == ["comparison-reciprocity-contradiction"] * len(
        _DIMENSIONS
    )
    assert {item[1].split(".dimensions.")[1].split(".")[0] for item in findings} == set(_DIMENSIONS)
    assert all(
        item[1].startswith("$.candidate_comparison.comparisons[1].dimensions.") for item in findings
    )
    assert all(
        item[2].startswith("$.candidate_comparison.comparisons[0].dimensions.") for item in findings
    )


def test_one_sided_pair_is_not_a_contradiction() -> None:
    dossier = _comparison_dossier((("human", "fixed", _all_dimensions(ComparisonResult.BETTER)),))

    assert evaluate_consistency_readiness(dossier).ready is True


def test_unknown_reciprocal_side_is_not_upgraded_to_a_contradiction() -> None:
    primary_dims = _dimensions_with("cost", ComparisonResult.BETTER, ComparisonResult.WORSE)
    secondary_dims = _all_dimensions(ComparisonResult.UNKNOWN)
    dossier = _comparison_dossier(
        (
            ("human", "fixed", primary_dims),
            ("fixed", "human", secondary_dims),
        )
    )

    assert evaluate_consistency_readiness(dossier).ready is True


@pytest.mark.parametrize(
    "uncertain_evidence",
    [_assumption("comparison-uncertain"), _missing("comparison-uncertain")],
)
def test_assumption_or_known_gap_reciprocal_side_is_not_upgraded_to_a_contradiction(
    uncertain_evidence: AssumptionEvidence | MissingEvidence,
) -> None:
    primary_dims = replace(
        _all_dimensions(ComparisonResult.EQUIVALENT),
        cost=_dimension(ComparisonResult.BETTER, uncertain_evidence.id),
    )
    secondary_dims = replace(
        _all_dimensions(ComparisonResult.EQUIVALENT),
        cost=_dimension(ComparisonResult.BETTER, uncertain_evidence.id),
    )
    dossier = _comparison_dossier(
        (
            ("human", "fixed", primary_dims),
            ("fixed", "human", secondary_dims),
        )
    )
    dossier = replace(
        dossier,
        evidence=(*dossier.evidence, uncertain_evidence),
    )

    assert evaluate_consistency_readiness(dossier).ready is True


def test_finding_order_is_canonical_independent_of_authored_direction() -> None:
    def build(forward: bool) -> Dossier:
        if forward:
            pairs = (
                ("fixed", "human", _all_dimensions(ComparisonResult.BETTER)),
                ("human", "fixed", _all_dimensions(ComparisonResult.BETTER)),
            )
        else:
            pairs = (
                ("human", "fixed", _all_dimensions(ComparisonResult.BETTER)),
                ("fixed", "human", _all_dimensions(ComparisonResult.BETTER)),
            )
        return _comparison_dossier(pairs)

    forward = _findings(build(True))
    reversed_order = _findings(build(False))

    # Finding sequence and messages are canonical; only the exact authored pair
    # index in the path shifts because the reverse direction occupies a different
    # authored position.
    assert [item[0] for item in forward] == [item[0] for item in reversed_order]
    assert [item[4] for item in forward] == [item[4] for item in reversed_order]
    assert [item[1].split(".dimensions.")[1] for item in forward] == [
        item[1].split(".dimensions.")[1] for item in reversed_order
    ]
    assert [item[0] for item in forward] == ["comparison-reciprocity-contradiction"] * len(
        _DIMENSIONS
    )


def test_multiple_simultaneous_contradictions_are_all_reported() -> None:
    residual = ResidualCase(
        "residual-a",
        "A residual requires a runtime choice.",
        "A fixed path cannot select the next step.",
        ("agency-observed",),
    )
    agency = _agency(
        fixed=AgencyAnswer.YES,
        tool=AgencyAnswer.YES,
        replan=AgencyAnswer.YES,
        residuals=(residual,),
    )
    authority = CandidateAuthority(("release-disposition",), (), ("autonomy-observed",))
    comparison = CandidateComparison(
        candidates=(
            replace(
                _candidate("human", ControlClass.HUMAN_OWNED_WORK),
                authority=authority,
            ),
            _candidate("fixed", ControlClass.FIXED_AI_WORKFLOW),
        ),
        comparisons=(),
    )
    dossier = replace(
        _base_dossier(),
        evidence=(*_base_dossier().evidence, _observed("autonomy-observed")),
        agency_necessity=agency,
        candidate_comparison=comparison,
    )

    findings = _findings(dossier)

    assert [item[0] for item in findings] == [
        "agency-necessity-contradiction",
        "agency-necessity-contradiction",
        "fixed-workflow-residual-contradiction",
        "candidate-authority-class-contradiction",
    ]


def test_contradiction_makes_aggregate_prerequisites_unready_and_abstains() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES, tool=AgencyAnswer.YES, replan=AgencyAnswer.NO
        ),
    )

    consistency = evaluate_consistency_readiness(dossier)
    prerequisites = evaluate_assessment_prerequisites(dossier)
    evaluation = evaluate_assessment(dossier)

    assert consistency.ready is False
    assert prerequisites.ready is False
    assert any(
        finding.rule_id == "agency-necessity-contradiction" for finding in prerequisites.findings
    )
    assert evaluation.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE


def test_resolving_the_contradiction_restores_readiness() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.NO, tool=AgencyAnswer.YES, replan=AgencyAnswer.NO
        ),
    )

    assert evaluate_consistency_readiness(dossier).ready is True


def test_validate_json_reports_consistency_unready_with_a_contradiction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def payload_for(fixed: str) -> dict[str, object]:
        workspace = tmp_path / f"case-{fixed}"
        assert initialize_workspace(workspace).exit_code == ExitCode.SUCCESS
        residuals: list[object] = (
            []
            if fixed == "yes"
            else [
                {
                    "id": "residual-a",
                    "description": "A residual requires a runtime choice.",
                    "fixed_workflow_failure": "A fixed path cannot select the next step.",
                    "evidence_ids": ["agency-observed"],
                }
            ]
        )
        (workspace / "case.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "case": {"id": "x", "title": "X"},
                    "evidence": [
                        {
                            "id": "agency-observed",
                            "kind": "observed",
                            "claim": "A sanitised agency observation.",
                            "owner": "Synthetic reviewer",
                            "affects": ["agency-necessity"],
                            "provenance": "evidence/synthetic.txt",
                            "observed_at": "2026-08-08",
                        }
                    ],
                    "agency_necessity": {
                        "execution_steps_predefinable": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "step_count_or_order_predictable": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "runtime_tool_choice_required": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "runtime_replanning_required": {
                            "answer": "no",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "environmental_feedback_available": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "completion_independently_verifiable": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "effects_independently_verifiable": {
                            "answer": "yes",
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "fixed_workflow_sufficient": {
                            "answer": fixed,
                            "rationale": "Known.",
                            "evidence_ids": ["agency-observed"],
                        },
                        "residual_cases": residuals,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
        captured = capsys.readouterr()
        assert captured.err == ""
        return json.loads(captured.out)

    contradictory = payload_for("yes")
    coherent = payload_for("no")

    assert contradictory["consistency_ready"] is False
    assert contradictory["assessment_prerequisites_ready"] is False
    # Four unrelated missing-section prerequisites plus the agency contradiction.
    assert contradictory["prerequisite_finding_count"] == 5
    assert coherent["consistency_ready"] is True
    assert coherent["prerequisite_finding_count"] == 4
    assert contradictory["ruleset_version"] == coherent["ruleset_version"] == "1.13.0"


def test_contradiction_findings_flow_into_records_reports_and_rule_output() -> None:
    dossier = replace(
        _base_dossier(),
        agency_necessity=_agency(
            fixed=AgencyAnswer.YES, tool=AgencyAnswer.YES, replan=AgencyAnswer.NO
        ),
    )
    record = compose_decision_record(dossier, tool_version="0.1.0-test")

    gap = next(
        item
        for item in record.unresolved_gaps
        if item.source is UnresolvedGapSource.PREREQUISITE
        and item.rule_id == "agency-necessity-contradiction"
    )
    assert gap.counterpart == "$.agency_necessity.runtime_tool_choice_required.answer"
    assert gap.evidence_ids == ("agency-observed",)
    rendered = render_markdown_decision_report(record).decode("utf-8")
    assert "agency-necessity-contradiction" in rendered
    assert "$.agency_necessity.runtime_tool_choice_required.answer" in rendered

    for rule_id in (
        "agency-necessity-contradiction",
        "candidate-authority-class-contradiction",
        "comparison-reciprocity-contradiction",
        "fixed-workflow-residual-contradiction",
    ):
        rule = next(rule for rule in list_rules() if rule.id == rule_id)
        assert rule.effect.value == "require-evidence"
        assert rule.requirement == "FR-008"
