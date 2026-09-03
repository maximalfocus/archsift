from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest

from archsift.artefacts import EvidenceArtefactIdentity
from archsift.decision import ArchitectureVerdict
from archsift.decision_record import DecisionRecord, compose_decision_record
from archsift.markdown_report import MarkdownReportError, render_markdown_decision_report
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
    EvidenceArtefactReference,
    EvidenceArtefactRoot,
    EvidencedStatement,
    HardVeto,
    HardVetoStatus,
    MandatoryHumanControl,
    MissingEvidence,
    ObservedEvidence,
    ProblemBaseline,
    ProblemOutcome,
    ProblemValue,
    StrongestSimplerBoundary,
    TaskAction,
    TaskBoundary,
)

_INCOMPLETE_GOLDEN = Path(__file__).parent / "golden" / "decision-report-incomplete-v5.md"


def _question(answer: AgencyAnswer = AgencyAnswer.YES) -> AgencyQuestion:
    return AgencyQuestion(answer, "Synthetic agency rationale.", ("observed",))


def _autonomy_question(answer: AutonomyAnswer = AutonomyAnswer.YES) -> AutonomyQuestion:
    return AutonomyQuestion(answer, "Synthetic autonomy rationale.", ("observed",))


def _dimensions() -> ComparisonDimensions:
    dimension = ComparisonDimension(
        ComparisonResult.EQUIVALENT,
        "Synthetic directional trade-off.",
        ("observed",),
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


def _candidate(
    identifier: str,
    control_class: ControlClass,
    roles: tuple[CandidateRole, ...],
    result: CandidateTestResult,
) -> Candidate:
    return Candidate(
        id=identifier,
        name=f"Synthetic {identifier}",
        description=f"Synthetic {control_class.value} candidate.",
        control_class=control_class,
        roles=roles,
        material_deviations=("One synthetic deviation.",),
        outcome_tests=(
            CandidateOutcomeTest(
                "quality",
                result,
                f"Synthetic quality result for {identifier}.",
                ("observed",),
            ),
        ),
        constraint_tests=(),
    )


def _positive_dossier() -> Dossier:
    evidence = ObservedEvidence(
        "observed",
        "A synthetic observation supports every represented decision area.",
        "Synthetic reviewer",
        tuple(DecisionArea),
        provenance="evidence/synthetic.txt",
        observed_at=date(2026, 8, 8),
    )
    human = _candidate(
        "human",
        ControlClass.HUMAN_OWNED_WORK,
        (CandidateRole.CURRENT_BASELINE, CandidateRole.STRONGEST_SIMPLER),
        CandidateTestResult.FAILS,
    )
    process = _candidate(
        "process",
        ControlClass.PROCESS_REDESIGN,
        (CandidateRole.PROPOSED,),
        CandidateTestResult.MEETS,
    )
    return Dossier(
        schema_version=1,
        case=CaseIdentity("report-positive", "Synthetic positive report"),
        evidence=(
            evidence,
            AssumptionEvidence(
                "assumption",
                "A synthetic assumption remains visible.",
                "Synthetic reviewer",
                (DecisionArea.COMPARATIVE_FIT,),
                falsified_by="Run the named synthetic falsification observation.",
            ),
            MissingEvidence(
                "missing",
                "A non-material synthetic gap remains visible.",
                "Synthetic reviewer",
                (DecisionArea.COMPARATIVE_FIT,),
                resolved_by="Run the named synthetic resolution observation.",
            ),
        ),
        task=TaskBoundary(
            operation="Review one synthetic request.",
            starts_when="A complete request arrives.",
            completes_when="A disposition is recorded.",
            accountable_owner="Synthetic owner",
            actors=("Reviewer",),
            systems_and_tools=("Case register",),
            information_read=("Synthetic request",),
            actions=(
                TaskAction(
                    "record",
                    "Record the disposition.",
                    False,
                    "The reviewer may record it.",
                ),
            ),
            exclusions=("Changing policy",),
        ),
        problem_value=ProblemValue(
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
            ),
            baselines=(
                ProblemBaseline(
                    "quality-baseline",
                    "Current synthetic quality.",
                    "Accepted cases",
                    "90 percent",
                    ("observed",),
                ),
            ),
            constraints=(),
            affected_volume=EvidencedStatement("Material volume.", ("observed",)),
            material_pain=EvidencedStatement("Material delay.", ("observed",)),
            error_cost=EvidencedStatement("Material rework.", ("observed",)),
            technology_limitation=EvidencedStatement(
                "Current tooling is constrained.", ("observed",)
            ),
        ),
        agency_necessity=AgencyNecessity(
            execution_steps_predefinable=_question(),
            step_count_or_order_predictable=_question(),
            runtime_tool_choice_required=_question(AgencyAnswer.NO),
            runtime_replanning_required=_question(AgencyAnswer.NO),
            environmental_feedback_available=_question(),
            completion_independently_verifiable=_question(),
            effects_independently_verifiable=_question(),
            fixed_workflow_sufficient=_question(),
            residual_cases=(),
        ),
        autonomy_permission=AutonomyPermission(
            actions_reversible=_autonomy_question(),
            failure_blast_radius_bounded=_autonomy_question(),
            regulatory_automation_permitted=_autonomy_question(),
            data_confidence_sufficient=_autonomy_question(),
            accountable_owner_assigned=_autonomy_question(),
            decision_path_auditable=_autonomy_question(),
            timely_human_intervention_available=_autonomy_question(),
            safe_degradation_available=_autonomy_question(),
            hard_vetoes=(
                HardVeto(
                    "review-before-record",
                    HardVetoStatus.ACTIVE,
                    "Recording lacks review.",
                    "Recording is prohibited until review completes.",
                    ("record",),
                    ("observed",),
                ),
            ),
            mandatory_human_controls=(
                MandatoryHumanControl(
                    "approve-record",
                    "Approve before recording.",
                    "Immediately before recording.",
                    "Reviewer",
                    ("record",),
                    ("observed",),
                ),
            ),
        ),
        candidate_comparison=CandidateComparison(
            candidates=(human, process),
            comparisons=(CandidatePairComparison("process", "human", _dimensions()),),
            strongest_simpler_boundary=StrongestSimplerBoundary(
                strongest_candidate_id="human",
                scope="All represented candidates below process redesign.",
                rationale="Human-owned work is the strongest represented simpler option.",
                considered_candidate_ids=("human",),
                evidence_ids=("observed",),
            ),
        ),
        decision_conditions=(
            DecisionCondition(
                "retain-review",
                ControlClass.PROCESS_REDESIGN,
                DecisionArea.COMPARATIVE_FIT,
                "Retain synthetic review.",
                DecisionConditionStatus.MET,
                "Observe the review control operating.",
                ("observed",),
            ),
        ),
    )


