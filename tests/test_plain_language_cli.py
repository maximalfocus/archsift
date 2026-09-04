"""The concise human CLI output speaks the plain-language register (NFR-011)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from archsift import vocabulary
from archsift.cli import main
from archsift.decision import ArchitectureVerdict, EvidenceState
from archsift.diagnostics import ExitCode
from archsift.rules import RULESET_VERSION, list_rules
from archsift.validation import ControlClass, DecisionArea

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
_EXAMPLES = ("fixed-workflow", "agentic-control", "insufficient-evidence", "no-technology-change")

_TOKENS = (
    *(verdict.value for verdict in ArchitectureVerdict),
    *(state.value for state in EvidenceState),
    *(control_class.value for control_class in ControlClass),
    *(area.value for area in DecisionArea),
    "dossier",
    "ledger",
    "schema",
)


def _copy(tmp_path: Path, name: str) -> Path:
    workspace = tmp_path / name
    shutil.copytree(EXAMPLES / name, workspace)
    return workspace


def _prose(line: str) -> str:
    """Return a human line without its FR-012 trace suffix and record paths."""
    line = re.sub(r"\[trace: [^\]]*\]", "", line)
    return re.sub(r"sha256:[0-9a-f]{64}|output/sha256-[0-9a-f]{64}\.\w+", "", line)


def _forbidden(text: str) -> list[str]:
    hits: list[str] = []
    for token in _TOKENS:
        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text, re.IGNORECASE):
            hits.append(token)
    for rule in list_rules():
        if re.search(rf"\b{re.escape(rule.id)}\b", text):
            hits.append(rule.id)
    if "$." in text:
        hits.append("field path")
    if re.search(r"\bN?FR-\d{3}\b", text):
        hits.append("requirement id")
    return hits


@pytest.mark.parametrize("example", _EXAMPLES)
def test_assess_prerequisites_and_validate_speak_the_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    workspace = _copy(tmp_path, example)

    assert main(["validate", str(workspace)]) == ExitCode.SUCCESS
    validated = capsys.readouterr().out.splitlines()
    assert validated[0] == "Valid case file: case.yaml (format 1)"
    assert _forbidden(_prose(validated[0])) == []

    assert main(["prerequisites", str(workspace)]) == ExitCode.SUCCESS
    readiness = capsys.readouterr().out.splitlines()
    assert readiness[0].startswith(("Ready for assessment:", "Not yet ready for assessment:"))
    assert readiness[0].endswith(f"(case file format 1; rules {RULESET_VERSION}).")
    for line in readiness:
        assert _forbidden(_prose(line)) == [], line

    assert main(["assess", str(workspace)]) == ExitCode.SUCCESS
    result = capsys.readouterr().out.rstrip("\n")
    assert result.startswith("Result: ")
    assert " Record sha256:" in result and "; report -> output/sha256-" in result
    assert _forbidden(_prose(result)) == [], result
    record = json.loads(next((workspace / "output").glob("sha256-*.json")).read_bytes())
    verdict = ArchitectureVerdict(record["assessment"]["verdict"])
    assert vocabulary.VERDICTS[verdict] in result.lower()
    recommended = record["assessment"]["recommended_class"]
    if recommended is None:
        assert "Indicated option:" not in result
    else:
        option = vocabulary.OPTIONS[ControlClass(recommended)]
        assert f" Indicated option: {option}." in result


def test_prerequisites_lists_every_gap_through_the_vocabulary_without_authored_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _copy(tmp_path, "fixed-workflow")
    dossier: dict[str, Any] = yaml.safe_load((workspace / "case.yaml").read_text(encoding="utf-8"))
    dossier["case"]["title"] = "Authored title must not render"
    candidate = dossier["candidate_comparison"]["candidates"][1]
    candidate["name"] = "Authored option name must not render"
    candidate["outcome_tests"][0]["result"] = "unknown"
    dossier["candidate_comparison"]["comparisons"][0]["dimensions"]["cost"]["result"] = "unknown"
    (workspace / "case.yaml").write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    worklist = json.loads(capsys.readouterr().out)
    assert worklist["complete"] is False

    assert main(["prerequisites", str(workspace)]) == ExitCode.SUCCESS
    lines = capsys.readouterr().out.splitlines()

    count = len(worklist["findings"])
    gaps = "1 gap" if count == 1 else f"{count} gaps"
    assert lines[0] == (
        f"Not yet ready for assessment: {gaps} outstanding "
        f"(case file format 1; rules {worklist['ruleset_version']})."
    )
    assert len(lines) == 1 + count
    for line, finding in zip(lines[1:], worklist["findings"], strict=True):
        phrases = vocabulary.rule_phrases(finding["rule_id"])
        assert line == (
            f"{phrases.flag} flag: {phrases.remediation} "
            f"[trace: {finding['rule_id']} {finding['field']}]"
        )
        assert _forbidden(_prose(line)) == [], line
    assert "Authored" not in "\n".join(lines)
    assert vocabulary.excluded_words_in("\n".join(_prose(line) for line in lines)) == ()


def test_compare_states_both_results_as_phrases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    old_workspace = _copy(tmp_path, "fixed-workflow")
    new_workspace = _copy(tmp_path, "insufficient-evidence")
    for workspace in (old_workspace, new_workspace):
        assert main(["assess", str(workspace), "--quiet"]) == ExitCode.SUCCESS
    old = next((old_workspace / "output").glob("sha256-*.json"))
    new = next((new_workspace / "output").glob("sha256-*.json"))
    monkeypatch.chdir(tmp_path)

    assert main(["compare", str(old.relative_to(tmp_path)), str(new.relative_to(tmp_path))]) == (
        ExitCode.SUCCESS
    )
    lines = capsys.readouterr().out.splitlines()

    assert lines[0].startswith("Compared sha256:")
    assert lines[1] == (
        f"Result: {vocabulary.VERDICTS[ArchitectureVerdict.SUPPORTED]} -> "
        f"{vocabulary.VERDICTS[ArchitectureVerdict.INSUFFICIENT_EVIDENCE]}"
    )
    assert lines[2].startswith("Evidence: ")
    assert _forbidden("\n".join(_prose(line) for line in lines)) == []


def test_machine_output_and_exit_codes_are_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _copy(tmp_path, "insufficient-evidence")

    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
    worklist = json.loads(capsys.readouterr().out)
    assert set(worklist) == {
        "complete",
        "dossier_content_identity",
        "dossier_schema_version",
        "findings",
        "prerequisite_worklist_schema_version",
        "ruleset_version",
    }
    assert main(["validate", str(workspace), "--json"]) == ExitCode.SUCCESS
    validated = json.loads(capsys.readouterr().out)
    assert validated["status"] == "valid" and validated["schema_version"] == 1
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = json.loads(capsys.readouterr().out)
    assert record["assessment"]["verdict"] == "insufficient-evidence"
    assert main(["assess", str(workspace), "--quiet"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == ""


def test_human_output_fails_closed_on_an_unmapped_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _copy(tmp_path, "insufficient-evidence")
    incomplete = {
        key: value
        for key, value in vocabulary.RULES.items()
        if key != "candidate-test-result-unknown"
    }
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(incomplete))

    assert main(["prerequisites", str(workspace)]) == ExitCode.INTERNAL_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("internal-error [FR-012]")
    # The machine-readable worklist does not depend on the vocabulary.
    assert main(["prerequisites", str(workspace), "--json"]) == ExitCode.SUCCESS
