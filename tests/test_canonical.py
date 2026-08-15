from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest

from archsift.canonical import (
    CanonicalizationError,
    canonical_dossier_bytes,
    canonical_dossier_dict,
    canonical_evidence_bytes,
    canonical_evidence_dict,
    canonical_json_bytes,
    dossier_content_identity,
    evidence_content_identities,
    evidence_content_identity,
)
from archsift.diagnostics import ExitCode
from archsift.rules import RULESET_VERSION
from archsift.validation import (
    AgencyAnswer,
    AgencyNecessity,
    AgencyQuestion,
    AssumptionEvidence,
    AutonomyAnswer,
    AutonomyPermission,
    AutonomyQuestion,
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
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    ResidualCase,
    StrongestSimplerBoundary,
    TaskAction,
    TaskBoundary,
    validate_workspace,
)

_GOLDEN = Path(__file__).parent / "golden" / "canonical-dossier-v1.json"
_EXPECTED_DOSSIER_ID = "sha256:53f1c0161d2886c5e2bd05b243fd44f9df748c89952bbe9d86a764859c6c784b"
_EXPECTED_EVIDENCE_IDS = {
    "assumption": "sha256:10f6a22ef04cbac6a98c1d08b0966210e309d839fd7940373c7ed7644066c3ae",
    "estimate": "sha256:fff5c0155ee12491114a94548601a551ee293c00c2c7002978628d5a269d1245",
    "missing": "sha256:94a522411fdc35103e386abca6dc9e3b82fa0e49615b695c49928de72f739ccb",
    "observed": "sha256:50e01190e8e41240e1d451e85e15406e55d4f62617b5accd1c6c79f4b4a39050",
}


def _evidence() -> tuple[Evidence, ...]:
    all_areas = tuple(DecisionArea)
    return (
        ObservedEvidence(
            "observed",
            "Observed café throughput.\x1b",
            "Synthetic analyst",
            all_areas,
            provenance="evidence/synthetic-observation.csv",
            observed_at=date(2026, 8, 8),
        ),
        AssumptionEvidence(
            "assumption",
            "A bounded synthetic assumption.",
            "Synthetic owner",
            all_areas,
            falsified_by="A controlled observation disproves it.",
        ),
        EstimateEvidence(
            "estimate",
            "A synthetic forecast.",
            "Synthetic estimator",
            all_areas,
            method="A documented synthetic sampling method.",
        ),
        MissingEvidence(
            "missing",
            "A known synthetic evidence gap.",
            "Synthetic investigator",
            all_areas,
            resolved_by="Run the named synthetic observation.",
        ),
    )


def _task() -> TaskBoundary:
    return TaskBoundary(
        operation="Review one synthetic case.",
        starts_when="A complete request arrives.",
        completes_when="A disposition is recorded.",
        accountable_owner="Synthetic operations owner",
        actors=("Reviewer", "Approver"),
        systems_and_tools=("Case register", "Evidence viewer"),
        information_read=("Synthetic request", "Synthetic policy"),
        actions=(
            TaskAction(
                "record",
                "Record the disposition.",
                False,
                "The reviewer may record it.",
            ),
            TaskAction(
                "release",
                "Release the disposition.",
                True,
                "An approver must approve release.",
            ),
        ),
        exclusions=("Changing policy", "Executing the recommendation"),
    )


def _problem() -> ProblemValue:
    return ProblemValue(
        outcomes=(
            ProblemOutcome(
                "quality",
                "Meet synthetic quality.",
                "Accepted cases",
                "At least 95 percent",
                "quality-baseline",
                True,
                ("observed",),
            ),
            ProblemOutcome(
                "speed",
                "Improve synthetic speed.",
                "Median minutes",
                "At most 5",
                "speed-baseline",
                False,
                ("estimate",),
            ),
        ),
        baselines=(
            ProblemBaseline(
                "quality-baseline",
                "Current quality.",
                "Accepted cases",
                "90 percent",
                ("observed",),
            ),
            ProblemBaseline(
                "speed-baseline",
                "Current speed.",
                "Median minutes",
                "12",
                ("estimate",),
            ),
        ),
        constraints=(
            ProblemConstraint(
                "approval",
                "Approval is required.",
                "Check approval before release.",
                "Approval exists",
                True,
                ("observed",),
            ),
            ProblemConstraint(
                "preference",
                "A non-binding synthetic preference.",
                "Check the preferred presentation.",
                "Preference met",
                False,
                ("assumption",),
            ),
        ),
        affected_volume=EvidencedStatement("Material synthetic volume.", ("observed",)),
        material_pain=EvidencedStatement("Material synthetic delay.", ("observed",)),
        error_cost=EvidencedStatement("Material synthetic rework.", ("estimate",)),
        technology_limitation=EvidencedStatement(
            "Current retrieval is constrained.",
            ("assumption", "missing"),
        ),
    )


