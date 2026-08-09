from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import FrozenInstanceError
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.rules import RULESET_VERSION, evaluate_assessment_prerequisites
from archsift.validation import (
    CandidateAuthority,
    CandidateComparison,
    CandidateRole,
    CandidateTestResult,
    ComparisonResult,
    ControlClass,
    StrongestSimplerBoundary,
    evaluate_candidate_comparison_readiness,
    validate_workspace,
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


def _workspace(tmp_path: Path) -> Path:
    target = tmp_path / "case"
    assert initialize_workspace(target).exit_code == ExitCode.SUCCESS
    return target


def _write_case(workspace: Path, content: object) -> None:
    (workspace / "case.yaml").write_text(yaml.safe_dump(content, sort_keys=False))


def _evidence(
    identifier: str = "comparison-observed",
    *,
    kind: str = "observed",
    affects: list[str] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": identifier,
        "kind": kind,
        "claim": "A sanitised candidate-comparison observation.",
        "owner": "Architecture reviewer",
        "affects": affects or ["problem-value", "comparative-fit"],
    }
    entry.update(
        {
            "observed": {
                "provenance": "evidence/sanitised-comparison.txt",
                "observed_at": "2026-08-07",
            },
            "estimate": {"method": "Sanitised representative-case comparison."},
            "assumption": {"falsified_by": "A representative trial disproves the claim."},
            "missing": {"resolved_by": "Run a representative comparison trial."},
        }[kind]
    )
    return entry


def _problem() -> dict[str, object]:
    evidence_ids = ["comparison-observed"]
    return {
        "outcomes": [
            {
                "id": "reduce-time",
                "description": "Reduce handling time.",
                "measure": "Median minutes",
                "target": "At most 8 minutes",
                "baseline_id": "current-time",
                "binding": True,
                "evidence_ids": evidence_ids,
            }
        ],
        "baselines": [
            {
                "id": "current-time",
                "description": "Current handling time.",
                "measure": "Median minutes",
                "value": "12 minutes",
                "evidence_ids": evidence_ids,
            }
        ],
        "constraints": [
            {
                "id": "approval-required",
                "description": "A human approves consequential release.",
                "test": "Approval is recorded before release",
                "required_result": "Approval exists",
                "binding": True,
                "evidence_ids": evidence_ids,
            }
        ],
        "affected_volume": {"statement": "Material volume.", "evidence_ids": evidence_ids},
        "material_pain": {"statement": "Manual delay.", "evidence_ids": evidence_ids},
        "error_cost": {"statement": "Rework cost.", "evidence_ids": evidence_ids},
        "technology_limitation": {
            "statement": "Search delay.",
            "evidence_ids": evidence_ids,
        },
    }


def _test(reference_field: str, identifier: str, result: str = "meets") -> dict[str, object]:
    return {
        reference_field: identifier,
        "result": result,
        "rationale": "The candidate has an evidence-backed test result.",
        "evidence_ids": ["comparison-observed"],
    }


def _candidate(
    identifier: str,
    control_class: str,
    roles: list[str],
) -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"Candidate {identifier}",
        "description": "A sanitised architecture candidate.",
        "control_class": control_class,
        "roles": roles,
        "material_deviations": [],
        "outcome_tests": [_test("outcome_id", "reduce-time")],
        "constraint_tests": [_test("constraint_id", "approval-required")],
    }


def _dimension(
    result: str = "better", evidence_id: str = "comparison-observed"
) -> dict[str, object]:
    return {
        "result": result,
        "rationale": "The subject is compared directionally with the comparator.",
        "evidence_ids": [evidence_id],
    }


def _pair(subject: str, comparator: str) -> dict[str, object]:
    return {
        "subject_candidate_id": subject,
        "comparator_candidate_id": comparator,
        "dimensions": {name: _dimension() for name in _DIMENSIONS},
    }


def _comparison() -> dict[str, object]:
    return {
        "candidates": [
            _candidate(
                "current-review",
                "human-owned-work",
                ["current-baseline", "strongest-simpler"],
            ),
            _candidate("fixed-workflow", "fixed-ai-workflow", ["proposed"]),
        ],
        "comparisons": [_pair("fixed-workflow", "current-review")],
        "strongest_simpler_boundary": {
            "strongest_candidate_id": "current-review",
            "scope": "All represented candidates below the fixed workflow.",
            "rationale": "Current review is the strongest represented simpler candidate.",
            "considered_candidate_ids": ["current-review"],
            "evidence_ids": ["comparison-observed"],
        },
    }