def _positive_record() -> DecisionRecord:
    dossier = _positive_dossier()
    observed = dossier.evidence[0]
    assert isinstance(observed, ObservedEvidence)
    observed = replace(
        observed,
        artefacts=(
            EvidenceArtefactReference("source", EvidenceArtefactRoot.WORKSPACE, "synthetic.bin"),
        ),
    )
    return compose_decision_record(
        replace(dossier, evidence=(observed, *dossier.evidence[1:])),
        tool_version="0.1.0-test",
        artefact_identities=(
            EvidenceArtefactIdentity(
                "observed",
                "source",
                EvidenceArtefactRoot.WORKSPACE,
                "synthetic.bin",
                3,
                f"sha256:{'0' * 64}",
            ),
        ),
    )


def _incomplete_record() -> DecisionRecord:
    return compose_decision_record(
        Dossier(schema_version=1, case=CaseIdentity("incomplete", "Synthetic incomplete")),
        tool_version="0.1.0-test",
    )


def test_incomplete_report_matches_exact_golden_and_marks_absent_sections() -> None:
    content = render_markdown_decision_report(_incomplete_record())

    assert content == _INCOMPLETE_GOLDEN.read_bytes()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert b"\r" not in content
    text = content.decode("utf-8")
    assert text.count("(not provided)") >= 5
    assert "## Task Boundary" in text
    assert "### Problem Value" in text
    assert "### Agency Necessity" in text
    assert "### Autonomy Permission" in text
    assert "### Comparative Fit" in text
    assert "insufficient-evidence" in text
    assert "(abstention)" in text


def test_golden_report_is_pinned_to_lf_line_endings_on_every_platform() -> None:
    attributes = Path(__file__).parent.parent / ".gitattributes"
    assert "tests/golden/*.md text eol=lf" in attributes.read_text(encoding="utf-8")