def _agency() -> AgencyNecessity:
    answers = (
        AgencyAnswer.YES,
        AgencyAnswer.NO,
        AgencyAnswer.UNKNOWN,
        AgencyAnswer.YES,
        AgencyAnswer.NO,
        AgencyAnswer.UNKNOWN,
        AgencyAnswer.YES,
        AgencyAnswer.NO,
    )

    def question(index: int) -> AgencyQuestion:
        return AgencyQuestion(
            answers[index],
            f"Synthetic agency rationale {index}.",
            (("observed", "estimate", "missing")[index % 3],),
        )

    return AgencyNecessity(
        execution_steps_predefinable=question(0),
        step_count_or_order_predictable=question(1),
        runtime_tool_choice_required=question(2),
        runtime_replanning_required=question(3),
        environmental_feedback_available=question(4),
        completion_independently_verifiable=question(5),
        effects_independently_verifiable=question(6),
        fixed_workflow_sufficient=question(7),
        residual_cases=(
            ResidualCase(
                "residual",
                "A fully synthetic residual case.",
                "The fixed path cannot classify its unseen branch.",
                ("estimate",),
            ),
        ),
    )


def _autonomy() -> AutonomyPermission:
    answers = (
        AutonomyAnswer.YES,
        AutonomyAnswer.NO,
        AutonomyAnswer.UNKNOWN,
        AutonomyAnswer.YES,
        AutonomyAnswer.NO,
        AutonomyAnswer.UNKNOWN,
        AutonomyAnswer.YES,
        AutonomyAnswer.NO,
    )

    def question(index: int) -> AutonomyQuestion:
        return AutonomyQuestion(
            answers[index],
            f"Synthetic autonomy rationale {index}.",
            (("observed", "estimate", "missing")[index % 3],),
        )

    return AutonomyPermission(
        actions_reversible=question(0),
        failure_blast_radius_bounded=question(1),
        regulatory_automation_permitted=question(2),
        data_confidence_sufficient=question(3),
        accountable_owner_assigned=question(4),
        decision_path_auditable=question(5),
        timely_human_intervention_available=question(6),
        safe_degradation_available=question(7),
        hard_vetoes=(
            HardVeto(
                "active-veto",
                HardVetoStatus.ACTIVE,
                "Release lacks approval.",
                "Release is prohibited.",
                ("release",),
                ("observed",),
                (ControlClass.FIXED_AI_WORKFLOW, ControlClass.AGENTIC_CONTROL),
            ),
            HardVeto(
                "inactive-veto",
                HardVetoStatus.INACTIVE,
                "A synthetic inactive condition.",
                "No current restriction.",
                ("record",),
                ("estimate",),
            ),
            HardVeto(
                "unknown-veto",
                HardVetoStatus.UNKNOWN,
                "Applicability is unresolved.",
                "Resolve applicability before release.",
                ("release",),
                ("missing",),
            ),
        ),
        mandatory_human_controls=(
            MandatoryHumanControl(
                "approve-release",
                "Approve before release.",
                "Immediately before release.",
                "Approver",
                ("release",),
                ("observed",),
            ),
        ),
    )


