"""The per-action assistance envelope at the public CLI boundary (FR-011, FR-017, FR-019)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from archsift.cli import main
from archsift.decision import evaluate_assessment
from archsift.decision_record import _assessment_dict
from archsift.diagnostics import ExitCode
from archsift.executive_summary import build_executive_summary
from archsift.html_report import render_detailed_html_report
from archsift.validation import validate_workspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "fixed-workflow"


def _load_example() -> dict[str, Any]:
    return yaml.safe_load((EXAMPLE / "case.yaml").read_text(encoding="utf-8"))


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


def _assess(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dossier: dict[str, Any], name: str
) -> tuple[Path, dict[str, Any]]:
    workspace = _workspace(tmp_path, dossier, name)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return workspace, _json(capsys)


def _automation_candidate(dossier: dict[str, Any]) -> dict[str, Any]:
    candidate = next(
        item
        for item in dossier["candidate_comparison"]["candidates"]
        if item["control_class"] == "fixed-ai-workflow"
    )
    assert candidate["authority"]["action_ids"] == ["prepare-disposition"]
    return candidate


def _entries(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["action_id"]: entry for entry in record["assistance_envelope"]["entries"]}


def test_envelope_states_the_boundary_for_every_task_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, record = _assess(tmp_path, capsys, _load_example(), "retained")
    assert record["record_schema_version"] == 5
    assert record["assessment"]["verdict"] == "supported"
    envelope = record["assistance_envelope"]
    entries = _entries(record)
    assert list(entries) == [action["id"] for action in record["dossier"]["task"]["actions"]]

    prepare = entries["prepare-disposition"]
    assert prepare["consequential"] is False
    assert prepare["person_required"] is False
    assert prepare["mandatory_human_control_ids"] == []
    assert prepare["active_hard_veto_ids"] == []
    assert prepare["rule_ids"] == []
    assert prepare["evidence_ids"] == []
    assert [
        (
            item["candidate_id"],
            item["control_class"],
            item["retained_human_control_ids"],
            item["omitted_human_control_ids"],
        )
        for item in prepare["declared_authorities"]
    ] == [("fixed-workflow", "fixed-ai-workflow", [], [])]
    assert prepare["declared_authorities"][0]["evidence_ids"] == ["autonomy-observed"]

    release = entries["release-disposition"]
    assert release["consequential"] is True
    assert release["person_required"] is True
    assert release["mandatory_human_control_ids"] == ["approve-release"]
    assert release["active_hard_veto_ids"] == ["human-release-required"]
    assert release["declared_authorities"] == []
    assert release["evidence_ids"] == ["autonomy-observed"]
    assert release["rule_ids"] == [
        "mandatory-human-control-omitted",
        "mandatory-human-control-retained",
        "active-veto-blocks-candidate",
    ]

    assert envelope["human_decision_retained"] is True
    assert envelope["replaced_controls"] == []

    # The envelope introduces no fact: every cited ID resolves in the dossier.
    dossier = record["dossier"]
    evidence_ids = {entry["id"] for entry in dossier["evidence"]}
    control_ids = {
        item["id"] for item in dossier["autonomy_permission"]["mandatory_human_controls"]
    }
    veto_ids = {item["id"] for item in dossier["autonomy_permission"]["hard_vetoes"]}
    for entry in entries.values():
        assert set(entry["evidence_ids"]) <= evidence_ids
        assert set(entry["mandatory_human_control_ids"]) <= control_ids
        assert set(entry["active_hard_veto_ids"]) <= veto_ids

    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "## Assistance Envelope" in markdown and "**Human Decision Retained**" in markdown
    html = render_detailed_html_report(record).decode("utf-8")
    assert "Assistance Envelope" in html and "release-disposition" in html
    summary = build_executive_summary(record)
    section = next(item for item in summary.sections if item.title == "Assistance Envelope")
    labels = [point.label for point in section.points]
    assert labels == ["prepare-disposition", "release-disposition", "Human Decision Retained"]
    assert section.points[-1].values[0].startswith("yes")


def test_envelope_reports_a_candidate_that_would_replace_a_retained_control(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    candidate = _automation_candidate(dossier)
    candidate["authority"]["action_ids"] = ["prepare-disposition", "release-disposition"]
    _, record = _assess(tmp_path, capsys, dossier, "replaced")

    release = _entries(record)["release-disposition"]
    assert [
        (
            item["candidate_id"],
            item["retained_human_control_ids"],
            item["omitted_human_control_ids"],
        )
        for item in release["declared_authorities"]
    ] == [("fixed-workflow", [], ["approve-release"])]
    envelope = record["assistance_envelope"]
    assert envelope["human_decision_retained"] is False
    assert envelope["replaced_controls"] == [
        {
            "action_id": "release-disposition",
            "candidate_id": "fixed-workflow",
            "human_control_ids": ["approve-release"],
        }
    ]
    summary = build_executive_summary(record)
    section = next(item for item in summary.sections if item.title == "Assistance Envelope")
    assert section.points[-1].values[0].startswith("no")


def test_envelope_reports_a_candidate_that_retains_the_control(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    candidate = _automation_candidate(dossier)
    candidate["authority"]["action_ids"] = ["prepare-disposition", "release-disposition"]
    candidate["authority"]["retained_human_control_ids"] = ["approve-release"]
    _, record = _assess(tmp_path, capsys, dossier, "kept")

    release = _entries(record)["release-disposition"]
    assert release["declared_authorities"][0]["retained_human_control_ids"] == ["approve-release"]
    assert release["declared_authorities"][0]["omitted_human_control_ids"] == []
    assert record["assistance_envelope"]["human_decision_retained"] is True
    assert record["assistance_envelope"]["replaced_controls"] == []


def test_envelope_is_absent_without_bound_controls_or_vetoes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    dossier["autonomy_permission"]["hard_vetoes"] = []
    dossier["autonomy_permission"]["mandatory_human_controls"] = []
    _, record = _assess(tmp_path, capsys, dossier, "absent")

    assert "assistance_envelope" not in record
    assert record["record_schema_version"] == 5
    assert build_executive_summary(record).sections[3].title != "Assistance Envelope"


def test_envelope_never_changes_the_assessment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _load_example()
    candidate = _automation_candidate(dossier)
    candidate["authority"]["action_ids"] = ["prepare-disposition", "release-disposition"]
    workspace, record = _assess(tmp_path, capsys, dossier, "unchanged")

    # The assessment in the record is exactly the assessment of the dossier; the
    # envelope is derived beside it and feeds nothing back.
    typed = validate_workspace(workspace).dossier
    assert typed is not None
    assert record["assessment"] == _assessment_dict(evaluate_assessment(typed))
    assert record["assessment"]["verdict"] == "insufficient-evidence" or record["assessment"][
        "verdict"
    ] in {"supported", "no-technology-change", "conditional", "no-permissible-candidate"}
    assert "assistance_envelope" not in record["assessment"]
    assert not any("envelope" in gap["rule_id"] for gap in record["unresolved_gaps"])