def test_positive_report_covers_the_decision_and_trade_off_trace() -> None:
    record = _positive_record()
    content = render_markdown_decision_report(record)
    text = content.decode("utf-8")

    assert record.assessment.verdict is ArchitectureVerdict.NO_TECHNOLOGY_CHANGE
    for expected in (
        "# ArchSift Decision Report",
        "## Record Metadata",
        "## Case Identity",
        "## Task Boundary",
        "## Evidence Ledger",
        "## Decision Areas",
        "Candidate Comparison and Trade-offs",
        "## Verdict and Recommendation",
        "## Assessment Trace",
        "## Evidence Identities",
        "## Artefact Identities",
        "## Unresolved Gaps",
        "## Reassessment Triggers",
        record.record_content_identity,
        "verdict-no-technology-change",
        "process-redesign",
        "binding-outcome-met",
        "Synthetic directional trade-off.",
        "evidence/synthetic.txt",
        "review-before-record",
        "approve-record",
        "retain-review",
        "synthetic.bin",
        "Run the named synthetic falsification observation.",
        "Run the named synthetic resolution observation.",
    ):
        assert expected in text


def test_authored_markdown_and_controls_stay_in_one_inert_visible_code_line() -> None:
    hostile = (
        "# forged heading\n| forged | table |\n> quote\n- finding\n"
        "[link](https://example.invalid) ![image](x) <https://example.invalid>\n"
        "<script>alert(1)</script> ``` [ref]: https://example.invalid\\tail"
        "\x00\x1b\x85\u200b\u2028\u202e café"
    )
    dossier = _positive_dossier()
    evidence = replace(dossier.evidence[0], claim=hostile, provenance=hostile)
    task = replace(dossier.task, operation=hostile) if dossier.task is not None else None
    comparison = dossier.candidate_comparison
    assert comparison is not None
    candidates = (replace(comparison.candidates[0], name=hostile), *comparison.candidates[1:])
    record = compose_decision_record(
        replace(
            dossier,
            case=CaseIdentity("hostile", hostile),
            evidence=(evidence,),
            task=task,
            candidate_comparison=replace(comparison, candidates=candidates),
        ),
        tool_version="0.1.0-test",
    )

    text = render_markdown_decision_report(record).decode("utf-8")
    assert "\x00" not in text and "\x1b" not in text and "\x85" not in text
    assert "\u200b" not in text and "\u2028" not in text and "\u202e" not in text
    assert "\\u0000" in text and "\\u001b" in text and "\\u0085" in text
    assert "\\u200b" in text and "\\u2028" in text and "\\u202e" in text
    assert "\\u000a" in text and "\\\\tail" in text
    for line in text.splitlines():
        if any(
            marker in line
            for marker in (
                "forged heading",
                "forged | table",
                "https://example.invalid",
                "<script>",
                "```",
                "[ref]",
            )
        ):
            assert line.startswith("    "), line
    assert text.count("# forged heading") == 5
    assert "\n| forged | table |" not in text


def test_rendering_is_pure_and_does_not_re_evaluate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _incomplete_record()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("renderer crossed its pure typed boundary")

    monkeypatch.setattr("archsift.decision_record.evaluate_assessment", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)

    first = render_markdown_decision_report(record)
    second = render_markdown_decision_report(record)
    assert first == second


def test_unknown_record_shape_fails_closed() -> None:
    @dataclass(frozen=True, slots=True)
    class ExtendedDecisionRecord(DecisionRecord):
        added_report_field: str = "unsupported"

    record = _incomplete_record()
    extended = ExtendedDecisionRecord(
        *[getattr(record, field.name) for field in record.__dataclass_fields__.values()]
    )

    with pytest.raises(MarkdownReportError, match="DecisionRecord"):
        render_markdown_decision_report(extended)


def test_report_bytes_are_hash_seed_independent() -> None:
    script = """
from archsift.decision_record import compose_decision_record
from archsift.markdown_report import render_markdown_decision_report
from archsift.validation import CaseIdentity, Dossier
record = compose_decision_record(Dossier(1, CaseIdentity('seed', 'café')), tool_version='test')
print(render_markdown_decision_report(record).hex())
"""
    outputs = []
    for seed in ("1", "947"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]