def _candidate(
    identifier: str,
    control_class: ControlClass,
    roles: tuple[CandidateRole, ...],
    result: CandidateTestResult,
) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Synthetic {control_class.value}",
        description=f"A synthetic {control_class.value} candidate.",
        control_class=control_class,
        roles=roles,
        material_deviations=(f"Synthetic deviation for {identifier}.",),
        outcome_tests=(
            CandidateOutcomeTest(
                "quality",
                result,
                f"Synthetic quality result for {identifier}.",
                (("observed", "estimate", "missing")[list(CandidateTestResult).index(result)],),
            ),
            CandidateOutcomeTest(
                "speed",
                CandidateTestResult.MEETS,
                f"Synthetic speed result for {identifier}.",
                ("estimate",),
            ),
        ),
        constraint_tests=(
            CandidateConstraintTest(
                "approval",
                result,
                f"Synthetic approval result for {identifier}.",
                (("observed", "estimate", "missing")[list(CandidateTestResult).index(result)],),
            ),
            CandidateConstraintTest(
                "preference",
                CandidateTestResult.FAILS,
                f"Synthetic preference result for {identifier}.",
                ("assumption",),
            ),
        ),
        authority=(
            CandidateAuthority(("record",), (), ("observed",))
            if control_class
            in {
                ControlClass.DETERMINISTIC_AUTOMATION,
                ControlClass.FIXED_AI_WORKFLOW,
                ControlClass.AGENTIC_CONTROL,
            }
            else None
        ),
    )


def _dimensions() -> ComparisonDimensions:
    results = (
        ComparisonResult.BETTER,
        ComparisonResult.EQUIVALENT,
        ComparisonResult.WORSE,
        ComparisonResult.UNKNOWN,
    )

    def dimension(index: int) -> ComparisonDimension:
        return ComparisonDimension(
            results[index % len(results)],
            f"Synthetic comparison rationale {index}.",
            (("observed", "estimate", "assumption", "missing")[index % 4],),
        )

    return ComparisonDimensions(
        outcome_quality=dimension(0),
        difficult_case_performance=dimension(1),
        cost=dimension(2),
        latency=dimension(3),
        human_effort=dimension(4),
        integration_burden=dimension(5),
        security_exposure=dimension(6),
        failure_impact=dimension(7),
        operability=dimension(8),
        evaluation_burden=dimension(9),
        maintainability=dimension(10),
    )


def full_dossier() -> Dossier:
    candidates = (
        _candidate(
            "human",
            ControlClass.HUMAN_OWNED_WORK,
            (CandidateRole.CURRENT_BASELINE,),
            CandidateTestResult.MEETS,
        ),
        _candidate(
            "process",
            ControlClass.PROCESS_REDESIGN,
            (CandidateRole.STRONGEST_SIMPLER,),
            CandidateTestResult.FAILS,
        ),
        _candidate(
            "deterministic",
            ControlClass.DETERMINISTIC_AUTOMATION,
            (),
            CandidateTestResult.UNKNOWN,
        ),
        _candidate(
            "fixed",
            ControlClass.FIXED_AI_WORKFLOW,
            (CandidateRole.PROPOSED,),
            CandidateTestResult.MEETS,
        ),
        _candidate(
            "agentic",
            ControlClass.AGENTIC_CONTROL,
            (CandidateRole.AGENTIC_COMPARATOR,),
            CandidateTestResult.FAILS,
        ),
    )
    return Dossier(
        schema_version=1,
        case=CaseIdentity("canonical", "Canonical café \u202e synthetic case"),
        evidence=_evidence(),
        task=_task(),
        problem_value=_problem(),
        agency_necessity=_agency(),
        autonomy_permission=_autonomy(),
        candidate_comparison=CandidateComparison(
            candidates,
            (
                CandidatePairComparison("process", "human", _dimensions()),
                CandidatePairComparison("deterministic", "human", _dimensions()),
                CandidatePairComparison("fixed", "human", _dimensions()),
                CandidatePairComparison("agentic", "human", _dimensions()),
                CandidatePairComparison("fixed", "process", _dimensions()),
                CandidatePairComparison("process", "deterministic", _dimensions()),
            ),
            StrongestSimplerBoundary(
                strongest_candidate_id="process",
                scope="All represented candidates below the fixed workflow.",
                rationale="Process redesign is the strongest represented simpler option.",
                considered_candidate_ids=("human", "process", "deterministic"),
                evidence_ids=("observed",),
            ),
        ),
        decision_conditions=(
            DecisionCondition(
                "verify-capacity",
                ControlClass.FIXED_AI_WORKFLOW,
                DecisionArea.COMPARATIVE_FIT,
                "Verify synthetic capacity.\x1b",
                DecisionConditionStatus.UNMET,
                "Run the named synthetic capacity test.",
                ("estimate",),
            ),
            DecisionCondition(
                "retain-approval",
                ControlClass.HUMAN_OWNED_WORK,
                DecisionArea.AUTONOMY_PERMISSION,
                "Retain synthetic approval.",
                DecisionConditionStatus.MET,
                "Observe the approval control operating.",
                ("observed",),
            ),
        ),
    )


