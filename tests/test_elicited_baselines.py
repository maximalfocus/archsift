"""Elicited baselines at the public CLI boundary (FR-002, FR-005, FR-010, FR-012)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "fixed-workflow"

_ELICITED = {
    "id": "elicited-baseline",
    "claim": "Reviewers judge the current procedure to miss the target on most weeks.",
    "owner": "Fictional evaluation team",
    "affects": ["problem-value"],
    "artefacts": [],
    "kind": "estimate",
    "method": "Structured elicitation of the reviewers who run the task.",
    "elicitation": {
        "roles": ["Reviewer", "Approver"],
        "coverage": "The twelve most recent synthetic review weeks.",
        "scale": "ordinal",
    },
}


def _load_example() -> dict[str, Any]:
    return yaml.safe_load((EXAMPLE / "case.yaml").read_text(encoding="utf-8"))


def _elicited(dossier: dict[str, Any], target_kind: str | None) -> dict[str, Any]:
    """Point the binding outcome's baseline at an elicited estimate only."""
    dossier["schema_version"] = 5
    dossier["evidence"] = [*dossier["evidence"], dict(_ELICITED)]
    problem = dossier["problem_value"]
    problem["baselines"][0]["evidence_ids"] = ["elicited-baseline"]
    outcome = problem["outcomes"][0]
    assert outcome["binding"] is True
    if target_kind is not None:
        outcome["target_kind"] = target_kind
    return dossier


def _workspace(tmp_path: Path, dossier: dict[str, Any], name: str = "case") -> Path:
    workspace = tmp_path / name
    workspace.mkdir()
    shutil.copytree(EXAMPLE / "evidence", workspace / "evidence")
    (workspace / "output").mkdir()
    (workspace / "case.yaml").write_text(
        yaml.safe_dump(dossier, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return workspace


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    return payload


def _findings(record: dict[str, Any]) -> list[dict[str, Any]]:
    return list(record["assessment"]["prerequisite_evaluation"]["findings"])


@pytest.mark.parametrize("target_kind", ["no-regression", "directional"])
def test_elicited_baseline_supports_a_no_regression_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target_kind: str
) -> None:
    workspace = _workspace(tmp_path, _elicited(_load_example(), target_kind))

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    validation = _json(capsys)
    assert validation["status"] == "valid"
    assert validation["assessment_prerequisites_ready"] is True

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "supported"
    assert record["dossier_schema_version"] == 5
    assert not any(
        finding["rule_id"] in {"credible-baseline-missing", "elicited-baseline-quantified-target"}
        for finding in _findings(record)
    )
    # The record states that the baseline was elicited rather than measured.
    entry = next(
        item for item in record["dossier"]["evidence"] if item["id"] == "elicited-baseline"
    )
    assert entry["elicitation"] == _ELICITED["elicitation"]
    assert record["dossier"]["problem_value"]["outcomes"][0]["target_kind"] == target_kind
    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "**Elicitation**" in markdown and "**Scale**" in markdown and "ordinal" in markdown


def test_elicited_baseline_is_refused_for_a_quantified_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _elicited(_load_example(), "quantified"))

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    assert record["assessment"]["recommended_class"] is None
    finding = next(
        item
        for item in _findings(record)
        if item["rule_id"] == "elicited-baseline-quantified-target"
    )
    assert finding["effect"] == "require-evidence"
    assert finding["field"] == "$.problem_value.outcomes[0].baseline_id"
    assert finding["counterpart"] == "$.problem_value.outcomes[0].target_kind"
    assert finding["evidence_ids"] == ["elicited-baseline"]
    assert "target kind quantified" in finding["message"]
    assert "directional or" in finding["remediation"]

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    worklist = _json(capsys)
    assert [item["rule_id"] for item in worklist["findings"]] == [
        "elicited-baseline-quantified-target"
    ]


def test_elicited_baseline_is_refused_for_an_undeclared_target_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _elicited(_load_example(), None))

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    finding = next(
        item
        for item in _findings(record)
        if item["rule_id"] == "elicited-baseline-quantified-target"
    )
    assert "target kind undeclared" in finding["message"]
    assert "target_kind" not in record["dossier"]["problem_value"]["outcomes"][0]


def test_gap_only_baseline_remediation_names_elicitation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    dossier["evidence"] = [
        *dossier["evidence"],
        {
            "id": "baseline-gap",
            "claim": "The current acceptance rate has never been recorded.",
            "owner": "Fictional evaluation team",
            "affects": ["problem-value"],
            "artefacts": [],
            "kind": "missing",
            "resolved_by": "Measure the acceptance rate over a representative month.",
        },
    ]
    dossier["problem_value"]["baselines"][0]["evidence_ids"] = ["baseline-gap"]
    workspace = _workspace(tmp_path, dossier)

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    worklist = _json(capsys)
    finding = next(
        item for item in worklist["findings"] if item["rule_id"] == "credible-baseline-missing"
    )
    assert "measurement is unavailable" in finding["remediation"]
    assert "elicitation" in finding["remediation"]

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "measurement is unavailable" in markdown


def test_measured_baseline_is_unaffected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _load_example())

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "supported"
    assert not any(
        finding["rule_id"] == "elicited-baseline-quantified-target" for finding in _findings(record)
    )


@pytest.mark.parametrize(
    ("mutate", "expected_field"),
    [
        (lambda entry: entry["elicitation"].update({"scale": "numeric"}), "elicitation"),
        (lambda entry: entry["elicitation"].update({"roles": []}), "elicitation"),
        (lambda entry: entry["elicitation"].pop("coverage"), "elicitation"),
        (lambda entry: entry.update({"kind": "observed"}), "evidence"),
    ],
    ids=["unknown-scale", "no-roles", "missing-coverage", "elicitation-on-observed"],
)
def test_malformed_elicitation_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutate: Any, expected_field: str
) -> None:
    dossier = _elicited(_load_example(), "no-regression")
    entry = dossier["evidence"][-1]
    mutate(entry)
    if entry["kind"] == "observed":
        entry.update({"provenance": "Fictional observations.", "observed_at": "2026-08-08"})
        entry.pop("method")
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    payload = _json(capsys)
    assert payload["status"] == "invalid"
    assert any(expected_field in diagnostic["field"] for diagnostic in payload["diagnostics"])


def test_target_kind_and_elicitation_are_rejected_on_earlier_schemas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _elicited(_load_example(), "no-regression")
    dossier["schema_version"] = 4
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    messages = " ".join(item["message"] for item in _json(capsys)["diagnostics"])
    assert "elicitation" in messages or "target_kind" in messages
