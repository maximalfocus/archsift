from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path

import pytest

from archsift.canonical import (
    CanonicalizationError,
    canonical_evidence_dict,
    dossier_content_identity,
    evidence_content_identities,
)
from archsift.decision import ArchitectureVerdict, EvidenceState, evaluate_assessment
from archsift.decision_record import (
    RECORD_SCHEMA_VERSION,
    DecisionGap,
    DecisionRecord,
    DecisionRecordError,
    EvidenceLink,
    PrerequisiteGap,
    canonical_decision_record_bytes,
    canonical_decision_record_dict,
    compose_decision_record,
)
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
    EvidencedStatement,
    EvidenceKind,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemConstraint,
    ProblemOutcome,
    ProblemValue,
    TaskAction,
    TaskBoundary,
)

_POSITIVE_GOLDEN = Path(__file__).parent / "golden" / "decision-record-positive-v1.json"
_INCOMPLETE_GOLDEN = Path(__file__).parent / "golden" / "decision-record-incomplete-v1.json"
_TOOL_VERSION = "0.1.0-test"


def _observed(identifier: str, area: DecisionArea) -> ObservedEvidence:
    return ObservedEvidence(
        identifier,
        f"Synthetic {area.value} observation.",
        "Synthetic reviewer",
        (area,),
        provenance=f"evidence/{identifier}.txt",
        observed_at=date(2026, 8, 8),
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
                ("decision-observed",),
            ),
        ),
        baselines=(
            ProblemBaseline(
                "quality-baseline",
                "Current synthetic quality.",
                "Accepted cases",
                "90 percent",
                ("decision-observed",),
            ),
        ),
        constraints=(
            ProblemConstraint(
                "approval",
                "Approval is required.",
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
            "Current tooling is constrained.",
            ("decision-observed",),
        ),
    )


def _task() -> TaskBoundary:
    return TaskBoundary(
        operation="Review one bounded synthetic case.",
        starts_when="A complete request arrives.",
        completes_when="An approved disposition is recorded.",
        accountable_owner="Synthetic owner",
        actors=("Reviewer", "Approver"),
        systems_and_tools=("Case register",),
        information_read=("Synthetic request",),
        actions=(
            TaskAction(
                "release",
                "Release the disposition.",
                True,
                "An approver must approve release.",
            ),
        ),
        exclusions=("Changing policy",),
    )


def _agency() -> AgencyNecessity:
    def question(answer: AgencyAnswer) -> AgencyQuestion:
        return AgencyQuestion(answer, "Synthetic agency rationale.", ("agency-observed",))

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
        return AutonomyQuestion(answer, "Synthetic autonomy rationale.", ("autonomy-observed",))

    return AutonomyPermission(
        actions_reversible=question(AutonomyAnswer.YES),
        failure_blast_radius_bounded=question(AutonomyAnswer.YES),
        regulatory_automation_permitted=question(AutonomyAnswer.YES),
        data_confidence_sufficient=question(AutonomyAnswer.YES),
        accountable_owner_assigned=question(AutonomyAnswer.YES),
        decision_path_auditable=question(AutonomyAnswer.YES),
        timely_human_intervention_available=question(AutonomyAnswer.YES),
        safe_degradation_available=question(AutonomyAnswer.YES),
        hard_vetoes=(
            HardVeto(
                "review-before-release",
                HardVetoStatus.ACTIVE,
                "Release lacks review.",
                "Release is prohibited until review completes.",
                ("release",),
                ("autonomy-observed",),
            ),
        ),
        mandatory_human_controls=(
            MandatoryHumanControl(
                "approve-release",
                "Approve before release.",
                "Immediately before release.",
                "Approver",
                ("release",),
                ("autonomy-observed",),
            ),
        ),
    )