def test_full_dossier_matches_exact_golden_bytes_and_identities() -> None:
    dossier = full_dossier()
    canonical = canonical_dossier_bytes(dossier)

    assert canonical == _GOLDEN.read_bytes()
    assert canonical_dossier_bytes(dossier) == canonical
    assert canonical.endswith(b"\n") and not canonical.endswith(b"\n\n")
    assert json.loads(canonical) == canonical_dossier_dict(dossier)
    assert b"ObservedEvidence" not in canonical
    assert b"datetime.date" not in canonical
    assert b"<object at" not in canonical
    identity = dossier_content_identity(dossier)
    assert identity == _EXPECTED_DOSSIER_ID
    assert dossier_content_identity(dossier) == identity
    assert evidence_content_identities(dossier) == _EXPECTED_EVIDENCE_IDS
    assert dossier.candidate_comparison is not None
    assert dossier.candidate_comparison.strongest_simpler_boundary is not None
    changed_boundary = replace(
        dossier.candidate_comparison.strongest_simpler_boundary,
        scope="A changed represented-candidate scope.",
    )
    changed_dossier = replace(
        dossier,
        candidate_comparison=replace(
            dossier.candidate_comparison,
            strongest_simpler_boundary=changed_boundary,
        ),
    )
    assert dossier_content_identity(changed_dossier) != identity
    assert RULESET_VERSION == "1.10.0"


def test_minimal_dossier_emits_explicit_nulls_and_json_booleans_remain_boolean() -> None:
    minimal = Dossier(schema_version=1, case=CaseIdentity("minimal", "Minimal"))
    payload = canonical_dossier_dict(minimal)

    assert payload == {
        "schema_version": 1,
        "case": {"id": "minimal", "title": "Minimal"},
        "language": "en",
        "evidence": [],
        "task": None,
        "problem_value": None,
        "agency_necessity": None,
        "autonomy_permission": None,
        "candidate_comparison": None,
        "decision_conditions": [],
    }
    task = canonical_dossier_dict(full_dossier())["task"]
    assert isinstance(task, dict)
    assert task["actions"][0]["consequential"] is False
    assert task["actions"][1]["consequential"] is True


def test_golden_snapshot_is_itself_a_valid_schema_v1_dossier(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "case.yaml").write_bytes(_GOLDEN.read_bytes())

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier == full_dossier()


def test_full_fixture_exhausts_current_enum_values_and_dimensions() -> None:
    payload = canonical_dossier_dict(full_dossier())
    evidence = payload["evidence"]
    comparison = payload["candidate_comparison"]
    agency = payload["agency_necessity"]
    autonomy = payload["autonomy_permission"]
    assert isinstance(evidence, list)
    assert isinstance(comparison, dict)
    assert isinstance(agency, dict)
    assert isinstance(autonomy, dict)

    assert {item["kind"] for item in evidence if isinstance(item, dict)} == {
        "observed",
        "assumption",
        "estimate",
        "missing",
    }
    candidates = comparison["candidates"]
    assert isinstance(candidates, list)
    assert {item["control_class"] for item in candidates if isinstance(item, dict)} == {
        member.value for member in ControlClass
    }
    assert {
        role
        for item in candidates
        if isinstance(item, dict)
        for role in item["roles"]
        if isinstance(role, str)
    } == {member.value for member in CandidateRole}
    assert {
        test["result"]
        for item in candidates
        if isinstance(item, dict)
        for collection in (item["outcome_tests"], item["constraint_tests"])
        if isinstance(collection, list)
        for test in collection
        if isinstance(test, dict)
    } == {member.value for member in CandidateTestResult}
    assert {
        agency[name]["answer"]
        for name in (
            "execution_steps_predefinable",
            "step_count_or_order_predictable",
            "runtime_tool_choice_required",
            "runtime_replanning_required",
            "environmental_feedback_available",
            "completion_independently_verifiable",
            "effects_independently_verifiable",
            "fixed_workflow_sufficient",
        )
    } == {member.value for member in AgencyAnswer}
    assert {
        autonomy[name]["answer"]
        for name in (
            "actions_reversible",
            "failure_blast_radius_bounded",
            "regulatory_automation_permitted",
            "data_confidence_sufficient",
            "accountable_owner_assigned",
            "decision_path_auditable",
            "timely_human_intervention_available",
            "safe_degradation_available",
        )
    } == {member.value for member in AutonomyAnswer}
    assert {item["status"] for item in autonomy["hard_vetoes"]} == {
        member.value for member in HardVetoStatus
    }
    pair = comparison["comparisons"][0]
    assert set(pair["dimensions"]) == {
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
    }
    assert {item["result"] for item in pair["dimensions"].values()} == {
        member.value for member in ComparisonResult
    }


