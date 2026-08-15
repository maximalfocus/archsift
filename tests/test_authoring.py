from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from archsift.authoring import (
    PREREQUISITE_WORKLIST_SCHEMA_VERSION,
    dossier_schema_surface,
)
from archsift.canonical import canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.workspace import initialize_workspace

ROOT = Path(__file__).parents[1]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "case"
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    return workspace


@pytest.mark.parametrize("version", [1, 2, 3])
def test_dossier_schema_emits_complete_canonical_packaged_contract(
    version: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["dossier-schema", "--schema-version", str(version), "--json"]) == 0

    content = capsys.readouterr().out.encode("utf-8")
    payload = json.loads(content)
    surface = dossier_schema_surface(version)
    assert content == surface.canonical_bytes
    assert content == canonical_json_bytes(payload)
    assert payload["properties"]["schema_version"]["const"] == version
    Draft202012Validator.check_schema(payload)


def test_dossier_schema_defaults_latest_and_supports_human_and_quiet_modes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["dossier-schema"]) == 0
    human = capsys.readouterr().out
    assert human.startswith("Dossier schema 3: sha256:")
    assert "top-level properties" in human and "definitions" in human

    assert main(["dossier-schema", "--quiet"]) == 0
    assert capsys.readouterr() == ("", "")


def test_prerequisite_worklist_is_versioned_complete_and_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = ROOT / "examples/no-technology-change"
    assert main(["prerequisites", str(case), "--json"]) == 0
    first = capsys.readouterr().out.encode("utf-8")
    assert main(["prerequisites", str(case), "--json"]) == 0
    second = capsys.readouterr().out.encode("utf-8")

    assert first == second
    payload = json.loads(first)
    assert payload["prerequisite_worklist_schema_version"] == (PREREQUISITE_WORKLIST_SCHEMA_VERSION)
    assert payload["complete"] is True
    assert payload["findings"] == []
    assert payload["dossier_schema_version"] == 1
    assert payload["dossier_content_identity"].startswith("sha256:")
    assert payload["ruleset_version"]


def test_incomplete_worklist_preserves_generated_finding_contract_without_opening_artefacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    dossier = {
        "schema_version": 1,
        "case": {"id": "incomplete", "title": "Authored title must not render"},
        "evidence": [
            {
                "id": "missing-file-observation",
                "kind": "observed",
                "claim": "Authored claim must not render",
                "owner": "Authored owner must not render",
                "affects": ["problem-value"],
                "provenance": "Authored provenance must not render",
                "observed_at": "2026-08-16",
                "artefacts": [{"id": "absent", "root": "workspace", "path": "does-not-exist.bin"}],
            }
        ],
    }
    (workspace / "case.yaml").write_text(json.dumps(dossier), encoding="utf-8")

    assert main(["prerequisites", str(workspace), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["complete"] is False
    assert payload["findings"]
    assert set(payload["findings"][0]) == {
        "consequence",
        "counterpart",
        "effect",
        "evidence_ids",
        "field",
        "message",
        "remediation",
        "requirement",
        "rule_id",
    }

    assert main(["prerequisites", str(workspace)]) == 0
    human = capsys.readouterr().out
    assert "Assessment prerequisites incomplete" in human
    assert "Authored" not in human


def test_prerequisites_reuses_validate_failure_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text("schema_version: 99\ncase: {}\n", encoding="utf-8")

    assert main(["validate", str(workspace), "--json"]) == ExitCode.UNSUPPORTED_SCHEMA
    validation = json.loads(capsys.readouterr().out)
    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.UNSUPPORTED_SCHEMA
    prerequisites = json.loads(capsys.readouterr().out)

    assert prerequisites["status"] == validation["status"] == "invalid"
    assert prerequisites["exit_code"] == validation["exit_code"]
    assert prerequisites["diagnostics"] == validation["diagnostics"]


def test_prerequisites_is_read_only_and_quiet(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    before = {
        path.relative_to(workspace).as_posix(): path.stat().st_mtime_ns
        for path in workspace.rglob("*")
    }

    assert main(["prerequisites", str(workspace), "--quiet"]) == 0

    after = {
        path.relative_to(workspace).as_posix(): path.stat().st_mtime_ns
        for path in workspace.rglob("*")
    }
    assert before == after
    assert capsys.readouterr() == ("", "")
