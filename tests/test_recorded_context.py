"""Decision-bearing evidence versus recorded context (FR-004, FR-011, FR-012, FR-018)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.executive_summary import build_executive_summary
from archsift.html_report import render_detailed_html_report
from archsift.validation import (
    DECISION_BEARING_CITATION_LOCATIONS,
    SUPPORTED_DOSSIER_SCHEMA_VERSIONS,
    packaged_dossier_schema,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "fixed-workflow"
GOLDEN = ROOT / "tests" / "golden"

_CONTEXT_OBSERVED = {
    "id": "context-observed",
    "claim": "A fictional operational fact that no decision field reads.",
    "owner": "Fictional evaluation team",
    "affects": ["problem-value"],
    "artefacts": [],
    "kind": "observed",
    "provenance": "Fictional observations in evidence/observations.txt.",
    "observed_at": "2026-08-08",
}
_CONTEXT_MISSING = {
    "id": "context-missing",
    "claim": "A fictional figure nobody has measured and no decision field needs.",
    "owner": "Fictional evaluation team",
    "affects": ["problem-value"],
    "artefacts": [],
    "kind": "missing",
    "resolved_by": "Measure it if a decision field ever cites it.",
}


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


def _with_context(dossier: dict[str, Any]) -> dict[str, Any]:
    dossier["evidence"] = [*dossier["evidence"], dict(_CONTEXT_OBSERVED), dict(_CONTEXT_MISSING)]
    return dossier


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    return payload


def _citation_definitions(schema: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for name, definition in schema["$defs"].items():
        if "evidence_ids" in definition.get("properties", {}):
            found.add(name)
    # Top-level properties never carry citations directly; the walk below proves it.
    for name, definition in schema["properties"].items():
        assert "evidence_ids" not in definition.get("properties", {}), name
    return found


def test_citation_location_enumeration_is_exhaustive_over_every_packaged_schema() -> None:
    enumerated = set(DECISION_BEARING_CITATION_LOCATIONS)
    assert list(DECISION_BEARING_CITATION_LOCATIONS) == sorted(enumerated)
    union: set[str] = set()
    for version in SUPPORTED_DOSSIER_SCHEMA_VERSIONS:
        schema = dict(packaged_dossier_schema(version))
        found = _citation_definitions(schema)
        assert found <= enumerated, (version, found - enumerated)
        union |= found
    assert union == enumerated


def test_validate_advises_on_uncited_entries_without_changing_the_exit_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _with_context(_load_example()))
    count = len(_load_example()["evidence"])

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = _json(capsys)
    assert payload["status"] == "valid"
    assert payload["diagnostics"] == []
    assert [(item["id"], item["field"], item["requirement"]) for item in payload["advisories"]] == [
        ("uncited-evidence-entry", f"$.evidence[{count}]", "FR-004"),
        ("uncited-evidence-entry", f"$.evidence[{count + 1}]", "FR-004"),
    ]
    assert all(
        item["file"] == "case.yaml" and item["remediation"] for item in payload["advisories"]
    )
    assert payload["assessment_prerequisites_ready"] is True

    assert main(["validate", str(workspace)]) == ExitCode.SUCCESS
    human = capsys.readouterr()
    assert human.err == ""
    lines = human.out.splitlines()
    assert lines[0].startswith("Valid ArchSift dossier")
    assert [line for line in lines[1:] if line.startswith("advisory: uncited-evidence-entry")] == (
        lines[1:]
    )
    assert len(lines) == 3

    assert main(["validate", str(workspace), "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr() == ("", "")


def test_fully_cited_dossier_raises_no_advisory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _load_example())

    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    assert _json(capsys)["advisories"] == []


def test_advisory_is_never_emitted_in_place_of_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _with_context(_load_example())
    dossier["problem_value"]["outcomes"][0]["evidence_ids"] = ["absent-evidence"]
    workspace = _workspace(tmp_path, dossier)

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    payload = _json(capsys)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"]
    assert payload["advisories"] == []


def test_record_separates_decision_bearing_evidence_from_recorded_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path, _with_context(_load_example()))

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["record_schema_version"] == 5
    assert record["assessment"]["verdict"] == "supported"
    links = record["evidence_links"]
    assert links["context-observed"]["decision_bearing"] is False
    assert links["context-missing"]["decision_bearing"] is False
    assert all(
        link["decision_bearing"] is True
        for identifier, link in links.items()
        if identifier not in {"context-observed", "context-missing"}
    )
    # No entry is dropped, and the uncited known gap is not a material gap.
    assert {entry["id"] for entry in record["dossier"]["evidence"]} == set(links)
    assert not any("context-missing" in gap["evidence_ids"] for gap in record["unresolved_gaps"])
    triggers = {item["evidence_id"]: item for item in record["reassessment_triggers"]}
    assert triggers["context-missing"]["decision_bearing"] is False
    assert triggers["context-missing"]["kind"] == "missing"

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    worklist = _json(capsys)
    assert worklist["complete"] is True and worklist["findings"] == []

    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    assert "## Recorded Context" in markdown
    context_section = markdown.split("## Recorded Context", 1)[1].split("## ", 1)[0]
    assert "context-observed" in context_section and "context-missing" in context_section

    html = render_detailed_html_report(record).decode("utf-8")
    assert "Recorded Context Evidence IDs" in html
    assert "context-observed" in html and "context-missing" in html

    summary = build_executive_summary(record)
    points = [
        (point.label, point.values)
        for section in summary.sections
        for point in section.points
        if point.label in {"Recorded Context", "Material Gap"}
    ]
    labels = [label for label, _ in points]
    assert labels.count("Recorded Context") == 2
    assert "Material Gap" not in labels


def test_cited_missing_entry_keeps_its_blocking_treatment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dossier = _with_context(_load_example())
    # Cite the known gap from a binding outcome: it becomes decision-bearing.
    dossier["problem_value"]["outcomes"][0]["evidence_ids"] = [
        "decision-observed",
        "context-missing",
    ]
    workspace = _workspace(tmp_path, dossier)

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = _json(capsys)
    assert record["evidence_links"]["context-missing"]["decision_bearing"] is True
    trigger = next(
        item for item in record["reassessment_triggers"] if item["evidence_id"] == "context-missing"
    )
    assert trigger["decision_bearing"] is True
    summary = build_executive_summary(record)
    labels = [point.label for section in summary.sections for point in section.points]
    assert "Material Gap" in labels


@pytest.mark.parametrize(
    "golden",
    [
        "decision-record-positive-v1.json",
        "decision-record-positive-v2.json",
        "decision-record-positive-v3.json",
        "decision-record-positive-v4.json",
    ],
)
def test_earlier_record_schemas_remain_readable_and_comparable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, golden: str
) -> None:
    old = json.loads((GOLDEN / golden).read_bytes())
    assert old["record_schema_version"] in {1, 2, 3, 4}
    assert "abstention_scope" not in old
    # Rendering treats every pre-schema-3 entry as decision-bearing, as before.
    assert render_detailed_html_report(old)
    summary = build_executive_summary(old)
    if old["record_schema_version"] < 3:
        assert "Recorded Context" not in [
            point.label for section in summary.sections for point in section.points
        ]

    new = json.loads((GOLDEN / "decision-record-positive-v5.json").read_bytes())
    (tmp_path / "old.json").write_bytes((GOLDEN / golden).read_bytes())
    (tmp_path / "new.json").write_bytes((GOLDEN / "decision-record-positive-v5.json").read_bytes())
    monkeypatch.chdir(tmp_path)
    assert main(["compare", "old.json", "new.json", "--json"]) == ExitCode.SUCCESS
    delta = _json(capsys)
    assert delta["new_record_identity"] == new["record_content_identity"]