@pytest.mark.parametrize(
    ("evidence_index", "changes"),
    [
        (0, {"provenance": "changed provenance"}),
        (0, {"observed_at": date(2026, 8, 9)}),
        (1, {"falsified_by": "changed falsification"}),
        (2, {"method": "changed method"}),
        (3, {"resolved_by": "changed resolution"}),
    ],
)
def test_category_specific_evidence_fields_change_identity(
    evidence_index: int,
    changes: dict[str, object],
) -> None:
    entry = _evidence()[evidence_index]
    mutated = replace(entry, **changes)

    assert evidence_content_identity(mutated) != evidence_content_identity(entry)


def test_common_evidence_fields_and_order_are_complete() -> None:
    entry = _evidence()[0]
    original = evidence_content_identity(entry)
    for mutated in (
        replace(entry, id="changed"),
        replace(entry, claim="changed"),
        replace(entry, owner="changed"),
        replace(entry, affects=tuple(reversed(entry.affects))),
    ):
        assert evidence_content_identity(mutated) != original
    payload = canonical_evidence_dict(entry)
    assert payload["kind"] == "observed"
    assert payload["observed_at"] == "2026-08-08"
    assert canonical_evidence_bytes(entry).endswith(b"\n")


def test_represented_dossier_value_changes_bytes_and_identity() -> None:
    dossier = full_dossier()
    changed = replace(dossier, case=replace(dossier.case, title="Changed synthetic title"))

    assert canonical_dossier_bytes(changed) != canonical_dossier_bytes(dossier)
    assert dossier_content_identity(changed) != dossier_content_identity(dossier)


def test_authored_array_order_changes_dossier_but_not_entry_identities() -> None:
    dossier = full_dossier()
    reordered = replace(dossier, evidence=tuple(reversed(dossier.evidence)))

    assert canonical_dossier_bytes(reordered) != canonical_dossier_bytes(dossier)
    assert dossier_content_identity(reordered) != dossier_content_identity(dossier)
    assert evidence_content_identities(reordered) == evidence_content_identities(dossier)
    assert list(evidence_content_identities(reordered)) == [
        "assumption",
        "estimate",
        "missing",
        "observed",
    ]


def test_object_key_insertion_order_does_not_change_canonical_json() -> None:
    first = {"z": 1, "nested": {"b": True, "a": None}}
    second = {"nested": {"a": None, "b": True}, "z": 1}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first) == b'{"nested":{"a":null,"b":true},"z":1}\n'


def test_unicode_and_controls_are_escaped_without_terminal_interpretation() -> None:
    content = canonical_json_bytes({"text": "café\x1b\u202e"})

    assert content == b'{"text":"caf\\u00e9\\u001b\\u202e"}\n'
    assert b"\x1b" not in content
    assert "café" not in content.decode("ascii")
    assert json.loads(content) == {"text": "café\x1b\u202e"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.5, ("tuple",), object()])
def test_unsupported_json_values_fail_closed(value: object) -> None:
    with pytest.raises(CanonicalizationError, match="Unsupported value"):
        canonical_json_bytes(value)  # type: ignore[arg-type]


def test_duplicate_evidence_ids_fail_closed_without_last_write_wins() -> None:
    dossier = full_dossier()
    duplicate = replace(dossier.evidence[1], id=dossier.evidence[0].id)

    with pytest.raises(CanonicalizationError, match="Duplicate evidence IDs"):
        evidence_content_identities(replace(dossier, evidence=(dossier.evidence[0], duplicate)))


