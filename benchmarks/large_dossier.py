"""NFR-005 process-start benchmark for a 500-evidence, 20-candidate dossier."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVIDENCE_COUNT = 500
CANDIDATE_COUNT = 20
MAX_SECONDS = 2.0
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


class BenchmarkFailure(RuntimeError):
    """The measured process failed its correctness or performance contract."""


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One successful process-level benchmark result."""

    elapsed_seconds: float
    evidence_count: int
    candidate_count: int


def _evidence() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [
        {
            "id": "problem-observed",
            "kind": "observed",
            "claim": "The synthetic benchmark baseline is measured.",
            "owner": "Benchmark process analyst",
            "affects": ["problem-value"],
            "provenance": "Synthetic benchmark measurement.",
            "observed_at": "2026-08-07",
        },
        {
            "id": "agency-estimate",
            "kind": "estimate",
            "claim": "The synthetic benchmark supplies bounded comparative facts.",
            "owner": "Benchmark engineering lead",
            "affects": ["agency-necessity", "comparative-fit"],
            "method": "Deterministic synthetic benchmark fixture.",
        },
        {
            "id": "autonomy-observed",
            "kind": "observed",
            "claim": "The synthetic benchmark keeps consequential release human-approved.",
            "owner": "Benchmark risk reviewer",
            "affects": ["autonomy-permission"],
            "provenance": "Synthetic benchmark control review.",
            "observed_at": "2026-08-07",
        },
    ]
    entries.extend(
        {
            "id": f"filler-observed-{index:03d}",
            "kind": "observed",
            "claim": f"Synthetic benchmark observation {index:03d}.",
            "owner": "Benchmark fixture",
            "affects": ["comparative-fit"],
            "provenance": f"Synthetic benchmark artefact {index:03d}.",
            "observed_at": "2026-08-07",
        }
        for index in range(3, EVIDENCE_COUNT)
    )
    return entries


def _candidate(index: int) -> dict[str, Any]:
    if index == 0:
        control_class = "human-owned-work"
        roles = ["current-baseline"]
    elif index == CANDIDATE_COUNT - 2:
        control_class = "fixed-ai-workflow"
        roles = ["strongest-simpler"]
    elif index == CANDIDATE_COUNT - 1:
        control_class = "agentic-control"
        roles = ["proposed", "agentic-comparator"]
    elif index < 6:
        control_class = "process-redesign"
        roles = []
    elif index < 12:
        control_class = "deterministic-automation"
        roles = []
    else:
        control_class = "fixed-ai-workflow"
        roles = []
    return {
        "id": f"candidate-{index:02d}",
        "name": f"Synthetic candidate {index:02d}",
        "description": "A public synthetic architecture candidate for performance testing.",
        "control_class": control_class,
        "roles": roles,
        "material_deviations": [],
        "outcome_tests": [
            {
                "outcome_id": "reduce-time",
                "result": "fails" if index == 0 else "meets",
                "rationale": "The synthetic method records a known candidate outcome.",
                "evidence_ids": ["agency-estimate"],
            }
        ],
        "constraint_tests": [],
    }


def _comparison(subject: str, comparator: str) -> dict[str, Any]:
    return {
        "subject_candidate_id": subject,
        "comparator_candidate_id": comparator,
        "dimensions": {
            name: {
                "result": "equivalent",
                "rationale": "The deterministic fixture records a known directional result.",
                "evidence_ids": ["agency-estimate"],
            }
            for name in _DIMENSIONS
        },
    }