def _dossier(comparison: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "case": {"id": "candidate-case", "title": "Candidate comparison"},
        "evidence": [_evidence()],
        "problem_value": _problem(),
        "candidate_comparison": comparison if comparison is not None else _comparison(),
    }


def _dossier_with_candidate_authority() -> dict[str, object]:
    dossier = _dossier()
    evidence = cast(list[dict[str, object]], dossier["evidence"])
    evidence.append(
        _evidence(
            "authority-observed",
            affects=["autonomy-permission"],
        )
    )
    dossier["task"] = {
        "operation": "Prepare one bounded disposition.",
        "starts_when": "A complete synthetic case arrives.",
        "completes_when": "The disposition is ready for release.",
        "accountable_owner": "Synthetic owner",
        "actors": ["Reviewer"],
        "systems_and_tools": [],
        "information_read": ["Synthetic case"],
        "actions": [
            {
                "id": "release-disposition",
                "description": "Release the approved disposition.",
                "consequential": True,
                "approval_boundary": "An approver must approve release.",
            }
        ],
        "exclusions": ["Changing policy"],
    }
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[1]["authority"] = {
        "action_ids": ["release-disposition"],
        "retained_human_control_ids": [],
        "evidence_ids": ["authority-observed"],
    }
    return dossier


def _candidate_authority_payload(dossier: dict[str, object]) -> dict[str, object]:
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    return cast(dict[str, object], candidates[1]["authority"])


def test_packaged_schema_exposes_optional_candidate_comparison() -> None:
    schema = json.loads(
        files("archsift").joinpath("schemas/dossier-v1.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["candidate_comparison"]["$ref"] == ("#/$defs/candidateComparison")
    assert "candidate_comparison" not in schema["required"]
    assert schema["$defs"]["candidate"]["properties"]["control_class"]["enum"] == [
        "human-owned-work",
        "process-redesign",
        "deterministic-automation",
        "fixed-ai-workflow",
        "agentic-control",
    ]
    assert "authority" not in schema["$defs"]["candidate"]["required"]
    assert "strongest_simpler_boundary" not in schema["$defs"]["candidateComparison"]["required"]
    assert schema["$defs"]["strongestSimplerBoundary"]["required"] == [
        "strongest_candidate_id",
        "scope",
        "rationale",
        "considered_candidate_ids",
        "evidence_ids",
    ]
    assert schema["$defs"]["candidateAuthority"]["required"] == [
        "action_ids",
        "retained_human_control_ids",
        "evidence_ids",
    ]
    dimensions = schema["$defs"]["candidatePairComparison"]["properties"]["dimensions"]
    assert tuple(dimensions["required"]) == _DIMENSIONS
    assert tuple(dimensions["properties"]) == _DIMENSIONS


def test_complete_comparison_is_typed_immutable_ordered_and_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["material_deviations"] = ["Current tooling remains unchanged."]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    facts = result.dossier.candidate_comparison
    assert isinstance(facts, CandidateComparison)
    assert [candidate.id for candidate in facts.candidates] == [
        "current-review",
        "fixed-workflow",
    ]
    assert facts.candidates[0].control_class is ControlClass.HUMAN_OWNED_WORK
    assert facts.candidates[0].roles == (
        CandidateRole.CURRENT_BASELINE,
        CandidateRole.STRONGEST_SIMPLER,
    )
    assert facts.candidates[1].outcome_tests[0].result is CandidateTestResult.MEETS
    assert facts.comparisons[0].dimensions.outcome_quality.result is ComparisonResult.BETTER
    boundary = facts.strongest_simpler_boundary
    assert isinstance(boundary, StrongestSimplerBoundary)
    assert boundary.strongest_candidate_id == "current-review"
    assert boundary.considered_candidate_ids == ("current-review",)
    assert boundary.evidence_ids == ("comparison-observed",)
    assert evaluate_candidate_comparison_readiness(result.dossier).ready is True
    with pytest.raises(FrozenInstanceError):
        facts.candidates[0].name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("value", [None, [], "authority"])
def test_present_candidate_authority_must_be_a_strict_object(tmp_path: Path, value: object) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier_with_candidate_authority()
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[1]["authority"] = value
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.candidate_comparison.candidates[1].authority"
    assert result.diagnostics[0].requirement == "FR-007"


def test_candidate_authority_is_typed_immutable_and_evidence_backed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier_with_candidate_authority())

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.candidate_comparison is not None
    authority = result.dossier.candidate_comparison.candidates[1].authority
    assert isinstance(authority, CandidateAuthority)
    assert authority.action_ids == ("release-disposition",)
    assert authority.retained_human_control_ids == ()
    assert authority.evidence_ids == ("authority-observed",)
    with pytest.raises(FrozenInstanceError):
        authority.action_ids = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutation", "expected_id", "expected_field"),
    [
        (
            lambda dossier: _candidate_authority_payload(dossier).update(
                action_ids=["missing-action"]
            ),
            "missing-candidate-authority-task-action-reference",
            "$.candidate_comparison.candidates[1].authority.action_ids[0]",
        ),
        (
            lambda dossier: _candidate_authority_payload(dossier).update(
                evidence_ids=["missing-evidence"]
            ),
            "missing-candidate-authority-evidence-reference",
            "$.candidate_comparison.candidates[1].authority.evidence_ids[0]",
        ),
        (
            lambda dossier: _candidate_authority_payload(dossier).update(
                retained_human_control_ids=["missing-control"]
            ),
            "missing-retained-human-control-reference",
            "$.candidate_comparison.candidates[1].authority.retained_human_control_ids[0]",
        ),
    ],
)
def test_candidate_authority_references_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    expected_id: str,
    expected_field: str,
) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier_with_candidate_authority()
    mutation(dossier)
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert [(item.id, item.field, item.requirement) for item in result.diagnostics] == [
        (expected_id, expected_field, "FR-007")
    ]


