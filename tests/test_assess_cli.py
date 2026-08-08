from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from archsift import package_version
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.workspace import initialize_workspace


def _workspace(tmp_path: Path, name: str = "case") -> Path:
    workspace = tmp_path / name
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    return workspace


def _external_dossier(workspace: Path) -> None:
    dossier = {
        "schema_version": 1,
        "case": {"id": "external", "title": "Synthetic external evidence"},
        "evidence": [
            {
                "id": "observed",
                "kind": "observed",
                "claim": "Synthetic observed claim.",
                "owner": "Synthetic reviewer",
                "affects": ["problem-value"],
                "provenance": "Synthetic measurement name.",
                "observed_at": "2026-08-08",
                "artefacts": [
                    {
                        "id": "sample",
                        "root": "external",
                        "path": "sample.bin",
                    }
                ],
            }
        ],
        "decision_conditions": [],
    }
    (workspace / "case.yaml").write_text(
        yaml.safe_dump(dossier, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def test_assess_json_persists_exact_canonical_incomplete_record_and_reuses_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    first_output = capsys.readouterr()
    payload = json.loads(first_output.out)
    identity = payload["record_content_identity"]
    target = workspace / "output" / f"sha256-{identity[7:]}.json"
    report_target = workspace / "output" / f"sha256-{identity[7:]}.md"
    first_bytes = first_output.out.encode("ascii")

    assert first_output.err == ""
    assert payload["assessment"]["verdict"] == "insufficient-evidence"
    assert payload["tool_version"] == package_version()
    assert payload["artefact_links"] == []
    assert payload["configuration"] == {"entries": [], "schema_version": 1}
    assert target.read_bytes() == first_bytes
    assert identity in report_target.read_text(encoding="utf-8")
    os.utime(target, (1_700_000_000, 1_700_000_000))
    os.utime(report_target, (1_700_000_000, 1_700_000_000))
    before = (target.stat().st_mtime_ns, report_target.stat().st_mtime_ns)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    second_output = capsys.readouterr()

    assert second_output.out.encode("ascii") == first_bytes
    assert second_output.err == ""
    assert (target.stat().st_mtime_ns, report_target.stat().st_mtime_ns) == before
    assert set((workspace / "output").iterdir()) == {target, report_target}


def test_assess_human_and_quiet_modes_never_render_authored_or_host_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path, "authored-title-is-private")

    assert main(["assess", str(workspace)]) == ExitCode.SUCCESS
    human = capsys.readouterr()

    assert human.err == ""
    assert human.out.startswith("Assessment insufficient-evidence: sha256:")
    assert " -> output/sha256-" in human.out
    assert ".json; report -> output/sha256-" in human.out
    assert human.out.rstrip().endswith(".md")
    assert "authored-title-is-private" not in human.out
    assert str(tmp_path) not in human.out
    human_identity = human.out.split()[2]

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    machine = capsys.readouterr()
    assert json.loads(machine.out)["record_content_identity"] == human_identity

    assert main(["assess", str(workspace), "--quiet"]) == ExitCode.SUCCESS
    quiet = capsys.readouterr()
    assert quiet.out == quiet.err == ""
    stem = f"sha256-{human_identity[7:]}"
    assert {path.name for path in (workspace / "output").iterdir()} == {
        f"{stem}.json",
        f"{stem}.md",
    }


def test_external_artefact_requires_cli_grant_and_never_serializes_host_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    _external_dossier(workspace)
    external = tmp_path / "private-external-root"
    external.mkdir()
    (external / "sample.bin").write_bytes(b"synthetic\x00bytes")

    assert main(["assess", str(workspace), "--json"]) == ExitCode.ARTEFACT_UNAVAILABLE
    failure = capsys.readouterr()
    failure_payload = json.loads(failure.out)
    assert failure_payload["diagnostics"][0]["id"] == ("evidence-artefact-external-root-required")
    assert list((workspace / "output").iterdir()) == []

    missing_root = tmp_path / "private-missing-external-root"
    assert (
        main(
            [
                "assess",
                str(workspace),
                "--external-evidence-root",
                str(missing_root),
                "--json",
            ]
        )
        == ExitCode.UNSAFE_PATH
    )
    unsafe = capsys.readouterr()
    assert json.loads(unsafe.out)["diagnostics"][0]["id"] == (
        "evidence-artefact-external-root-unavailable"
    )
    assert str(missing_root) not in unsafe.out
    assert list((workspace / "output").iterdir()) == []

    assert (
        main(
            [
                "assess",
                str(workspace),
                "--external-evidence-root",
                str(external),
                "--json",
            ]
        )
        == ExitCode.SUCCESS
    )
    success = capsys.readouterr()
    payload = json.loads(success.out)

    assert payload["artefact_links"][0]["byte_length"] == 15
    assert payload["artefact_links"][0]["root"] == "external"
    assert str(external) not in success.out
    assert str(tmp_path) not in success.out

    os.utime(external / "sample.bin", (1_700_000_000, 1_700_000_000))
    (external / "unreferenced.bin").write_bytes(b"ignored")
    relocated = tmp_path / "relocated-external-root"
    relocated.mkdir()
    (relocated / "sample.bin").write_bytes(b"synthetic\x00bytes")
    assert (
        main(
            [
                "assess",
                str(workspace),
                "--external-evidence-root",
                str(relocated),
                "--json",
            ]
        )
        == ExitCode.SUCCESS
    )
    relocated_success = capsys.readouterr()
    assert relocated_success.out == success.out
    assert relocated_success.err == ""
    assert len(list((workspace / "output").glob("*.json"))) == 1

    (relocated / "sample.bin").write_bytes(b"changed synthetic bytes")
    assert (
        main(
            [
                "assess",
                str(workspace),
                "--external-evidence-root",
                str(relocated),
                "--json",
            ]
        )
        == ExitCode.SUCCESS
    )
    changed_success = capsys.readouterr()
    changed_payload = json.loads(changed_success.out)
    assert changed_payload["record_content_identity"] != payload["record_content_identity"]
    assert (
        changed_payload["artefact_links"][0]["content_identity"]
        != (payload["artefact_links"][0]["content_identity"])
    )
    assert len(list((workspace / "output").glob("*.json"))) == 2


def test_assess_validates_before_hashing_or_persistence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text("schema_version: 1\ncase: []\n", encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("assessment crossed the validation gate")

    monkeypatch.setattr("archsift.cli.evidence_artefact_identities", forbidden)
    monkeypatch.setattr("archsift.cli.persist_decision_outputs", forbidden)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "invalid"
    assert list((workspace / "output").iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_assess_refuses_output_root_escape_without_writing_outside(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "output").rmdir()
    (workspace / "output").symlink_to(outside, target_is_directory=True)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.UNSAFE_PATH
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert payload["status"] == "unsafe"
    assert payload["diagnostics"][0]["id"] == "decision-record-output-root-unsafe"
    assert payload["diagnostics"][0]["file"] == "output"
    assert list(outside.iterdir()) == []
    assert str(tmp_path) not in output.out


def test_assess_rejects_combined_json_and_quiet_modes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(SystemExit) as captured:
        main(["assess", str(workspace), "--json", "--quiet"])

    assert captured.value.code == ExitCode.USAGE
    assert list((workspace / "output").iterdir()) == []


def test_assess_reports_markdown_integrity_conflict_without_replacing_either_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    success = capsys.readouterr()
    identity = json.loads(success.out)["record_content_identity"]
    json_target = workspace / "output" / f"sha256-{identity[7:]}.json"
    report_target = workspace / "output" / f"sha256-{identity[7:]}.md"
    json_before = json_target.read_bytes()
    report_target.write_bytes(b"conflicting Markdown bytes")

    assert main(["assess", str(workspace), "--json"]) == ExitCode.PERSISTENCE_FAILED
    failure = capsys.readouterr()
    payload = json.loads(failure.out)

    assert payload["status"] == "persistence-failed"
    assert payload["diagnostics"][0]["id"] == "decision-record-integrity-conflict"
    assert json_target.read_bytes() == json_before
    assert report_target.read_bytes() == b"conflicting Markdown bytes"


def test_assess_reports_integrity_conflict_without_replacing_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    success = capsys.readouterr()
    identity = json.loads(success.out)["record_content_identity"]
    target = workspace / "output" / f"sha256-{identity[7:]}.json"
    target.write_bytes(b"conflicting bytes")

    assert main(["assess", str(workspace), "--json"]) == ExitCode.PERSISTENCE_FAILED
    failure = capsys.readouterr()
    payload = json.loads(failure.out)

    assert payload["status"] == "persistence-failed"
    assert payload["diagnostics"][0]["id"] == "decision-record-integrity-conflict"
    assert target.read_bytes() == b"conflicting bytes"
