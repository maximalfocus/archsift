"""Declared baseline retention at the public CLI boundary (FR-002, FR-008, FR-010, FR-013)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.html_report import render_executive_html_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "no-technology-change"

_RETENTION = {
    "declared_by": "Fictional operations owner",
    "rationale": "Keeping the current procedure is the intended result of this synthetic review.",
    "evidence_ids": ["decision-observed"],
}


def _load_example() -> dict[str, Any]:
    return yaml.safe_load((EXAMPLE / "case.yaml").read_text(encoding="utf-8"))


def _non_discriminating(dossier: dict[str, Any]) -> dict[str, Any]:
    """Reshape the packaged example so every candidate meets the whole binding set."""
    comparison = dossier["candidate_comparison"]
    human, process = comparison["candidates"]
    assert human["id"] == "human-review" and process["id"] == "process-redesign"
    human["roles"] = ["current-baseline", "proposed"]
    human["outcome_tests"][0]["result"] = "meets"
    process["roles"] = []
    comparison["comparisons"][0]["dimensions"]["outcome_quality"]["result"] = "equivalent"
    comparison.pop("strongest_simpler_boundary")
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


def _findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload["assessment"]["prerequisite_evaluation"]["findings"])


def test_declaration_resolves_a_non_discriminating_set_as_an_authored_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _non_discriminating(_load_example())
    dossier["schema_version"] = 4
    dossier["candidate_comparison"]["baseline_retention"] = dict(_RETENTION)
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    validation = _json(capsys)
    assert validation["status"] == "valid"
    assert validation["assessment_prerequisites_ready"] is True
    assert validation["prerequisite_finding_count"] == 0

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    assert _json(capsys)["complete"] is True

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assessment = record["assessment"]
    assert assessment["verdict"] == "no-technology-change"
    assert assessment["recommended_class"] == "human-owned-work"
    assert record["dossier_schema_version"] == 4
    assert all(
        finding["rule_id"]
        not in {"non-discriminating-binding-set", "baseline-retention-contradiction"}
        for finding in _findings(record)
    )
    # The declaration is echoed as authored content, never as a finding.
    assert record["dossier"]["candidate_comparison"]["baseline_retention"] == _RETENTION

    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "**Baseline Retention**" in markdown and "**Declared By**" in markdown
    assert "Fictional operations owner" in markdown
    executive = render_executive_html_report(record).decode("utf-8")
    assert "Baseline Retention (Authored Decision)" in executive
    assert "Fictional operations owner" in executive


def test_undeclared_set_names_the_declaration_route_and_is_resolved_by_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    undeclared = _non_discriminating(_load_example())
    undeclared["schema_version"] = 4
    before = _workspace(tmp_path, undeclared, "before")
    assert main(["assess", str(before), "--json"]) == ExitCode.SUCCESS
    old_bytes = capsys.readouterr().out
    old_record = json.loads(old_bytes)
    assert old_record["assessment"]["verdict"] == "insufficient-evidence"
    finding = next(
        item
        for item in _findings(old_record)
        if item["rule_id"] == "non-discriminating-binding-set"
    )
    assert "$.candidate_comparison.baseline_retention" in finding["remediation"]

    declared = _non_discriminating(_load_example())
    declared["schema_version"] = 4
    declared["candidate_comparison"]["baseline_retention"] = dict(_RETENTION)
    after = _workspace(tmp_path, declared, "after")
    assert main(["assess", str(after), "--json"]) == ExitCode.SUCCESS
    new_bytes = capsys.readouterr().out
    new_record = json.loads(new_bytes)
    assert new_record["assessment"]["verdict"] == "no-technology-change"

    # compare consumes the exact canonical bytes assess emitted, never a re-serialization.
    (tmp_path / "old.json").write_bytes(old_bytes.encode("utf-8"))
    (tmp_path / "new.json").write_bytes(new_bytes.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.SUCCESS
    delta = _json(capsys)
    assert delta["changed_evidence"]["dossier_content_identity"]["changed"] is True
    assert delta["changed_rules"]["ruleset_version"]["changed"] is False
    removed = delta["changed_rules"]["findings"]["removed"]
    assert [item["rule_id"] for item in removed] == ["non-discriminating-binding-set"]
    assert delta["verdict_delta"] == {
        "changed": True,
        "old": "insufficient-evidence",
        "new": "no-technology-change",
    }


def test_declaration_beside_a_credibly_failing_baseline_is_a_contradiction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    dossier["schema_version"] = 4
    dossier["candidate_comparison"]["baseline_retention"] = dict(_RETENTION)
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    validation = _json(capsys)
    assert validation["status"] == "valid"
    assert validation["assessment_prerequisites_ready"] is False

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    assert record["assessment"]["recommended_class"] is None
    finding = next(
        item for item in _findings(record) if item["rule_id"] == "baseline-retention-contradiction"
    )
    assert finding["effect"] == "require-evidence"
    assert finding["field"] == "$.candidate_comparison.baseline_retention"
    assert finding["counterpart"] == "$.candidate_comparison.candidates[0].outcome_tests[0].result"
    assert finding["evidence_ids"] == ["decision-observed"]


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (
            lambda retention: retention.update({"scored": 1}),
            "$.candidate_comparison.baseline_retention",
        ),
        (lambda retention: retention.update({"declared_by": " "}), "declared_by"),
        (lambda retention: retention.pop("rationale"), "$.candidate_comparison.baseline_retention"),
        (
            lambda retention: retention.update({"evidence_ids": ["absent-evidence"]}),
            "$.candidate_comparison.baseline_retention.evidence_ids[0]",
        ),
    ],
    ids=["unknown-key", "blank-declarer", "missing-rationale", "dangling-evidence"],
)
def test_malformed_declaration_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: Any, field: str
) -> None:
    dossier = _non_discriminating(_load_example())
    dossier["schema_version"] = 4
    retention = dict(_RETENTION)
    mutation(retention)
    dossier["candidate_comparison"]["baseline_retention"] = retention
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    payload = _json(capsys)
    assert payload["status"] == "invalid"
    assert any(field in diagnostic["field"] for diagnostic in payload["diagnostics"])


def test_declaration_is_rejected_on_earlier_schema_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _non_discriminating(_load_example())
    dossier["schema_version"] = 3
    dossier["candidate_comparison"]["baseline_retention"] = dict(_RETENTION)
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    payload = _json(capsys)
    assert any(
        "baseline_retention" in diagnostic["message"] for diagnostic in payload["diagnostics"]
    )


def test_earlier_schema_dossier_addresses_the_same_record_without_the_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _non_discriminating(_load_example())
    assert dossier["schema_version"] == 1
    workspace = _workspace(tmp_path, dossier)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["dossier_schema_version"] == 1
    assert "baseline_retention" not in record["dossier"]["candidate_comparison"]
    assert record["assessment"]["verdict"] == "insufficient-evidence"
