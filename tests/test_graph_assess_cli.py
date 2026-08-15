from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from archsift.canonical import JsonObject, canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode

_REPOSITORY = Path(__file__).parent.parent
_SNAPSHOT = Path(__file__).parent / "golden" / "graph-snapshot-v1.json"
_FINDING_RULE_ID = "agentic-agency-fact-non-decisive"
_REQUEST: JsonObject = {
    "bindings": [{"finding_id": _FINDING_RULE_ID, "rule_id": "agency-necessity-rule"}],
    "finding_ids": [_FINDING_RULE_ID],
    "request_schema_version": 1,
    "root_ids": ["runtime-agency"],
}


def _inputs(root: Path, *, request: JsonObject = _REQUEST) -> Path:
    workspace = root / "case"
    shutil.copytree(_REPOSITORY / "examples" / "fixed-workflow", workspace)
    (root / "snapshot.json").write_bytes(_SNAPSHOT.read_bytes())
    (root / "request.json").write_bytes(canonical_json_bytes(request))
    return workspace


def test_assess_binds_only_finding_relevant_graph_content_without_changing_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    snapshot_before = (tmp_path / "snapshot.json").read_bytes()
    request_before = (tmp_path / "request.json").read_bytes()

    assert main(["assess", "case", "--json"]) == ExitCode.SUCCESS
    baseline_bytes = capsys.readouterr().out.encode("ascii")
    baseline = json.loads(baseline_bytes)
    assert "graph_use" not in baseline

    command = [
        "assess",
        "case",
        "--graph-snapshot",
        "snapshot.json",
        "--graph-request",
        "request.json",
        "--json",
    ]
    assert main(command) == ExitCode.SUCCESS
    graph_bytes = capsys.readouterr().out.encode("ascii")
    graph_record = json.loads(graph_bytes)
    graph_use = graph_record["graph_use"]

    assert graph_record["assessment"] == baseline["assessment"]
    assert graph_record["record_content_identity"] != baseline["record_content_identity"]
    assert graph_use["graph_schema_version"] == 1
    assert graph_use["graph_version"].startswith("gv1:")
    assert graph_use["graph_snapshot_content_identity"].startswith("sha256:")
    assert graph_use["case_view_content_identity"].startswith("sha256:")
    assert graph_use["supported_finding_rule_ids"] == [_FINDING_RULE_ID]
    assert [item["id"] for item in graph_use["finding_relevant_nodes"]] == sorted(
        item["id"] for item in graph_use["finding_relevant_nodes"]
    )
    assert {item["id"] for item in graph_use["finding_relevant_nodes"]} >= {
        "agency-necessity-rule",
        "agency-needs-unpredictable-steps",
    }
    assert graph_use["finding_relevant_relations"]
    assert all(
        item["content_identity"].startswith("sha256:")
        for name in ("finding_relevant_nodes", "finding_relevant_relations")
        for item in graph_use[name]
    )

    target = workspace / "output" / f"sha256-{graph_record['record_content_identity'][7:]}.json"
    markdown = target.with_suffix(".md").read_text(encoding="utf-8")
    assert "## Graph Use" in markdown
    assert graph_use["graph_version"] in markdown
    assert graph_use["graph_snapshot_content_identity"] in markdown

    assert main(["report", str(target), "--format", "html", "--level", "detailed", "--json"]) == 0
    rendered = json.loads(capsys.readouterr().out)["report"]
    html = (tmp_path / rendered).read_text(encoding="utf-8")
    assert "<h2>Graph Use</h2>" in html
    assert graph_use["case_view_content_identity"] in html

    assert main(command) == ExitCode.SUCCESS
    assert capsys.readouterr().out.encode("ascii") == graph_bytes
    assert (tmp_path / "snapshot.json").read_bytes() == snapshot_before
    assert (tmp_path / "request.json").read_bytes() == request_before

    assert main(["assess", "case", "--json"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out.encode("ascii") == baseline_bytes


def test_assess_requires_paired_graph_options_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as failure:
        main(["assess", "case", "--graph-snapshot", "snapshot.json", "--json"])

    assert failure.value.code == ExitCode.USAGE
    assert list((workspace / "output").iterdir()) == [workspace / "output" / ".gitkeep"]


def test_assess_refuses_a_graph_label_that_is_not_an_emitted_finding_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = {
        **_REQUEST,
        "bindings": [{"finding_id": "private-label", "rule_id": "agency-necessity-rule"}],
        "finding_ids": ["private-label"],
    }
    workspace = _inputs(tmp_path, request=invalid)
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "assess",
                "case",
                "--graph-snapshot",
                "snapshot.json",
                "--graph-request",
                "request.json",
                "--json",
            ]
        )
        == ExitCode.VALIDATION_FAILED
    )
    payload = json.loads(capsys.readouterr().out)
    diagnostic = payload["diagnostics"][0]
    assert diagnostic["id"] == "assess-graph-invalid-binding"
    assert diagnostic["file"] == "request.json"
    assert diagnostic["requirement"] == "FR-011/FR-015"
    assert list((workspace / "output").iterdir()) == [workspace / "output" / ".gitkeep"]


@pytest.mark.parametrize(
    ("content", "exit_code", "diagnostic"),
    [
        (b"{not json}\n", 10, "assess-graph-invalid-json"),
        (
            canonical_json_bytes({**_REQUEST, "request_schema_version": 99}),
            11,
            "assess-graph-unsupported-schema",
        ),
    ],
)
def test_assess_classifies_malformed_and_unsupported_graph_requests(
    content: bytes,
    exit_code: int,
    diagnostic: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _inputs(tmp_path)
    (tmp_path / "request.json").write_bytes(content)
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "assess",
                "case",
                "--graph-snapshot",
                "snapshot.json",
                "--graph-request",
                "request.json",
                "--json",
            ]
        )
        == exit_code
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["id"] == diagnostic
    assert payload["diagnostics"][0]["requirement"] == "FR-011/FR-015"
    assert list((workspace / "output").iterdir()) == [workspace / "output" / ".gitkeep"]


@pytest.mark.parametrize(
    ("snapshot", "request_path", "exit_code", "diagnostic"),
    [
        ("snapshot.json", "missing.json", 14, "assess-graph-target-missing"),
        ("../snapshot.json", "request.json", 13, "assess-graph-target-outside-root"),
    ],
)
def test_assess_classifies_unavailable_and_unsafe_graph_inputs(
    snapshot: str,
    request_path: str,
    exit_code: int,
    diagnostic: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _inputs(tmp_path)
    root = tmp_path / "root" if snapshot.startswith("..") else tmp_path
    if root != tmp_path:
        root.mkdir()
        shutil.move(str(workspace), root / "case")
        workspace = root / "case"
        shutil.move(str(tmp_path / "request.json"), root / "request.json")
    monkeypatch.chdir(root)

    assert (
        main(
            [
                "assess",
                "case",
                "--graph-snapshot",
                snapshot,
                "--graph-request",
                request_path,
                "--json",
            ]
        )
        == exit_code
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["id"] == diagnostic
    assert payload["diagnostics"][0]["requirement"] == "FR-011/FR-015"
    assert list((workspace / "output").iterdir()) == [workspace / "output" / ".gitkeep"]
