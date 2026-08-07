from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from archsift.diagnostics import ExitCode
from archsift.rules import evaluate_assessment_prerequisites
from archsift.validation import CandidateRole, validate_workspace
from benchmarks.large_dossier import (
    CANDIDATE_COUNT,
    EVIDENCE_COUNT,
    BenchmarkFailure,
    build_large_dossier,
    run_benchmark,
    validate_benchmark_payload,
)


def test_large_dossier_fixture_is_deterministic_and_has_prd_scale() -> None:
    first = build_large_dossier()
    second = build_large_dossier()

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(first["evidence"]) == EVIDENCE_COUNT == 500
    comparison = first["candidate_comparison"]
    assert len(comparison["candidates"]) == CANDIDATE_COUNT == 20
    assert len(comparison["comparisons"]) == 20
    role_lists = [candidate["roles"] for candidate in comparison["candidates"]]
    assert role_lists.count([]) == 17
    assert role_lists[0] == ["current-baseline"]
    assert role_lists[-2] == ["strongest-simpler"]
    assert role_lists[-1] == ["proposed", "agentic-comparator"]


def test_large_dossier_is_valid_typed_and_assessment_prerequisite_ready(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "case.yaml").write_text(
        json.dumps(build_large_dossier(), sort_keys=True), encoding="utf-8"
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert len(result.dossier.evidence) == EVIDENCE_COUNT
    comparison = result.dossier.candidate_comparison
    assert comparison is not None
    assert len(comparison.candidates) == CANDIDATE_COUNT
    assert comparison.candidates[1].roles == ()
    assert comparison.candidates[-1].roles == (
        CandidateRole.PROPOSED,
        CandidateRole.AGENTIC_COMPARATOR,
    )
    prerequisites = evaluate_assessment_prerequisites(result.dossier)
    assert prerequisites.ready is True
    assert prerequisites.findings == ()


def _valid_payload() -> dict[str, object]:
    return {
        "status": "valid",
        "exit_code": 0,
        "evidence_count": EVIDENCE_COUNT,
        "candidate_count": CANDIDATE_COUNT,
        "candidate_comparison_defined": True,
        "candidate_comparison_ready": True,
        "assessment_prerequisites_ready": True,
        "prerequisite_finding_count": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "invalid"),
        ("exit_code", 12),
        ("evidence_count", EVIDENCE_COUNT - 1),
        ("candidate_count", CANDIDATE_COUNT - 1),
        ("candidate_comparison_defined", False),
        ("candidate_comparison_ready", False),
        ("assessment_prerequisites_ready", False),
        ("prerequisite_finding_count", 1),
    ],
)
def test_benchmark_payload_checks_fail_closed(field: str, value: object) -> None:
    payload = deepcopy(_valid_payload())
    payload[field] = value

    with pytest.raises(BenchmarkFailure, match="payload mismatch"):
        validate_benchmark_payload(payload)


def test_process_start_benchmark_meets_nfr005() -> None:
    result = run_benchmark()

    assert result.evidence_count == EVIDENCE_COUNT
    assert result.candidate_count == CANDIDATE_COUNT
    assert result.elapsed_seconds <= 2.0