def build_large_dossier() -> dict[str, Any]:
    """Return the deterministic public NFR-005 dossier."""
    question_yes = {
        "answer": "yes",
        "rationale": "The synthetic fixture supplies a known evidence-backed answer.",
        "evidence_ids": ["agency-estimate"],
    }
    autonomy_yes = {
        "answer": "yes",
        "rationale": "The synthetic control review supplies a known answer.",
        "evidence_ids": ["autonomy-observed"],
    }
    candidates = [_candidate(index) for index in range(CANDIDATE_COUNT)]
    current_id = "candidate-00"
    comparisons = [
        _comparison(f"candidate-{index:02d}", current_id) for index in range(1, CANDIDATE_COUNT)
    ]
    comparisons.append(_comparison("candidate-19", "candidate-18"))
    return {
        "schema_version": 1,
        "case": {"id": "nfr005-large-dossier", "title": "Synthetic large dossier"},
        "task": {
            "operation": "Validate one synthetic benchmark case and record its disposition.",
            "starts_when": "The generated benchmark dossier is available.",
            "completes_when": "Validation and prerequisite readiness are reported.",
            "accountable_owner": "Benchmark owner",
            "actors": ["Benchmark reviewer", "Benchmark approver"],
            "systems_and_tools": [],
            "information_read": ["Synthetic benchmark facts"],
            "actions": [
                {
                    "id": "release-disposition",
                    "description": "Release the synthetic benchmark disposition.",
                    "consequential": True,
                    "approval_boundary": "A benchmark approver must approve before release.",
                }
            ],
            "exclusions": ["Changing the performance threshold"],
        },
        "evidence": _evidence(),
        "problem_value": {
            "outcomes": [
                {
                    "id": "reduce-time",
                    "description": "Reduce synthetic handling time.",
                    "measure": "Synthetic median minutes",
                    "target": "At most 8 minutes",
                    "baseline_id": "current-time",
                    "binding": True,
                    "evidence_ids": ["problem-observed"],
                }
            ],
            "baselines": [
                {
                    "id": "current-time",
                    "description": "Current synthetic handling time.",
                    "measure": "Synthetic median minutes",
                    "value": "12 minutes",
                    "evidence_ids": ["problem-observed"],
                }
            ],
            "constraints": [],
            "affected_volume": {
                "statement": "The synthetic volume is material.",
                "evidence_ids": ["problem-observed"],
            },
            "material_pain": {
                "statement": "The synthetic baseline has avoidable delay.",
                "evidence_ids": ["problem-observed"],
            },
            "error_cost": {
                "statement": "Synthetic errors require rework.",
                "evidence_ids": ["problem-observed"],
            },
            "technology_limitation": {
                "statement": "Synthetic retrieval contributes to delay.",
                "evidence_ids": ["problem-observed"],
            },
        },
        "agency_necessity": {
            "execution_steps_predefinable": question_yes,
            "step_count_or_order_predictable": question_yes,
            "runtime_tool_choice_required": {**question_yes, "answer": "no"},
            "runtime_replanning_required": {**question_yes, "answer": "no"},
            "environmental_feedback_available": question_yes,
            "completion_independently_verifiable": question_yes,
            "effects_independently_verifiable": question_yes,
            "fixed_workflow_sufficient": question_yes,
            "residual_cases": [],
        },
        "autonomy_permission": {
            "actions_reversible": {**autonomy_yes, "answer": "no"},
            "failure_blast_radius_bounded": autonomy_yes,
            "regulatory_automation_permitted": {**autonomy_yes, "answer": "no"},
            "data_confidence_sufficient": autonomy_yes,
            "accountable_owner_assigned": autonomy_yes,
            "decision_path_auditable": autonomy_yes,
            "timely_human_intervention_available": autonomy_yes,
            "safe_degradation_available": autonomy_yes,
            "hard_vetoes": [
                {
                    "id": "no-autonomous-release",
                    "status": "active",
                    "condition": "Release would occur without approval.",
                    "consequence": "Autonomous release is prohibited.",
                    "action_ids": ["release-disposition"],
                    "evidence_ids": ["autonomy-observed"],
                }
            ],
            "mandatory_human_controls": [
                {
                    "id": "approve-release",
                    "description": "Approve before synthetic release.",
                    "control_point": "Immediately before release.",
                    "responsible_role": "Benchmark approver",
                    "action_ids": ["release-disposition"],
                    "evidence_ids": ["autonomy-observed"],
                }
            ],
        },
        "candidate_comparison": {
            "candidates": candidates,
            "comparisons": comparisons,
        },
    }


def validate_benchmark_payload(payload: Mapping[str, object]) -> None:
    """Fail unless CLI JSON proves the complete benchmark boundary."""
    expected: dict[str, object] = {
        "status": "valid",
        "exit_code": 0,
        "evidence_count": EVIDENCE_COUNT,
        "candidate_count": CANDIDATE_COUNT,
        "candidate_comparison_defined": True,
        "candidate_comparison_ready": True,
        "assessment_prerequisites_ready": True,
        "prerequisite_finding_count": 0,
    }
    mismatches = {
        name: (payload.get(name), value)
        for name, value in expected.items()
        if payload.get(name) != value
    }
    if mismatches:
        raise BenchmarkFailure(f"Benchmark validation payload mismatch: {mismatches!r}")


def run_benchmark(
    *, max_seconds: float = MAX_SECONDS, python: str = sys.executable
) -> BenchmarkResult:
    """Generate before timing, then measure a fresh ArchSift validation process."""
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    with tempfile.TemporaryDirectory(prefix="archsift-nfr005-") as temporary:
        workspace = Path(temporary) / "case"
        workspace.mkdir()
        dossier = build_large_dossier()
        (workspace / "case.yaml").write_text(
            json.dumps(dossier, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [python, "-m", "archsift", "validate", str(workspace), "--json"],
                check=False,
                capture_output=True,
                text=True,
                timeout=max_seconds,
            )
        except OSError as error:
            raise BenchmarkFailure(f"Validation process could not start: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise BenchmarkFailure(
                f"NFR-005 exceeded: validation did not complete within {max_seconds:.3f}s "
                f"({EVIDENCE_COUNT} evidence, {CANDIDATE_COUNT} candidates)."
            ) from error
        elapsed = time.perf_counter() - started

    if completed.returncode != 0:
        raise BenchmarkFailure(
            f"Validation process exited {completed.returncode}: {completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BenchmarkFailure("Validation process did not emit valid JSON.") from error
    if not isinstance(payload, Mapping):
        raise BenchmarkFailure("Validation process JSON must be an object.")
    validate_benchmark_payload(payload)
    if elapsed > max_seconds:
        raise BenchmarkFailure(
            f"NFR-005 exceeded: {elapsed:.3f}s > {max_seconds:.3f}s "
            f"({EVIDENCE_COUNT} evidence, {CANDIDATE_COUNT} candidates)."
        )
    return BenchmarkResult(elapsed, EVIDENCE_COUNT, CANDIDATE_COUNT)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--python", default=sys.executable)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the NFR-005 gate and print one concise result."""
    args = _parser().parse_args(argv)
    try:
        result = run_benchmark(max_seconds=args.max_seconds, python=args.python)
    except (BenchmarkFailure, ValueError) as error:
        print(f"NFR-005 failed: {error}", file=sys.stderr)
        return 1
    print(
        f"NFR-005 passed: {result.evidence_count} evidence, "
        f"{result.candidate_count} candidates, {result.elapsed_seconds:.3f}s "
        f"<= {args.max_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
