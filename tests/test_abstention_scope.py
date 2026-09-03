"""Scoped abstention at the public CLI boundary (FR-010, FR-011, FR-017, FR-019)."""

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

_GAP = {
    "id": "baseline-gap",
    "claim": "The current acceptance rate has never been recorded.",
    "owner": "Fictional evaluation team",
    "affects": ["problem-value"],
    "artefacts": [],
    "kind": "missing",
    "resolved_by": "Measure the acceptance rate over a representative month.",
}


def _load_example() -> dict[str, Any]:
    return yaml.safe_load((EXAMPLE / "case.yaml").read_text(encoding="utf-8"))


def _abstaining(dossier: dict[str, Any]) -> dict[str, Any]:
    """Leave the binding baseline unmeasured so the assessment abstains."""
    dossier["evidence"] = [*dossier["evidence"], dict(_GAP)]
    dossier["problem_value"]["baselines"][0]["evidence_ids"] = ["baseline-gap"]
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


def _assess(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dossier: dict[str, Any], name: str
) -> tuple[Path, dict[str, Any]]:
    workspace = _workspace(tmp_path, dossier, name)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return workspace, _json(capsys)


def test_abstention_states_what_is_determined_and_frames_the_remaining_choice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, record = _assess(tmp_path, capsys, _abstaining(_load_example()), "retained")
    assert record["record_schema_version"] == 5
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    scope = record["abstention_scope"]

    assert scope["eliminated_classes"] == [
        {
            "candidate_ids": ["human-review"],
            "control_class": "human-owned-work",
            "rule_ids": ["binding-outcome-failed"],
        }
    ]
    assert scope["undetermined_classes"] == []
    assert scope["surviving_classes"] == ["fixed-ai-workflow"]
    assert scope["assistance_envelope_present"] is True
    assert scope["human_decision_retained"] is True
    assert scope["remaining_choice"] == "assist-or-not"
    assert scope["outstanding_gap_rule_ids"] == ["credible-baseline-missing"]
    # Every determination restates facts already in the record.
    classes = {
        item["control_class"]: item
        for item in record["assessment"]["ordered_elimination_evaluation"]["control_classes"]
    }
    assert classes["human-owned-work"]["disposition"] == "eliminated"
    assert classes["fixed-ai-workflow"]["disposition"] == "survives"
    assert {
        gap["rule_id"] for gap in record["unresolved_gaps"] if gap["effect"] != "non-decisive"
    } == {"credible-baseline-missing"}

    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "## Abstention Scope" in markdown and "assist-or-not" in markdown
    html = render_detailed_html_report(record).decode("utf-8")
    assert "Abstention Scope" in html and "credible-baseline-missing" in html
    summary = build_executive_summary(record)
    titles = [section.title for section in summary.sections]
    assert titles.index("Abstention Scope") == titles.index("Verdict") + 1
    section = summary.sections[titles.index("Abstention Scope")]
    labels = [point.label for point in section.points]
    assert labels == [
        "Already Eliminated",
        "Surviving Classes",
        "Human Decision Retained",
        "Remaining Choice",
        "Outstanding Gaps",
    ]
    assert section.points[3].values[0].startswith("whether to assist at all")


def test_abstention_frames_an_unresolved_autonomy_question_when_a_control_would_be_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _abstaining(_load_example())
    candidate = next(
        item
        for item in dossier["candidate_comparison"]["candidates"]
        if item["control_class"] == "fixed-ai-workflow"
    )
    candidate["authority"]["action_ids"] = ["prepare-disposition", "release-disposition"]
    _, record = _assess(tmp_path, capsys, dossier, "replaced")

    scope = record["abstention_scope"]
    assert scope["human_decision_retained"] is False
    assert scope["remaining_choice"] == "autonomy-unresolved"
    summary = build_executive_summary(record)
    section = next(item for item in summary.sections if item.title == "Abstention Scope")
    choice = next(point for point in section.points if point.label == "Remaining Choice")
    assert choice.values == ("an unresolved autonomy question",)


def test_abstention_without_an_envelope_reports_no_retention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _abstaining(_load_example())
    dossier["autonomy_permission"]["hard_vetoes"] = []
    dossier["autonomy_permission"]["mandatory_human_controls"] = []
    _, record = _assess(tmp_path, capsys, dossier, "no-envelope")

    scope = record["abstention_scope"]
    assert "assistance_envelope" not in record
    assert scope["assistance_envelope_present"] is False
    assert scope["human_decision_retained"] is None
    assert scope["remaining_choice"] == "autonomy-unresolved"


def test_determined_verdict_carries_no_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, record = _assess(tmp_path, capsys, _load_example(), "determined")

    assert record["assessment"]["verdict"] == "supported"
    assert "abstention_scope" not in record
    assert "Abstention Scope" not in [
        section.title for section in build_executive_summary(record).sections
    ]


def test_scope_never_changes_the_assessment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, record = _assess(tmp_path, capsys, _abstaining(_load_example()), "unchanged")

    typed = validate_workspace(workspace).dossier
    assert typed is not None
    assert record["assessment"] == _assessment_dict(evaluate_assessment(typed))
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    assert "abstention_scope" not in record["assessment"]
