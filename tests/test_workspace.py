from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.workspace import initialize_workspace


def test_init_creates_versioned_workspace(tmp_path: Path) -> None:
    target = tmp_path / "My First Case"

    result = initialize_workspace(target)

    assert result.exit_code == ExitCode.SUCCESS
    assert yaml.safe_load((target / "case.yaml").read_text()) == {
        "schema_version": 1,
        "case": {"id": "my-first-case", "title": "My First Case"},
        "evidence": [],
        "decision_conditions": [],
    }
    guidance = (target / "README.md").read_text()
    assert guidance.startswith("# ArchSift case workspace\n")
    assert "task:" in guidance
    assert "operation:" in guidance
    assert "approval_boundary:" in guidance
    assert "kind: observed" in guidance
    assert "kind: assumption" in guidance
    assert "kind: estimate" in guidance
    assert "kind: missing" in guidance
    assert "problem_value:" in guidance
    assert "baseline_id:" in guidance
    assert "technology_limitation:" in guidance
    assert "agency_necessity:" in guidance
    assert "fixed_workflow_sufficient:" in guidance
    assert "residual_cases:" in guidance
    assert "autonomy_permission:" in guidance
    assert "hard_vetoes:" in guidance
    assert "mandatory_human_controls:" in guidance
    assert "candidate_comparison:" in guidance
    assert "strongest-simpler" in guidance
    assert "difficult_case_performance:" in guidance
    assert "decision_conditions:" in guidance
    assert "target_control_class:" in guidance
    assert "If resolving an uncertainty could change the selected class" in guidance
    assert (target / "evidence").is_dir()
    assert (target / "output").is_dir()


def test_init_is_deterministic_for_same_directory_name(tmp_path: Path) -> None:
    first = tmp_path / "one" / "repeatable"
    second = tmp_path / "two" / "repeatable"

    assert initialize_workspace(first).exit_code == ExitCode.SUCCESS
    assert initialize_workspace(second).exit_code == ExitCode.SUCCESS

    assert (first / "case.yaml").read_bytes() == (second / "case.yaml").read_bytes()
    assert (first / "README.md").read_bytes() == (second / "README.md").read_bytes()


def test_init_refuses_non_empty_directory_without_changes(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("do not replace")

    result = initialize_workspace(target)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "workspace-not-empty"
    assert sentinel.read_text() == "do not replace"
    assert sorted(item.name for item in target.iterdir()) == ["keep.txt"]


def test_init_refuses_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.write_text("keep")

    result = initialize_workspace(target)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "workspace-target-not-directory"
    assert target.read_text() == "keep"


def test_init_json_output_is_machine_readable(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "json-case"

    assert main(["init", str(target), "--json"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload == {
        "diagnostics": [],
        "exit_code": 0,
        "status": "created",
        "workspace": str(target),
    }
    assert captured.err == ""


def test_init_quiet_suppresses_output(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "quiet-case"

    assert main(["init", str(target), "--quiet"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_init_refuses_dangling_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "dangling"
    target.symlink_to(tmp_path / "nowhere")

    result = initialize_workspace(target)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "workspace-target-not-directory"


def test_init_reports_uncreatable_target_cleanly(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("keep")
    target = blocker / "case"

    result = initialize_workspace(target)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "workspace-create-failed"
    assert blocker.read_text() == "keep"
