from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
EXAMPLE_CASES = MANIFEST["examples"]


def _source_snapshot(workspace: Path) -> dict[str, bytes]:
    # Generated decision records under output/ are intentionally ignored and not
    # maintained sources, so exclude them (but keep the placeholder .gitkeep).
    return {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
        and (
            not path.relative_to(workspace).as_posix().startswith("output/")
            or path.name == ".gitkeep"
        )
    }


def _offline_environment(tmp_path: Path) -> dict[str, str]:
    blocker = tmp_path / "network-blocker"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(
        "import socket\n"
        "def blocked(*args, **kwargs):\n"
        "    raise AssertionError('example execution must remain offline')\n"
        "socket.create_connection = blocked\n"
        "socket.getaddrinfo = blocked\n"
        "socket.socket.connect = blocked\n"
        "socket.socket.connect_ex = blocked\n",
        encoding="utf-8",
        newline="\n",
    )
    environment = os.environ.copy()
    python_path = [str(blocker), str(ROOT / "src")]
    if existing := environment.get("PYTHONPATH"):
        python_path.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(python_path)
    return environment


def _run_cli(
    *arguments: str | Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "archsift", *(str(argument) for argument in arguments)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        timeout=10,
    )


def _all_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = payload["assessment"]
    return [
        *assessment["prerequisite_evaluation"]["findings"],
        *assessment["ordered_elimination_evaluation"]["findings"],
    ]


def test_example_manifest_matches_documented_source_workspaces() -> None:
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["corpus_version"] == "1.0.0"
    paths = [item["path"] for item in EXAMPLE_CASES]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths)) == 4

    actual_paths = sorted(
        path.name for path in EXAMPLES.iterdir() if path.is_dir() and not path.name.startswith(".")
    )
    assert actual_paths == paths

    overview = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "](examples/)" in root_readme

    for item in EXAMPLE_CASES:
        workspace = EXAMPLES / item["path"]
        expected_files = {
            "README.md",
            "case.yaml",
            "evidence/observations.txt",
            "output/.gitkeep",
        }
        assert set(_source_snapshot(workspace)) == expected_files
        assert f"]({item['path']}/)" in overview
        guidance = (workspace / "README.md").read_text(encoding="utf-8")
        assert f"validate examples/{item['path']} --json" in guidance
        assert f"assess examples/{item['path']} --json" in guidance


@pytest.mark.parametrize("example", EXAMPLE_CASES, ids=lambda item: item["path"])
def test_public_cli_runs_example_offline_and_deterministically(
    example: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = EXAMPLES / example["path"]
    source_before = _source_snapshot(source)
    workspace = tmp_path / example["path"]
    shutil.copytree(source, workspace)
    environment = _offline_environment(tmp_path)

    validation = _run_cli("validate", workspace, "--json", environment=environment)
    assert validation.stderr == b""
    assert json.loads(validation.stdout)["status"] == "valid"

    first = _run_cli("assess", workspace, "--json", environment=environment)
    assert first.stderr == b""
    payload = json.loads(first.stdout)
    assessment = payload["assessment"]
    assert assessment["verdict"] == example["verdict"]
    assert assessment["recommended_class"] == example["recommended_class"]
    assert assessment["evidence_state"] == example["evidence_state"]

    representative = next(
        finding
        for finding in _all_findings(payload)
        if finding["rule_id"] == example["representative_rule_id"]
    )
    assert example["representative_evidence_id"] in representative["evidence_ids"]

    identity = payload["record_content_identity"].removeprefix("sha256:")
    record = workspace / "output" / f"sha256-{identity}.json"
    report = workspace / "output" / f"sha256-{identity}.md"
    assert record.read_bytes() == first.stdout
    report_before = report.read_bytes()
    os.utime(record, (1_700_000_000, 1_700_000_000))
    os.utime(report, (1_700_000_000, 1_700_000_000))
    mtimes_before = (record.stat().st_mtime_ns, report.stat().st_mtime_ns)

    second = _run_cli("assess", workspace, "--json", environment=environment)
    assert second.stdout == first.stdout
    assert second.stderr == b""
    assert record.read_bytes() == first.stdout
    assert report.read_bytes() == report_before
    assert (record.stat().st_mtime_ns, report.stat().st_mtime_ns) == mtimes_before
    assert {path.name for path in (workspace / "output").iterdir()} == {
        ".gitkeep",
        record.name,
        report.name,
    }
    assert _source_snapshot(source) == source_before