@dataclass(frozen=True, slots=True)
class _ExtendedDossier(Dossier):
    extension: str = "unsupported"


@dataclass(frozen=True, slots=True)
class _ExtendedAssumption(AssumptionEvidence):
    extension: str = "unsupported"


@dataclass(frozen=True, slots=True)
class _ExtendedDimensions(ComparisonDimensions):
    extension: ComparisonDimension | None = None


def test_evolved_or_unsupported_typed_shapes_fail_exhaustiveness_guards() -> None:
    dossier = full_dossier()
    with pytest.raises(CanonicalizationError, match="Dossier typed value"):
        canonical_dossier_dict(
            _ExtendedDossier(
                schema_version=1,
                case=dossier.case,
                evidence=dossier.evidence,
                task=dossier.task,
                problem_value=dossier.problem_value,
                agency_necessity=dossier.agency_necessity,
                autonomy_permission=dossier.autonomy_permission,
                candidate_comparison=dossier.candidate_comparison,
            )
        )
    with pytest.raises(CanonicalizationError, match="Unsupported evidence subtype"):
        canonical_evidence_dict(
            _ExtendedAssumption(
                "extended",
                "Synthetic claim.",
                "Synthetic owner",
                (DecisionArea.PROBLEM_VALUE,),
                "A falsifying observation.",
            )  # type: ignore[arg-type]
        )
    assert dossier.candidate_comparison is not None
    pair = dossier.candidate_comparison.comparisons[0]
    extended_pair = replace(
        pair,
        dimensions=_ExtendedDimensions(
            **{
                field: getattr(pair.dimensions, field)
                for field in (
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
            }
        ),
    )
    comparison = replace(dossier.candidate_comparison, comparisons=(extended_pair,))
    with pytest.raises(CanonicalizationError, match="ComparisonDimensions typed value"):
        canonical_dossier_dict(replace(dossier, candidate_comparison=comparison))


def test_unsupported_schema_and_wrong_enum_type_fail_closed() -> None:
    dossier = full_dossier()
    with pytest.raises(CanonicalizationError, match="schema version"):
        canonical_dossier_dict(replace(dossier, schema_version=4))
    assert dossier.agency_necessity is not None
    wrong_question = AgencyQuestion(
        AutonomyAnswer.YES,  # type: ignore[arg-type]
        "Wrong enum type.",
        ("observed",),
    )
    agency = replace(dossier.agency_necessity, execution_steps_predefinable=wrong_question)
    with pytest.raises(CanonicalizationError, match="AgencyAnswer value contract"):
        canonical_dossier_dict(replace(dossier, agency_necessity=agency))


@pytest.mark.parametrize(
    ("dossier", "message"),
    [
        (
            Dossier(schema_version=True, case=CaseIdentity("id", "title")),
            "Unsupported int typed value",
        ),
        (
            Dossier(schema_version=1, case=CaseIdentity(123, "title")),
            "Unsupported str typed value",
        ),
        (
            Dossier(
                schema_version=1,
                case=CaseIdentity("id", "title"),
                evidence=(
                    AssumptionEvidence(
                        "assumption",
                        "claim",
                        "owner",
                        (DecisionArea.PROBLEM_VALUE,),
                        falsified_by=123,
                    ),
                ),
            ),
            "Unsupported str typed value",
        ),
        (
            Dossier(
                schema_version=1,
                case=CaseIdentity("id", "title"),
                task=TaskBoundary(
                    operation="operation",
                    starts_when="starts",
                    completes_when="completes",
                    accountable_owner="owner",
                    actors=(),
                    systems_and_tools=(),
                    information_read=(),
                    actions=(object(),),
                    exclusions=(),
                ),
            ),
            "Unsupported TaskAction typed value",
        ),
        (
            Dossier(
                schema_version=1,
                case=CaseIdentity("id", "title"),
                task=TaskBoundary(
                    operation="operation",
                    starts_when="starts",
                    completes_when="completes",
                    accountable_owner="owner",
                    actors=(None,),
                    systems_and_tools=(),
                    information_read=(),
                    actions=(),
                    exclusions=(),
                ),
            ),
            "Unsupported str typed value",
        ),
    ],
)
def test_mis_typed_dossier_values_fail_closed_before_attribute_access(
    dossier: Dossier,
    message: str,
) -> None:
    with pytest.raises(CanonicalizationError, match=message):
        canonical_dossier_bytes(dossier)
    with pytest.raises(CanonicalizationError, match=message):
        canonical_dossier_dict(dossier)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            ObservedEvidence(
                "observed",
                "claim",
                "owner",
                (DecisionArea.PROBLEM_VALUE,),
                provenance="provenance",
                observed_at="2026-08-08",
            ),
            "canonical date",
        ),
        (
            AssumptionEvidence(
                "assumption",
                "claim",
                object(),
                (DecisionArea.PROBLEM_VALUE,),
                falsified_by="falsification",
            ),
            "Unsupported str typed value",
        ),
    ],
)
@pytest.mark.parametrize(
    "call",
    [canonical_evidence_bytes, canonical_evidence_dict, evidence_content_identity],
)
def test_malformed_evidence_entry_fails_closed_from_every_evidence_root(
    call: object,
    entry: Evidence,
    message: str,
) -> None:
    with pytest.raises(CanonicalizationError, match=message):
        call(entry)  # type: ignore[operator]


