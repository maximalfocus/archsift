from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.knowledge_graph import NodeKind, RelationKind

_GOLDEN = Path(__file__).parent / "golden" / "graph-snapshot-v1.json"


def _write_snapshot(directory: Path, content: bytes | None = None) -> Path:
    path = directory / "snapshot.json"
    path.write_bytes(_GOLDEN.read_bytes() if content is None else content)
    return path


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> bytes:
    payload = cast(dict[str, Any], json.loads(_GOLDEN.read_bytes()))
    mutate(payload)
    return canonical_json_bytes(payload)


def test_graph_snapshot_reports_identifiers_and_counts_in_both_output_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["graph-snapshot", "snapshot.json"]) == ExitCode.SUCCESS
    human = capsys.readouterr()
    payload = json.loads(_GOLDEN.read_bytes())
    assert payload["graph_version"] in human.out
    assert payload["snapshot_content_identity"] in human.out
    assert "11 nodes" in human.out
    assert "7 relations" in human.out
    assert human.err == ""

    assert main(["graph-snapshot", "snapshot.json", "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "valid"
    assert output["exit_code"] == 0
    assert output["graph_schema_version"] == payload["graph_schema_version"]
    assert output["graph_version"] == payload["graph_version"]
    assert output["snapshot_content_identity"] == payload["snapshot_content_identity"]
    assert output["node_count"] == 11
    assert output["relation_count"] == 7
    assert set(output["node_counts_by_kind"]) == {kind.value for kind in NodeKind}
    assert output["node_counts_by_kind"]["evidence-source"] == 2
    assert output["node_counts_by_kind"]["theory"] == 2
    assert all(
        count == 1
        for kind, count in output["node_counts_by_kind"].items()
        if kind not in {"evidence-source", "theory"}
    )
    assert output["relation_counts_by_kind"] == {kind.value: 1 for kind in RelationKind}


@pytest.mark.parametrize(
    ("content", "exit_code", "diagnostic_id"),
    [
        (
            _mutated(lambda payload: payload["nodes"][0].__setitem__("kind", "unknown-kind")),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-malformed-snapshot",
        ),
        (
            _mutated(
                lambda payload: payload["relations"][0].__setitem__("subject_id", "source-primary")
            ),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-undefined-relation",
        ),
        (
            _mutated(lambda payload: payload["nodes"][2].__setitem__("citations", [])),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-missing-provenance",
        ),
        (
            _mutated(
                lambda payload: payload.__setitem__(
                    "snapshot_content_identity", f"sha256:{'0' * 64}"
                )
            ),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-identity-mismatch",
        ),
        (
            _mutated(lambda payload: payload.__setitem__("graph_version", f"gv1:{'0' * 64}")),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-identity-mismatch",
        ),
        (
            (
                json.dumps(json.loads(_GOLDEN.read_bytes()), sort_keys=True, indent=2) + "\n"
            ).encode(),
            ExitCode.VALIDATION_FAILED,
            "graph-snapshot-malformed-snapshot",
        ),
        (
            _mutated(lambda payload: payload.__setitem__("graph_schema_version", 99)),
            ExitCode.UNSUPPORTED_SCHEMA,
            "graph-snapshot-unsupported-schema",
        ),
        (
            b"{not json}\n",
            ExitCode.MALFORMED_INPUT,
            "graph-snapshot-invalid-json",
        ),
        (
            b'{"graph_schema_version":1,"graph_schema_version":1}\n',
            ExitCode.MALFORMED_INPUT,
            "graph-snapshot-invalid-json",
        ),
    ],
)
def test_graph_snapshot_contract_failures_have_stable_diagnostics(
    content: bytes,
    exit_code: ExitCode,
    diagnostic_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_snapshot(tmp_path, content)
    monkeypatch.chdir(tmp_path)

    assert main(["graph-snapshot", "snapshot.json", "--json"]) == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output["exit_code"] == exit_code
    assert output["diagnostics"][0]["id"] == diagnostic_id
    assert output["diagnostics"][0]["file"] == "snapshot.json"
    assert output["diagnostics"][0]["field"]
    assert output["diagnostics"][0]["requirement"] == "FR-015"
    assert output["diagnostics"][0]["remediation"]


def test_graph_snapshot_refuses_missing_outside_and_non_file_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = _write_snapshot(tmp_path)
    directory = root / "directory.json"
    directory.mkdir()
    monkeypatch.chdir(root)

    assert main(["graph-snapshot", "missing.json", "--json"]) == ExitCode.ARTEFACT_UNAVAILABLE
    missing = json.loads(capsys.readouterr().out)
    assert missing["diagnostics"][0]["id"] == "graph-snapshot-target-missing"

    assert main(["graph-snapshot", str(outside), "--json"]) == ExitCode.UNSAFE_PATH
    escaped = json.loads(capsys.readouterr().out)
    assert escaped["diagnostics"][0]["id"] == "graph-snapshot-target-outside-root"

    assert main(["graph-snapshot", "directory.json", "--json"]) == ExitCode.UNSAFE_PATH
    non_file = json.loads(capsys.readouterr().out)
    assert non_file["diagnostics"][0]["id"] == "graph-snapshot-target-not-regular"


def test_graph_snapshot_classifies_an_unreadable_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)

    def unreadable(*args: object, **kwargs: object) -> int:
        raise PermissionError("synthetic unreadable file")

    monkeypatch.setattr("archsift.knowledge_graph.os.open", unreadable)

    assert main(["graph-snapshot", "snapshot.json", "--json"]) == ExitCode.ARTEFACT_UNAVAILABLE
    output = json.loads(capsys.readouterr().out)
    assert output["diagnostics"][0]["id"] == "graph-snapshot-target-unreadable"


def test_graph_snapshot_is_read_only_and_quiet_suppresses_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _write_snapshot(tmp_path)
    before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in tmp_path.iterdir()
    }
    monkeypatch.chdir(tmp_path)

    assert main(["graph-snapshot", "snapshot.json", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")
    after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in tmp_path.iterdir()
    }
    assert after == before
    assert snapshot.read_bytes() == _GOLDEN.read_bytes()

    snapshot.write_bytes(b"not json\n")
    assert main(["graph-snapshot", "snapshot.json", "--quiet"]) == ExitCode.MALFORMED_INPUT
    assert capsys.readouterr() == ("", "")


def test_graph_snapshot_json_and_quiet_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as failure:
        main(["graph-snapshot", str(tmp_path / "snapshot.json"), "--json", "--quiet"])
    assert failure.value.code == ExitCode.USAGE