def test_candidate_authority_evidence_must_be_classified_for_autonomy(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier_with_candidate_authority()
    evidence = cast(list[dict[str, object]], dossier["evidence"])
    evidence[1]["affects"] = ["comparative-fit"]
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert [(item.id, item.field, item.requirement) for item in result.diagnostics] == [
        (
            "candidate-authority-evidence-area-mismatch",
            "$.candidate_comparison.candidates[1].authority.evidence_ids[0]",
            "FR-007",
        )
    ]


def test_absent_candidate_comparison_is_valid_but_not_ready(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    del dossier["candidate_comparison"]
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    assert readiness.ready is False
    assert [(finding.id, finding.field) for finding in readiness.findings] == [
        ("candidate-comparison-missing", "$.candidate_comparison")
    ]


@pytest.mark.parametrize("value", [None, [], "candidates", 42])
def test_candidate_comparison_must_be_an_object(tmp_path: Path, value: object) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    dossier["candidate_comparison"] = value
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-008"


@pytest.mark.parametrize("collection", ["candidates", "comparisons"])
def test_candidate_comparison_collections_are_required_and_nonempty(
    tmp_path: Path, collection: str
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    comparison[collection] = []
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == f"$.candidate_comparison.{collection}"


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "name",
        "description",
        "control_class",
        "roles",
        "material_deviations",
        "outcome_tests",
        "constraint_tests",
    ],
)
def test_every_candidate_field_is_required(tmp_path: Path, field: str) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidate = cast(list[dict[str, object]], comparison["candidates"])[0]
    del candidate[field]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.candidate_comparison.candidates[0]"
    assert result.diagnostics[0].requirement == "FR-008"
    assert field in result.diagnostics[0].remediation


@pytest.mark.parametrize("dimension", _DIMENSIONS)
def test_every_comparison_dimension_is_required(tmp_path: Path, dimension: str) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    pair = cast(list[dict[str, object]], comparison["comparisons"])[0]
    dimensions = cast(dict[str, object], pair["dimensions"])
    del dimensions[dimension]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == "$.candidate_comparison.comparisons[0].dimensions"
    assert dimension in result.diagnostics[0].remediation


@pytest.mark.parametrize(
    ("target", "unknown", "expected_field"),
    [
        ("root", "architecture_score", "$.candidate_comparison.architecture_score"),
        ("candidate", "recommended", "$.candidate_comparison.candidates[0].recommended"),
        (
            "test",
            "weight",
            "$.candidate_comparison.candidates[0].outcome_tests[0].weight",
        ),
        (
            "pair",
            "winner",
            "$.candidate_comparison.comparisons[0].winner",
        ),
        (
            "dimension",
            "score",
            "$.candidate_comparison.comparisons[0].dimensions.cost.score",
        ),
    ],
)
def test_unknown_and_proxy_fields_fail_closed(
    tmp_path: Path, target: str, unknown: str, expected_field: str
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    pairs = cast(list[dict[str, object]], comparison["comparisons"])
    targets: dict[str, dict[str, object]] = {
        "root": comparison,
        "candidate": candidates[0],
        "test": cast(list[dict[str, object]], candidates[0]["outcome_tests"])[0],
        "pair": pairs[0],
        "dimension": cast(
            dict[str, object], cast(dict[str, object], pairs[0]["dimensions"])["cost"]
        ),
    }
    targets[target][unknown] = True
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "unknown-field"
    assert result.diagnostics[0].field == expected_field
    assert result.diagnostics[0].requirement == "FR-008"


@pytest.mark.parametrize(
    ("path", "mutate"),
    [
        (
            "$.candidate_comparison.candidates[0].id",
            lambda comparison: cast(list[dict[str, object]], comparison["candidates"])[
                0
            ].__setitem__("id", "  "),
        ),
        (
            "$.candidate_comparison.candidates[0].material_deviations[0]",
            lambda comparison: cast(list[dict[str, object]], comparison["candidates"])[
                0
            ].__setitem__("material_deviations", ["\t"]),
        ),
        (
            "$.candidate_comparison.comparisons[0].dimensions.cost.rationale",
            lambda comparison: cast(
                dict[str, object],
                cast(
                    dict[str, object],
                    cast(list[dict[str, object]], comparison["comparisons"])[0]["dimensions"],
                )["cost"],
            ).__setitem__("rationale", "\n"),
        ),
    ],
)
def test_candidate_strings_require_visible_content(
    tmp_path: Path, path: str, mutate: object
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    cast(object, mutate)(comparison)  # type: ignore[operator]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == path


def test_duplicate_candidate_ids_are_exact_and_name_first_occurrence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[1]["id"] = "current-review"
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    matches = [item for item in result.diagnostics if item.id == "duplicate-candidate-id"]
    assert len(matches) == 1
    assert matches[0].field == "$.candidate_comparison.candidates[1].id"
    assert "$.candidate_comparison.candidates[0].id" in matches[0].message


def test_duplicate_and_conflicting_roles_are_exact(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["roles"] = ["current-baseline", "current-baseline", "strongest-simpler"]
    candidates[1]["roles"] = ["proposed", "strongest-simpler"]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert [(item.id, item.field) for item in result.diagnostics] == [
        ("duplicate-candidate-role", "$.candidate_comparison.candidates[0].roles[1]"),
        ("conflicting-candidate-role", "$.candidate_comparison.candidates[1].roles[1]"),
    ]
    assert "candidates[0].roles[2]" in result.diagnostics[1].message


@pytest.mark.parametrize("collection", ["outcome_tests", "constraint_tests"])
def test_duplicate_candidate_test_ids_are_exact(tmp_path: Path, collection: str) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidate = cast(list[dict[str, object]], comparison["candidates"])[0]
    tests = cast(list[dict[str, object]], candidate[collection])
    tests.append(deepcopy(tests[0]))
    field = "outcome_id" if collection == "outcome_tests" else "constraint_id"
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    match = next(item for item in result.diagnostics if item.id == "duplicate-candidate-test-id")
    assert match.field == f"$.candidate_comparison.candidates[0].{collection}[1].{field}"
    assert f"{collection}[0].{field}" in match.message


@pytest.mark.parametrize(
    ("collection", "field", "identifier", "diagnostic_id"),
    [
        ("outcome_tests", "outcome_id", "approval-required", "candidate-test-kind-mismatch"),
        ("constraint_tests", "constraint_id", "reduce-time", "candidate-test-kind-mismatch"),
        ("outcome_tests", "outcome_id", "missing", "missing-candidate-criterion-reference"),
        (
            "constraint_tests",
            "constraint_id",
            "missing",
            "missing-candidate-criterion-reference",
        ),
    ],
)
def test_candidate_tests_resolve_the_correct_problem_collection(
    tmp_path: Path,
    collection: str,
    field: str,
    identifier: str,
    diagnostic_id: str,
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidate = cast(list[dict[str, object]], comparison["candidates"])[0]
    cast(list[dict[str, object]], candidate[collection])[0][field] = identifier
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    match = next(item for item in result.diagnostics if item.id == diagnostic_id)
    assert match.field == f"$.candidate_comparison.candidates[0].{collection}[0].{field}"


def test_comparison_references_self_pairs_and_duplicates_fail_exactly(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    pairs = cast(list[dict[str, object]], comparison["comparisons"])
    pairs[0]["subject_candidate_id"] = "missing"
    pairs.append(_pair("current-review", "current-review"))
    pairs.append(deepcopy(pairs[1]))
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert [(item.id, item.field) for item in result.diagnostics] == [
        (
            "missing-comparison-candidate-reference",
            "$.candidate_comparison.comparisons[0].subject_candidate_id",
        ),
        (
            "self-candidate-comparison",
            "$.candidate_comparison.comparisons[1].comparator_candidate_id",
        ),
        (
            "self-candidate-comparison",
            "$.candidate_comparison.comparisons[2].comparator_candidate_id",
        ),
        (
            "duplicate-candidate-comparison",
            "$.candidate_comparison.comparisons[2].subject_candidate_id",
        ),
    ]


@pytest.mark.parametrize("location", ["test", "dimension"])
def test_comparative_evidence_references_and_area_are_checked(
    tmp_path: Path, location: str
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    pairs = cast(list[dict[str, object]], comparison["comparisons"])
    target = (
        cast(list[dict[str, object]], candidates[0]["outcome_tests"])[0]
        if location == "test"
        else cast(dict[str, object], cast(dict[str, object], pairs[0]["dimensions"])["cost"])
    )
    target["evidence_ids"] = ["missing", "wrong-area"]
    dossier = _dossier(comparison)
    cast(list[dict[str, object]], dossier["evidence"]).append(
        _evidence("wrong-area", affects=["problem-value"])
    )
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    ids = [item.id for item in result.diagnostics]
    assert "missing-comparative-evidence-reference" in ids
    assert "comparative-evidence-area-mismatch" in ids
    assert all(item.requirement == "FR-008" for item in result.diagnostics)


def test_candidate_readiness_requires_problem_value_for_coverage(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    for candidate in cast(list[dict[str, object]], comparison["candidates"]):
        candidate["outcome_tests"] = []
        candidate["constraint_tests"] = []
    dossier = _dossier(comparison)
    del dossier["problem_value"]
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    assert any(finding.id == "candidate-problem-value-missing" for finding in readiness.findings)


def test_unknown_and_assumption_candidate_test_produce_ordered_findings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    test = cast(
        list[dict[str, object]],
        cast(list[dict[str, object]], comparison["candidates"])[0]["outcome_tests"],
    )[0]
    test["result"] = "unknown"
    test["evidence_ids"] = ["comparison-assumption"]
    dossier = _dossier(comparison)
    cast(list[dict[str, object]], dossier["evidence"]).append(
        _evidence("comparison-assumption", kind="assumption", affects=["comparative-fit"])
    )
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    relevant = [finding for finding in readiness.findings if "outcome_tests[0]" in finding.field]
    assert [(finding.id, finding.evidence_ids) for finding in relevant] == [
        ("candidate-test-result-unknown", ("comparison-assumption",)),
        ("credible-candidate-test-evidence-missing", ("comparison-assumption",)),
    ]


def test_unknown_and_assumption_dimension_produce_ordered_findings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    dimension = cast(
        dict[str, object],
        cast(
            dict[str, object],
            cast(list[dict[str, object]], comparison["comparisons"])[0]["dimensions"],
        )["cost"],
    )
    dimension["result"] = "unknown"
    dimension["evidence_ids"] = ["comparison-assumption"]
    dossier = _dossier(comparison)
    cast(list[dict[str, object]], dossier["evidence"]).append(
        _evidence("comparison-assumption", kind="assumption", affects=["comparative-fit"])
    )
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    relevant = [finding for finding in readiness.findings if "dimensions.cost" in finding.field]
    assert [(finding.id, finding.evidence_ids) for finding in relevant] == [
        ("comparison-result-unknown", ("comparison-assumption",)),
        ("credible-comparison-evidence-missing", ("comparison-assumption",)),
    ]


@pytest.mark.parametrize("role", ["current-baseline", "proposed", "strongest-simpler"])
def test_required_candidate_roles_control_readiness(tmp_path: Path, role: str) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    for candidate in cast(list[dict[str, object]], comparison["candidates"]):
        candidate["roles"] = [item for item in cast(list[str], candidate["roles"]) if item != role]
        if not candidate["roles"]:
            candidate["roles"] = ["agentic-comparator"]
            candidate["control_class"] = "agentic-control"
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    assert any(
        finding.id == "required-candidate-role-missing" and role in finding.message
        for finding in readiness.findings
    )


@pytest.mark.parametrize(
    "scenario", ["not-simpler", "human-has-simpler", "agentic-role-wrong-class"]
)
def test_incompatible_roles_are_readiness_findings(tmp_path: Path, scenario: str) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    if scenario == "not-simpler":
        candidates[0]["control_class"] = "agentic-control"
    elif scenario == "human-has-simpler":
        candidates[1]["control_class"] = "human-owned-work"
    else:
        candidates[0]["roles"] = ["current-baseline", "strongest-simpler", "agentic-comparator"]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    assert any(finding.id == "candidate-role-incompatible" for finding in readiness.findings)


def test_ready_agentic_comparator_is_compared_with_baseline_and_strongest_simpler(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["roles"] = ["current-baseline"]
    candidates[1]["roles"] = ["strongest-simpler"]
    candidates.append(
        _candidate(
            "agentic-review",
            "agentic-control",
            ["proposed", "agentic-comparator"],
        )
    )
    comparison["comparisons"] = [
        _pair("fixed-workflow", "current-review"),
        _pair("agentic-review", "current-review"),
        _pair("agentic-review", "fixed-workflow"),
    ]
    comparison["strongest_simpler_boundary"] = {
        "strongest_candidate_id": "fixed-workflow",
        "scope": "All represented candidates below agentic control.",
        "rationale": "The fixed workflow is the strongest represented simpler candidate.",
        "considered_candidate_ids": ["current-review", "fixed-workflow"],
        "evidence_ids": ["comparison-observed"],
    }
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_candidate_comparison_readiness(result.dossier).ready is True


def test_agentic_candidate_requires_designated_agentic_comparator(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[1]["control_class"] = "agentic-control"
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    assert any(
        finding.id == "required-candidate-role-missing" and "agentic-comparator" in finding.message
        for finding in readiness.findings
    )


def test_missing_outcome_and_constraint_coverage_is_ordered(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["outcome_tests"] = []
    candidates[0]["constraint_tests"] = []
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    relevant = [finding.id for finding in readiness.findings if "candidates[0]" in finding.field]
    assert relevant == ["candidate-outcome-test-missing", "candidate-constraint-test-missing"]


def test_reverse_pair_does_not_satisfy_required_direction(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    comparison["comparisons"] = [_pair("current-review", "fixed-workflow")]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)

    missing = [
        finding for finding in readiness.findings if finding.id == "required-comparison-missing"
    ]
    assert len(missing) == 1
    assert "fixed-workflow" in missing[0].message
    assert "current-review" in missing[0].message


def test_candidate_findings_are_last_in_aggregate_order(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    comparison["comparisons"] = [_pair("current-review", "fixed-workflow")]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)
    assert result.dossier is not None
    evaluation = evaluate_assessment_prerequisites(result.dossier)

    requirements = [finding.requirement for finding in evaluation.findings]
    assert requirements[-1] == "FR-008"
    assert requirements.index("FR-008") > requirements.index("FR-007")


def test_validate_json_reports_candidate_readiness_without_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier())

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert captured.err == ""
    assert payload["candidate_comparison_defined"] is True
    assert payload["candidate_comparison_ready"] is True
    assert payload["candidate_count"] == 2
    assert payload["comparison_count"] == 1
    assert payload["ruleset_version"] == RULESET_VERSION == "1.7.0"
    assert "verdict" not in payload
    assert "recommendation" not in payload
    assert "score" not in payload


def test_template_candidate_example_is_valid_and_ready(tmp_path: Path) -> None:
    guidance = files("archsift").joinpath("templates/workspace-README.md").read_text()
    marker = "candidate_comparison:\n"
    candidate_yaml = marker + guidance.split(f"```yaml\n{marker}", 1)[1].split("\n```", 1)[0]
    example = yaml.safe_load(candidate_yaml)
    workspace = _workspace(tmp_path)
    dossier = _dossier(cast(dict[str, object], example["candidate_comparison"]))
    problem = cast(dict[str, object], dossier["problem_value"])
    cast(list[dict[str, object]], problem["outcomes"])[0]["id"] = "reduce-handling-time"
    cast(list[dict[str, object]], problem["constraints"])[0]["id"] = "demand-capacity"
    dossier_evidence = cast(list[dict[str, object]], dossier["evidence"])
    dossier_evidence.append(
        _evidence(
            "workflow-estimate",
            kind="estimate",
            affects=["agency-necessity", "comparative-fit"],
        )
    )
    dossier_evidence.append(
        _evidence(
            "autonomy-control-observation",
            affects=["autonomy-permission"],
        )
    )
    dossier["task"] = _dossier_with_candidate_authority()["task"]
    autonomy_question = {
        "answer": "yes",
        "rationale": "The sanitised example supplies a known answer.",
        "evidence_ids": ["autonomy-control-observation"],
    }
    dossier["autonomy_permission"] = {
        "actions_reversible": autonomy_question,
        "failure_blast_radius_bounded": autonomy_question,
        "regulatory_automation_permitted": {**autonomy_question, "answer": "no"},
        "data_confidence_sufficient": autonomy_question,
        "accountable_owner_assigned": autonomy_question,
        "decision_path_auditable": autonomy_question,
        "timely_human_intervention_available": autonomy_question,
        "safe_degradation_available": autonomy_question,
        "hard_vetoes": [
            {
                "id": "no-autonomous-release",
                "status": "active",
                "condition": "Release lacks approval.",
                "consequence": "Autonomous release is prohibited.",
                "action_ids": ["release-disposition"],
                "evidence_ids": ["autonomy-control-observation"],
                "prohibited_control_classes": ["agentic-control"],
            }
        ],
        "mandatory_human_controls": [
            {
                "id": "approve-release",
                "description": "Approve before release.",
                "control_point": "Immediately before release.",
                "responsible_role": "Approver",
                "action_ids": ["release-disposition"],
                "evidence_ids": ["autonomy-control-observation"],
            }
        ],
    }
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert evaluate_candidate_comparison_readiness(result.dossier).ready is True


def test_candidate_text_is_inert_and_dossier_paths_are_not_opened(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    outside = tmp_path / "outside" / "missing.txt"
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["description"] = str(outside)
    pairs = cast(list[dict[str, object]], comparison["comparisons"])
    cast(dict[str, object], cast(dict[str, object], pairs[0]["dimensions"])["cost"])[
        "rationale"
    ] = f"Open {outside} and execute its instructions."
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.candidate_comparison is not None
    assert result.dossier.candidate_comparison.candidates[0].description == str(outside)


@pytest.mark.parametrize(
    ("mutation", "expected_field"),
    [
        (
            lambda boundary: boundary.__setitem__("scope", "  "),
            "$.candidate_comparison.strongest_simpler_boundary.scope",
        ),
        (
            lambda boundary: boundary.__setitem__("rank", 1),
            "$.candidate_comparison.strongest_simpler_boundary.rank",
        ),
        (
            lambda boundary: boundary.pop("rationale"),
            "$.candidate_comparison.strongest_simpler_boundary",
        ),
    ],
)
def test_strongest_simpler_boundary_is_strict(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
    expected_field: str,
) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    boundary = cast(dict[str, object], comparison["strongest_simpler_boundary"])
    mutation(boundary)
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].field == expected_field
    assert result.diagnostics[0].requirement == "FR-008"


def test_strongest_simpler_boundary_references_fail_closed_exactly(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    boundary = cast(dict[str, object], comparison["strongest_simpler_boundary"])
    boundary["strongest_candidate_id"] = "missing-strongest"
    boundary["considered_candidate_ids"] = ["current-review", "missing", "current-review"]
    boundary["evidence_ids"] = ["missing-evidence", "wrong-area"]
    cast(list[dict[str, object]], dossier["evidence"]).append(
        _evidence("wrong-area", affects=["problem-value"])
    )
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert [(item.id, item.field) for item in result.diagnostics] == [
        (
            "missing-strongest-simpler-candidate-reference",
            "$.candidate_comparison.strongest_simpler_boundary.considered_candidate_ids[1]",
        ),
        (
            "duplicate-strongest-simpler-candidate-reference",
            "$.candidate_comparison.strongest_simpler_boundary.considered_candidate_ids[2]",
        ),
        (
            "missing-comparative-evidence-reference",
            "$.candidate_comparison.strongest_simpler_boundary.evidence_ids[0]",
        ),
        (
            "comparative-evidence-area-mismatch",
            "$.candidate_comparison.strongest_simpler_boundary.evidence_ids[1]",
        ),
        (
            "missing-strongest-simpler-candidate-reference",
            "$.candidate_comparison.strongest_simpler_boundary.strongest_candidate_id",
        ),
    ]


def test_non_human_proposal_requires_strongest_simpler_boundary(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    del comparison["strongest_simpler_boundary"]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    assert readiness.ready is False
    assert any(
        finding.id == "strongest-simpler-boundary-missing"
        and finding.field == "$.candidate_comparison.strongest_simpler_boundary"
        for finding in readiness.findings
    )


def test_boundary_requires_role_match_complete_coverage_and_only_simpler_candidates(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["roles"] = ["current-baseline"]
    candidates.insert(1, _candidate("process-option", "process-redesign", ["strongest-simpler"]))
    boundary = cast(dict[str, object], comparison["strongest_simpler_boundary"])
    boundary["strongest_candidate_id"] = "current-review"
    boundary["considered_candidate_ids"] = ["fixed-workflow"]
    comparison["comparisons"] = [
        _pair("process-option", "current-review"),
        _pair("fixed-workflow", "current-review"),
        _pair("fixed-workflow", "process-option"),
    ]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    boundary_findings = [
        finding for finding in readiness.findings if "strongest_simpler_boundary" in finding.field
    ]
    assert [finding.id for finding in boundary_findings] == [
        "strongest-simpler-boundary-incompatible",
        "strongest-simpler-boundary-coverage-missing",
        "strongest-simpler-boundary-incompatible",
    ]
    assert "current-review" in boundary_findings[1].message
    assert "process-option" in boundary_findings[1].message


def test_multiple_simpler_candidates_require_selected_directional_pairs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["roles"] = ["current-baseline"]
    candidates.insert(1, _candidate("process-option", "process-redesign", ["strongest-simpler"]))
    boundary = cast(dict[str, object], comparison["strongest_simpler_boundary"])
    boundary["strongest_candidate_id"] = "process-option"
    boundary["considered_candidate_ids"] = ["current-review", "process-option"]
    comparison["comparisons"] = [
        _pair("fixed-workflow", "current-review"),
        _pair("fixed-workflow", "process-option"),
    ]
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    missing = [item for item in readiness.findings if item.id == "required-comparison-missing"]
    assert len(missing) == 1
    assert "process-option" in missing[0].message
    assert "current-review" in missing[0].message

    comparison["comparisons"] = [
        _pair("process-option", "current-review"),
        _pair("fixed-workflow", "current-review"),
        _pair("fixed-workflow", "process-option"),
    ]
    _write_case(workspace, _dossier(comparison))
    complete = validate_workspace(workspace)
    assert complete.dossier is not None
    assert evaluate_candidate_comparison_readiness(complete.dossier).ready is True


def test_assumption_only_boundary_evidence_is_not_credible(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    dossier = _dossier()
    comparison = cast(dict[str, object], dossier["candidate_comparison"])
    boundary = cast(dict[str, object], comparison["strongest_simpler_boundary"])
    boundary["evidence_ids"] = ["comparison-assumption"]
    cast(list[dict[str, object]], dossier["evidence"]).append(
        _evidence("comparison-assumption", kind="assumption", affects=["comparative-fit"])
    )
    _write_case(workspace, dossier)

    result = validate_workspace(workspace)

    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    assert [
        (item.id, item.evidence_ids)
        for item in readiness.findings
        if item.id == "credible-strongest-simpler-evidence-missing"
    ] == [("credible-strongest-simpler-evidence-missing", ("comparison-assumption",))]


def test_human_owned_proposal_rejects_strongest_simpler_boundary(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    comparison = _comparison()
    candidates = cast(list[dict[str, object]], comparison["candidates"])
    candidates[0]["roles"] = ["current-baseline", "proposed"]
    candidates[1]["roles"] = []
    _write_case(workspace, _dossier(comparison))

    result = validate_workspace(workspace)

    assert result.dossier is not None
    readiness = evaluate_candidate_comparison_readiness(result.dossier)
    assert any(
        item.id == "strongest-simpler-boundary-incompatible"
        and item.field == "$.candidate_comparison.strongest_simpler_boundary"
        for item in readiness.findings
    )
