from __future__ import annotations

import json
from pathlib import Path

import pytest

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode

_SNAPSHOT = Path(__file__).parent / "golden" / "graph-snapshot-v1.json"
_REQUEST: JsonObject = {
    "bindings": [{"finding_id": "finding-agency", "rule_id": "agency-necessity-rule"}],
    "finding_ids": ["finding-agency"],
    "request_schema_version": 1,
    "root_ids": ["runtime-agency"],
}


def _inputs(root: Path, request: bytes | None = None) -> None:
    (root / "snapshot.json").write_bytes(_SNAPSHOT.read_bytes())
    (root / "request.json").write_bytes(
        canonical_json_bytes(_REQUEST) if request is None else request
    )


def test_graph_view_reports_a_deterministic_private_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["graph-view", "snapshot.json", "request.json"]) == ExitCode.SUCCESS
    human = capsys.readouterr()
    assert "private findings" in human.out and "reusable-knowledge gaps" in human.out
    assert human.err == ""

    assert main(["graph-view", "snapshot.json", "request.json", "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "valid"
    assert output["case_view_content_identity"].startswith("sha256:")
    view = output["case_view"]
    assert view["case_finding_ids"] == ["finding-agency"]
    assert view["graph_snapshot_content_identity"].startswith("sha256:")
    assert view["reusable_claim_traces"]
    assert view["conflict_relation_ids"]
    assert view["reusable_knowledge_gap_claim_ids"]


@pytest.mark.parametrize(
    ("request_content", "exit_code", "diagnostic"),
    [
        (b"{not json}\n", ExitCode.MALFORMED_INPUT, "graph-view-invalid-json"),
        (
            canonical_json_bytes({**_REQUEST, "request_schema_version": 99}),
            ExitCode.UNSUPPORTED_SCHEMA,
            "graph-view-unsupported-schema",
        ),
        (
            (json.dumps(_REQUEST, indent=2, sort_keys=True) + "\n").encode(),
            ExitCode.VALIDATION_FAILED,
            "graph-view-malformed-request",
        ),
        (
            canonical_json_bytes({**_REQUEST, "root_ids": ["absent"]}),
            ExitCode.VALIDATION_FAILED,
            "graph-view-unknown-root",
        ),
    ],
)
def test_graph_view_request_failures_are_classified(
    request_content: bytes,
    exit_code: ExitCode,
    diagnostic: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _inputs(tmp_path, request_content)
    monkeypatch.chdir(tmp_path)

    assert main(["graph-view", "snapshot.json", "request.json", "--json"]) == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output["diagnostics"][0]["id"] == diagnostic
    assert output["diagnostics"][0]["file"] == "request.json"
    assert output["diagnostics"][0]["requirement"] == "FR-015"
    assert output["diagnostics"][0]["field"]
    assert output["diagnostics"][0]["remediation"]


def test_graph_view_enforces_contained_paths_and_unavailable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _inputs(tmp_path)
    monkeypatch.chdir(root)

    assert (
        main(["graph-view", "../snapshot.json", "../request.json", "--json"])
        == ExitCode.UNSAFE_PATH
    )
    assert json.loads(capsys.readouterr().out)["diagnostics"][0]["file"] == "../snapshot.json"
    assert (
        main(["graph-view", "missing.json", "request.json", "--quiet"])
        == ExitCode.ARTEFACT_UNAVAILABLE
    )
    assert capsys.readouterr() == ("", "")


def test_graph_view_is_read_only_quiet_and_output_options_are_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _inputs(tmp_path)
    before = {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns) for item in tmp_path.iterdir()
    }
    monkeypatch.chdir(tmp_path)

    assert main(["graph-view", "snapshot.json", "request.json", "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")
    assert before == {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns) for item in tmp_path.iterdir()
    }
    with pytest.raises(SystemExit) as failure:
        main(["graph-view", "snapshot.json", "request.json", "--json", "--quiet"])
    assert failure.value.code == ExitCode.USAGE