def _candidate(
    identifier: str,
    control_class: ControlClass,
    role: CandidateRole,
    result: CandidateTestResult,
) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Synthetic {identifier}",
        description=f"Synthetic {control_class.value} candidate.",
        control_class=control_class,
        roles=(role,),
        material_deviations=(),
        outcome_tests=(
            CandidateOutcomeTest(
                "quality",
                result,
                f"Synthetic quality result for {identifier}.",
                ("decision-observed",),
            ),
        ),
        constraint_tests=(
            CandidateConstraintTest(
                "approval",
                CandidateTestResult.MEETS,
                f"Synthetic approval result for {identifier}.",
                ("decision-observed",),
            ),
        ),
    )


def _dimensions() -> ComparisonDimensions:
    dimension = ComparisonDimension(
        ComparisonResult.EQUIVALENT,
        "Synthetic directional comparison.",
        ("decision-observed",),
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


def positive_dossier() -> Dossier:
    human = _candidate(
        "human",
        ControlClass.HUMAN_OWNED_WORK,
        CandidateRole.CURRENT_BASELINE,
        CandidateTestResult.FAILS,
    )
    deterministic = _candidate(
        "deterministic",
        ControlClass.DETERMINISTIC_AUTOMATION,
        CandidateRole.STRONGEST_SIMPLER,
        CandidateTestResult.FAILS,
    )
    fixed = _candidate(
        "fixed",
        ControlClass.FIXED_AI_WORKFLOW,
        CandidateRole.PROPOSED,
        CandidateTestResult.MEETS,
    )
    return Dossier(
        schema_version=1,
        case=CaseIdentity("decision-record", "Decision record café \u202e synthetic"),
        evidence=(
            replace(
                _observed("decision-observed", DecisionArea.COMPARATIVE_FIT),
                affects=(DecisionArea.PROBLEM_VALUE, DecisionArea.COMPARATIVE_FIT),
            ),
            _observed("agency-observed", DecisionArea.AGENCY_NECESSITY),
            _observed("autonomy-observed", DecisionArea.AUTONOMY_PERMISSION),
            _observed("condition-observed", DecisionArea.COMPARATIVE_FIT),
            AssumptionEvidence(
                "a-assumption",
                "A synthetic bounded assumption.\x1b",
                "Synthetic reviewer",
                (DecisionArea.COMPARATIVE_FIT,),
                falsified_by="A controlled synthetic observation disproves it.",
            ),
            MissingEvidence(
                "z-missing",
                "A synthetic non-material gap.",
                "Synthetic reviewer",
                (DecisionArea.COMPARATIVE_FIT,),
                resolved_by="Run the named synthetic observation.",
            ),
        ),
        task=_task(),
        problem_value=_problem(),
        agency_necessity=_agency(),
        autonomy_permission=_autonomy(),
        candidate_comparison=CandidateComparison(
            (human, deterministic, fixed),
            (
                CandidatePairComparison("deterministic", "human", _dimensions()),
                CandidatePairComparison("fixed", "deterministic", _dimensions()),
                CandidatePairComparison("fixed", "human", _dimensions()),
            ),
        ),
        decision_conditions=(
            DecisionCondition(
                "verify-capacity",
                ControlClass.FIXED_AI_WORKFLOW,
                DecisionArea.COMPARATIVE_FIT,
                "Verify production capacity before adoption.\x1b",
                DecisionConditionStatus.UNMET,
                "Run the named production-capacity test.",
                ("condition-observed",),
            ),
        ),
    )


def incomplete_dossier() -> Dossier:
    return Dossier(
        schema_version=1,
        case=CaseIdentity("incomplete", "Incomplete synthetic record"),
        evidence=(
            MissingEvidence(
                "a-missing",
                "A required observation is missing.",
                "Synthetic reviewer",
                (DecisionArea.PROBLEM_VALUE,),
                resolved_by="Run the required synthetic observation.",
            ),
            AssumptionEvidence(
                "z-assumption",
                "A synthetic assumption remains untested.",
                "Synthetic reviewer",
                (DecisionArea.PROBLEM_VALUE,),
                falsified_by="A controlled trial disproves the assumption.",
            ),
        ),
    )


def test_positive_record_matches_exact_golden_and_existing_evaluation() -> None:
    dossier = positive_dossier()
    record = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    content = canonical_decision_record_bytes(record)
    payload = canonical_decision_record_dict(record)

    assert content == _POSITIVE_GOLDEN.read_bytes()
    assert json.loads(content) == payload
    assert record.record_schema_version == RECORD_SCHEMA_VERSION == 1
    assert record.dossier_schema_version == dossier.schema_version
    assert record.dossier_content_identity == dossier_content_identity(dossier)
    assert record.ruleset_version == RULESET_VERSION == "1.4.0"
    assert record.assessment == evaluate_assessment(dossier)
    assert payload["assessment"] == record.assessment.to_dict()
    assert record.assessment.verdict is ArchitectureVerdict.CONDITIONAL
    assert record.assessment.evidence_state is EvidenceState.COMPLETE
    assert [condition.id for condition in record.assessment.unmet_conditions] == ["verify-capacity"]
    assert record.assessment.recommended_class is ControlClass.FIXED_AI_WORKFLOW
    assert record.assessment.active_hard_veto_ids == ("review-before-release",)
    assert record.assessment.mandatory_human_control_ids == ("approve-release",)
    assert record.unresolved_gaps == ()
    assert [
        (trigger.evidence_id, trigger.kind, trigger.observation)
        for trigger in record.reassessment_triggers
    ] == [
        (
            "a-assumption",
            EvidenceKind.ASSUMPTION,
            "A controlled synthetic observation disproves it.",
        ),
        (
            "z-missing",
            EvidenceKind.MISSING,
            "Run the named synthetic observation.",
        ),
    ]
    assert list(payload["evidence_links"]) == sorted(evidence_content_identities(dossier))
    assert "condition-observed" in payload["evidence_links"]
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert b"\x1b" not in content
    assert b"datetime.date" not in content
    assert b"<object at" not in content


def test_incomplete_record_matches_exact_golden_with_structured_gaps() -> None:
    dossier = incomplete_dossier()
    record = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    content = canonical_decision_record_bytes(record)

    assert content == _INCOMPLETE_GOLDEN.read_bytes()
    assert json.loads(content) == canonical_decision_record_dict(record)
    assert record.assessment.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert record.assessment.evidence_state is EvidenceState.INCOMPLETE
    assert [gap.rule_id for gap in record.unresolved_gaps] == [
        "task-boundary-missing",
        "problem-value-missing",
        "agency-necessity-missing",
        "autonomy-permission-missing",
        "candidate-comparison-missing",
    ]
    assert all(type(gap) is PrerequisiteGap for gap in record.unresolved_gaps)
    assert [trigger.evidence_id for trigger in record.reassessment_triggers] == [
        "a-missing",
        "z-assumption",
    ]


def test_record_is_deeply_immutable_at_the_typed_boundary() -> None:
    record = compose_decision_record(positive_dossier(), tool_version=_TOOL_VERSION)

    with pytest.raises(FrozenInstanceError):
        record.tool_version = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.evidence_links[0].content_identity = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.dossier.evidence[0] = record.dossier.evidence[0]  # type: ignore[index]


@pytest.mark.parametrize(
    "tool_version",
    ["", "   ", None, 1, True],
)
def test_tool_version_must_be_explicit_non_empty_text(tool_version: object) -> None:
    with pytest.raises(DecisionRecordError, match="explicit non-empty tool version"):
        compose_decision_record(
            incomplete_dossier(),
            tool_version=tool_version,  # type: ignore[arg-type]
        )


def test_every_evidence_link_uses_the_landed_identity_and_canonical_id_order() -> None:
    dossier = positive_dossier()
    record = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    identities = evidence_content_identities(dossier)

    assert [link.evidence_id for link in record.evidence_links] == sorted(identities)
    for link in record.evidence_links:
        entry = next(item for item in dossier.evidence if item.id == link.evidence_id)
        assert link.kind.value == canonical_evidence_dict(entry)["kind"]
        assert link.content_identity == identities[link.evidence_id]


def test_ledger_reordering_changes_authored_dossier_bytes_but_not_evidence_links() -> None:
    dossier = positive_dossier()
    reordered = replace(dossier, evidence=tuple(reversed(dossier.evidence)))
    original = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    changed = compose_decision_record(reordered, tool_version=_TOOL_VERSION)

    assert original.evidence_links == changed.evidence_links
    assert original.reassessment_triggers == changed.reassessment_triggers
    assert original.dossier_content_identity != changed.dossier_content_identity
    assert canonical_decision_record_bytes(original) != canonical_decision_record_bytes(changed)


def test_dangling_evidence_citations_fail_closed_at_arbitrary_nested_depth() -> None:
    dossier = positive_dossier()
    assert dossier.candidate_comparison is not None
    pair = dossier.candidate_comparison.comparisons[0]
    changed_dimension = replace(
        pair.dimensions.cost,
        evidence_ids=("absent-evidence",),
    )
    changed_dimensions = replace(pair.dimensions, cost=changed_dimension)
    changed_pair = replace(pair, dimensions=changed_dimensions)
    comparison = replace(
        dossier.candidate_comparison,
        comparisons=(changed_pair, *dossier.candidate_comparison.comparisons[1:]),
    )

    with pytest.raises(DecisionRecordError, match="'absent-evidence'"):
        compose_decision_record(
            replace(dossier, candidate_comparison=comparison),
            tool_version=_TOOL_VERSION,
        )


def test_undetermined_decision_findings_remain_structured_and_evidence_traced() -> None:
    dossier = positive_dossier()
    assert dossier.candidate_comparison is not None
    human = dossier.candidate_comparison.candidates[0]
    unknown_test = replace(
        human.outcome_tests[0],
        result=CandidateTestResult.UNKNOWN,
        evidence_ids=("z-missing",),
    )
    changed_human = replace(human, outcome_tests=(unknown_test,))
    comparison = replace(
        dossier.candidate_comparison,
        candidates=(changed_human, *dossier.candidate_comparison.candidates[1:]),
    )

    record = compose_decision_record(
        replace(dossier, candidate_comparison=comparison),
        tool_version=_TOOL_VERSION,
    )
    decision_gaps = [gap for gap in record.unresolved_gaps if type(gap) is DecisionGap]

    assert record.assessment.verdict is ArchitectureVerdict.INSUFFICIENT_EVIDENCE
    assert len(decision_gaps) == 1
    assert decision_gaps[0].rule_id == "candidate-test-result-unknown"
    assert decision_gaps[0].candidate_id == "human"
    assert decision_gaps[0].criterion_id == "quality"
    assert decision_gaps[0].evidence_ids == ("z-missing",)


def test_duplicate_evidence_ids_fail_closed_without_overwriting_links() -> None:
    dossier = positive_dossier()
    duplicate = replace(dossier.evidence[1], id=dossier.evidence[0].id)

    with pytest.raises(CanonicalizationError, match="Duplicate evidence IDs"):
        compose_decision_record(
            replace(dossier, evidence=(dossier.evidence[0], duplicate)),
            tool_version=_TOOL_VERSION,
        )


def test_stale_or_mutated_record_components_fail_consistency_checks() -> None:
    record = compose_decision_record(positive_dossier(), tool_version=_TOOL_VERSION)
    incomplete = compose_decision_record(incomplete_dossier(), tool_version=_TOOL_VERSION)
    stale_prerequisites = replace(
        record.assessment.prerequisite_evaluation,
        ruleset_version="stale",
    )
    mutations = (
        (replace(record, record_schema_version=2), "record schema version"),
        (replace(record, dossier_schema_version=2), "dossier schema version"),
        (
            replace(record, dossier_content_identity="sha256:" + "0" * 64),
            "dossier identity",
        ),
        (replace(record, ruleset_version="stale"), "ruleset versions"),
        (
            replace(
                record,
                assessment=replace(record.assessment, schema_version=2),
            ),
            "assessment schema version",
        ),
        (
            replace(
                record,
                assessment=replace(
                    record.assessment,
                    schema_version=True,
                ),
            ),
            "assessment schema version",
        ),
        (
            replace(
                record,
                assessment=replace(
                    record.assessment,
                    prerequisite_evaluation=stale_prerequisites,
                ),
            ),
            "ruleset versions",
        ),
        (
            replace(
                record,
                assessment=replace(
                    record.assessment,
                    verdict=ArchitectureVerdict.NO_TECHNOLOGY_CHANGE,
                ),
            ),
            "assessment",
        ),
        (replace(record, evidence_links=()), "evidence links"),
        (
            replace(record, unresolved_gaps=(incomplete.unresolved_gaps[0],)),
            "unresolved gaps",
        ),
        (replace(record, reassessment_triggers=()), "reassessment triggers"),
    )

    for mutation, message in mutations:
        with pytest.raises(DecisionRecordError, match=message):
            canonical_decision_record_dict(mutation)


def test_exact_scalar_guards_reject_equality_twins_through_dict_and_bytes() -> None:
    dossier = positive_dossier()
    record = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    incomplete = compose_decision_record(incomplete_dossier(), tool_version=_TOOL_VERSION)

    def twin(value: str) -> StrEnum:
        return StrEnum("Twin", {"VALUE": value})["VALUE"]

    assessment = record.assessment
    elimination = assessment.ordered_elimination_evaluation
    prerequisites = assessment.prerequisite_evaluation
    finding = elimination.findings[0]
    links = record.evidence_links
    triggers = record.reassessment_triggers
    incomplete_assessment = incomplete.assessment
    incomplete_prerequisites = incomplete_assessment.prerequisite_evaluation
    prerequisite_finding = incomplete_prerequisites.findings[0]
    prerequisite_gap = incomplete.unresolved_gaps[0]

    def assert_twin_rejected(mutated: DecisionRecord) -> None:
        for canonicalize in (canonical_decision_record_dict, canonical_decision_record_bytes):
            with pytest.raises(DecisionRecordError, match="must be text"):
                canonicalize(mutated)

    cases = (
        (
            "assessment ruleset_version",
            replace(
                record,
                assessment=replace(assessment, ruleset_version=twin("1.4.0")),
            ),
        ),
        (
            "assessment verdict_rule_id",
            replace(
                record,
                assessment=replace(assessment, verdict_rule_id=twin(assessment.verdict_rule_id)),
            ),
        ),
        (
            "prerequisite ruleset_version",
            replace(
                record,
                assessment=replace(
                    assessment,
                    prerequisite_evaluation=replace(
                        prerequisites,
                        ruleset_version=twin("1.4.0"),
                    ),
                ),
            ),
        ),
        (
            "ordered-elimination ruleset_version",
            replace(
                record,
                assessment=replace(
                    assessment,
                    ordered_elimination_evaluation=replace(
                        elimination,
                        ruleset_version=twin("1.4.0"),
                    ),
                ),
            ),
        ),
        (
            "candidate-elimination candidate_id",
            replace(
                record,
                assessment=replace(
                    assessment,
                    ordered_elimination_evaluation=replace(
                        elimination,
                        candidates=(
                            replace(elimination.candidates[0], candidate_id=twin("human")),
                            *elimination.candidates[1:],
                        ),
                    ),
                ),
            ),
        ),
        (
            "decision-finding message",
            replace(
                record,
                assessment=replace(
                    assessment,
                    ordered_elimination_evaluation=replace(
                        elimination,
                        findings=(
                            replace(finding, message=twin(finding.message)),
                            *elimination.findings[1:],
                        ),
                    ),
                ),
            ),
        ),
        (
            "prerequisite-finding field",
            replace(
                incomplete,
                assessment=replace(
                    incomplete_assessment,
                    prerequisite_evaluation=replace(
                        incomplete_prerequisites,
                        findings=(
                            replace(
                                prerequisite_finding,
                                field=twin(prerequisite_finding.field),
                            ),
                            *incomplete_prerequisites.findings[1:],
                        ),
                    ),
                ),
            ),
        ),
        (
            "prerequisite-gap rule_id",
            replace(
                incomplete,
                unresolved_gaps=(
                    replace(prerequisite_gap, rule_id=twin(prerequisite_gap.rule_id)),
                    *incomplete.unresolved_gaps[1:],
                ),
            ),
        ),
        (
            "evidence-link evidence_id",
            replace(
                record,
                evidence_links=(
                    replace(links[0], evidence_id=twin(links[0].evidence_id)),
                    *links[1:],
                ),
            ),
        ),
        (
            "evidence-link content_identity",
            replace(
                record,
                evidence_links=(
                    replace(links[0], content_identity=twin(links[0].content_identity)),
                    *links[1:],
                ),
            ),
        ),
        (
            "reassessment-trigger observation",
            replace(
                record,
                reassessment_triggers=(
                    replace(triggers[0], observation=twin(triggers[0].observation)),
                    *triggers[1:],
                ),
            ),
        ),
    )
    for _label, mutated in cases:
        assert_twin_rejected(mutated)

    assert dossier.candidate_comparison is not None
    human = dossier.candidate_comparison.candidates[0]
    unknown_test = replace(
        human.outcome_tests[0],
        result=CandidateTestResult.UNKNOWN,
        evidence_ids=("z-missing",),
    )
    changed_human = replace(human, outcome_tests=(unknown_test,))
    comparison = replace(
        dossier.candidate_comparison,
        candidates=(changed_human, *dossier.candidate_comparison.candidates[1:]),
    )
    decision_record = compose_decision_record(
        replace(dossier, candidate_comparison=comparison),
        tool_version=_TOOL_VERSION,
    )
    decision_gap = next(gap for gap in decision_record.unresolved_gaps if type(gap) is DecisionGap)
    index = decision_record.unresolved_gaps.index(decision_gap)
    twin_gaps = (
        *decision_record.unresolved_gaps[:index],
        replace(decision_gap, criterion_id=twin(decision_gap.criterion_id)),
        *decision_record.unresolved_gaps[index + 1 :],
    )
    assert_twin_rejected(replace(decision_record, unresolved_gaps=twin_gaps))

    for bad_schema in (True, 1.0):
        mutated = replace(
            record,
            assessment=replace(assessment, schema_version=bad_schema),
        )
        for canonicalize in (canonical_decision_record_dict, canonical_decision_record_bytes):
            with pytest.raises(DecisionRecordError, match="schema version"):
                canonicalize(mutated)


def test_malformed_nested_assessment_containers_fail_with_domain_error() -> None:
    record = compose_decision_record(positive_dossier(), tool_version=_TOOL_VERSION)
    malformed_elimination = replace(
        record.assessment.ordered_elimination_evaluation,
        candidates=None,
    )
    malformed_assessment = replace(
        record.assessment,
        ordered_elimination_evaluation=malformed_elimination,
    )

    with pytest.raises(DecisionRecordError, match="immutable tuple"):
        canonical_decision_record_dict(replace(record, assessment=malformed_assessment))


@dataclass(frozen=True, slots=True)
class _ExtendedRecord(DecisionRecord):
    extension: str = "unsupported"


@dataclass(frozen=True, slots=True)
class _ExtendedLink(EvidenceLink):
    extension: str = "unsupported"


def test_evolved_record_and_link_shapes_fail_exhaustiveness_guards() -> None:
    record = compose_decision_record(positive_dossier(), tool_version=_TOOL_VERSION)
    extended_record = _ExtendedRecord(
        record_schema_version=record.record_schema_version,
        dossier_schema_version=record.dossier_schema_version,
        dossier_content_identity=record.dossier_content_identity,
        ruleset_version=record.ruleset_version,
        tool_version=record.tool_version,
        dossier=record.dossier,
        assessment=record.assessment,
        evidence_links=record.evidence_links,
        unresolved_gaps=record.unresolved_gaps,
        reassessment_triggers=record.reassessment_triggers,
    )
    with pytest.raises(DecisionRecordError, match="DecisionRecord typed value"):
        canonical_decision_record_dict(extended_record)

    extended_link = _ExtendedLink(
        evidence_id=record.evidence_links[0].evidence_id,
        kind=record.evidence_links[0].kind,
        content_identity=record.evidence_links[0].content_identity,
    )
    with pytest.raises(DecisionRecordError, match="evidence links are inconsistent"):
        canonical_decision_record_dict(
            replace(record, evidence_links=(extended_link, *record.evidence_links[1:]))
        )


def test_malformed_or_stale_nested_conditions_fail_closed() -> None:
    record = compose_decision_record(positive_dossier(), tool_version=_TOOL_VERSION)
    condition = record.assessment.unmet_conditions[0]

    malformed = replace(
        record,
        assessment=replace(
            record.assessment,
            unmet_conditions=(replace(condition, statement=1),),  # type: ignore[arg-type]
        ),
    )
    stale = replace(
        record,
        assessment=replace(
            record.assessment,
            unmet_conditions=(replace(condition, id="stale-condition"),),
        ),
    )

    with pytest.raises(DecisionRecordError, match="statement must be text"):
        canonical_decision_record_bytes(malformed)
    with pytest.raises(DecisionRecordError, match="assessment is inconsistent"):
        canonical_decision_record_bytes(stale)


def test_composition_performs_no_io_environment_clock_randomness_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dossier = positive_dossier()
    before = repr(dossier)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("decision-record composition must remain pure")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr("time.time", forbidden)
    monkeypatch.setattr("random.random", forbidden)
    monkeypatch.setattr("importlib.metadata.version", forbidden)

    record = compose_decision_record(dossier, tool_version=_TOOL_VERSION)

    assert record.assessment.verdict is ArchitectureVerdict.CONDITIONAL
    assert repr(dossier) == before


def test_hash_seed_locale_and_stream_encoding_do_not_change_record_bytes() -> None:
    script = """
import json
from archsift.decision_record import canonical_decision_record_bytes, compose_decision_record
from archsift.validation import AssumptionEvidence, CaseIdentity, DecisionArea, Dossier
entry = AssumptionEvidence(
    'evidence', 'café\\x1b', 'owner', (DecisionArea.PROBLEM_VALUE,), 'observe it'
)
dossier = Dossier(schema_version=1, case=CaseIdentity('case', 'café'), evidence=(entry,))
record = compose_decision_record(dossier, tool_version='0.1.0-test')
print(json.dumps({'bytes': canonical_decision_record_bytes(record).hex()}, sort_keys=True))
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
    assert json.loads(outputs[0])["bytes"].endswith("0a")


def test_represented_changes_affect_record_bytes_without_a_record_identity_claim() -> None:
    dossier = positive_dossier()
    original = compose_decision_record(dossier, tool_version=_TOOL_VERSION)
    changed_tool = compose_decision_record(dossier, tool_version="0.1.1-test")
    changed_case = compose_decision_record(
        replace(dossier, case=replace(dossier.case, title="Changed synthetic title")),
        tool_version=_TOOL_VERSION,
    )

    assert canonical_decision_record_bytes(original) != canonical_decision_record_bytes(
        changed_tool
    )
    assert canonical_decision_record_bytes(original) != canonical_decision_record_bytes(
        changed_case
    )
    assert "record_content_identity" not in canonical_decision_record_dict(original)