def test_optional_union_none_succeeds_but_nonoptional_union_rejects_none() -> None:
    minimal = Dossier(schema_version=1, case=CaseIdentity("id", "title"))
    canonical_dossier_bytes(minimal)

    with pytest.raises(CanonicalizationError, match="Unsupported None typed value"):
        canonical_evidence_dict(None)  # type: ignore[arg-type]


def test_tuple_subclass_containers_are_rejected_fail_closed() -> None:
    class _Actors(tuple):
        pass

    dossier = Dossier(
        schema_version=1,
        case=CaseIdentity("id", "title"),
        task=TaskBoundary(
            operation="operation",
            starts_when="starts",
            completes_when="completes",
            accountable_owner="owner",
            actors=_Actors(("Reviewer",)),
            systems_and_tools=(),
            information_read=(),
            actions=(),
            exclusions=(),
        ),
    )
    with pytest.raises(CanonicalizationError, match="Unsupported tuple typed value"):
        canonical_dossier_bytes(dossier)


def test_canonicalization_performs_no_io_and_does_not_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dossier = full_dossier()
    before = repr(dossier)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("canonicalization must not perform file I/O")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)

    assert dossier_content_identity(dossier).startswith("sha256:")
    assert evidence_content_identities(dossier)
    assert repr(dossier) == before


def test_hash_seed_locale_and_stream_encoding_do_not_change_output() -> None:
    script = """
import json
from archsift.canonical import (
    canonical_dossier_bytes,
    dossier_content_identity,
    evidence_content_identities,
)
from archsift.validation import AssumptionEvidence, CaseIdentity, DecisionArea, Dossier
entry = AssumptionEvidence(
    'evidence', 'café\\x1b', 'owner', (DecisionArea.PROBLEM_VALUE,), 'observe it'
)
dossier = Dossier(schema_version=1, case=CaseIdentity('case', 'café'), evidence=(entry,))
print(json.dumps({
    'bytes': canonical_dossier_bytes(dossier).hex(),
    'dossier': dossier_content_identity(dossier),
    'evidence': evidence_content_identities(dossier),
}, sort_keys=True))
"""
    outputs: list[str] = []
    for seed in ("1", "937"):
        environment = {
            **os.environ,
            "LC_ALL": "C",
            "PYTHONHASHSEED": seed,
            "PYTHONIOENCODING": "ascii:strict",
        }
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )
        outputs.append(completed.stdout)

    assert outputs[0] == outputs[1]
    payload = json.loads(outputs[0])
    assert payload["dossier"].startswith("sha256:")
    assert payload["evidence"]["evidence"].startswith("sha256:")


def test_every_identity_has_lowercase_sha256_shape() -> None:
    dossier = full_dossier()
    identities = [dossier_content_identity(dossier), *evidence_content_identities(dossier).values()]

    for identity in identities:
        algorithm, digest = identity.split(":", 1)
        assert algorithm == "sha256"
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(character in "0123456789abcdef" for character in digest)
