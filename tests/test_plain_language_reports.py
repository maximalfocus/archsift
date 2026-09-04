"""Reader-facing register of the Markdown and HTML reports (NFR-011, FR-011, FR-016)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from archsift import vocabulary
from archsift.cli import main
from archsift.decision import ArchitectureVerdict
from archsift.diagnostics import ExitCode
from archsift.html_report import render_detailed_html_report
from archsift.rules import list_rules
from archsift.validation import ControlClass, DecisionArea, EvidenceKind
from archsift.vocabulary import VocabularyError, excluded_words_in

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"

_INTERNAL_TOKENS = (
    *(verdict.value for verdict in ArchitectureVerdict),
    *(control_class.value for control_class in ControlClass),
    *(area.value for area in DecisionArea),
    "evidence-complete",
    "evidence-incomplete",
    "require-evidence",
    "support-candidate",
    "constrain-autonomy",
    "non-decisive",
    "known-gap",
    "dossier",
    "ledger",
)


def _narrative_and_appendix(markdown: str) -> tuple[str, str]:
    narrative, _, appendix = markdown.partition("\n## Traceability Appendix\n")
    assert appendix, "the Markdown report has no traceability appendix"
    return narrative, appendix


def _html_parts(html: str) -> tuple[str, str]:
    narrative, _, appendix = html.partition("<h2>Traceability Appendix</h2>")
    assert appendix, "the HTML report has no traceability appendix"
    return narrative, appendix


def _assess_example(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> tuple[Path, dict[str, Any]]:
    workspace = tmp_path / name
    shutil.copytree(EXAMPLES / name, workspace)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    record = json.loads(capsys.readouterr().out)
    return workspace, record


def _forbidden_in_narrative(record: dict[str, Any], text: str) -> list[str]:
    hits: list[str] = []
    dossier = record["dossier"]
    for rule in list_rules():
        if re.search(rf"\b{re.escape(rule.id)}\b", text):
            hits.append(f"rule id {rule.id}")
    for evidence_id in record["evidence_links"]:
        if re.search(rf"\b{re.escape(evidence_id)}\b", text):
            hits.append(f"evidence id {evidence_id}")
    if re.search(r"\bN?FR-\d{3}\b", text):
        hits.append("requirement id")
    if "$." in text:
        hits.append("field path")
    for token in _INTERNAL_TOKENS:
        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text):
            hits.append(f"token {token}")
    for section in (
        "candidate_comparison",
        "problem_value",
        "agency_necessity",
        "autonomy_permission",
    ):
        if section in text:
            hits.append(f"field {section}")
    problem = dossier.get("problem_value") or {}
    for element in problem.get("outcomes", []):
        if re.search(rf"(?<![\w-]){re.escape(element['id'])}(?![\w-])", text):
            hits.append(f"outcome id {element['id']}")
    return hits


@pytest.mark.parametrize(
    "example",
    ["fixed-workflow", "agentic-control", "insufficient-evidence", "no-technology-change"],
)
def test_narratives_carry_no_internal_identifier_and_the_appendix_keeps_the_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    workspace, record = _assess_example(tmp_path, example, capsys)
    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    narrative, appendix = _narrative_and_appendix(markdown)

    assert _forbidden_in_narrative(record, narrative) == []
    assert excluded_words_in(re.sub(r"^    .*$", "", narrative, flags=re.M)) == ()
    # Authored names replace identifiers.
    for candidate in record["dossier"]["candidate_comparison"]["candidates"]:
        assert candidate["name"] in narrative
    # The appendix keeps every internal identifier the record carries.
    assert record["record_content_identity"] in appendix
    for rule_id in {finding["rule_id"] for finding in record["unresolved_gaps"]}:
        assert rule_id in appendix
    for evidence_id in record["evidence_links"]:
        assert evidence_id in appendix
    assert record["assessment"]["verdict"] in appendix
    assert f"Vocabulary Version**\n\n    {vocabulary.VOCABULARY_VERSION}" in appendix

    html = render_detailed_html_report(record).decode("utf-8")
    html_narrative, html_appendix = _html_parts(html)
    assert _forbidden_in_narrative(record, html_narrative) == []
    assert record["record_content_identity"] in html_appendix
    assert record["assessment"]["verdict"] in html_appendix


def test_narrative_speaks_through_the_vocabulary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, record = _assess_example(tmp_path, "fixed-workflow", capsys)
    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (workspace / "output" / f"sha256-{identity}.md").read_text(encoding="utf-8")
    narrative, _ = _narrative_and_appendix(markdown)

    assert vocabulary.VERDICTS[ArchitectureVerdict.SUPPORTED].capitalize() in narrative
    assert vocabulary.OPTIONS[ControlClass.FIXED_AI_WORKFLOW].capitalize() in narrative
    assert vocabulary.DECISION_OWNER_STATEMENT in narrative
    for area in DecisionArea:
        assert f"## {vocabulary.QUESTIONS[area]}" in narrative
    assert "stop flag" in narrative and "fit flag" in narrative
    assert vocabulary.EVIDENCE_KINDS[EvidenceKind.OBSERVED] in narrative
    # A resolved rule message names the authored element, not its identifier.
    assert (
        "The recorded evidence shows Fictional human review does not reach the required outcome"
        in narrative
    )
    assert "## Who may act, action by action" in narrative


def test_rendering_fails_closed_on_an_unmapped_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import MappingProxyType

    incomplete = {
        key: value for key, value in vocabulary.RULES.items() if key != "binding-outcome-failed"
    }
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(incomplete))
    record = json.loads((GOLDEN / "decision-record-positive-v1.json").read_bytes())
    with pytest.raises(VocabularyError, match="binding-outcome-failed"):
        render_detailed_html_report(record)


def test_rendering_is_addressed_by_the_vocabulary_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = json.loads((GOLDEN / "decision-record-positive-v1.json").read_bytes())
    before = render_detailed_html_report(record)
    assert before == render_detailed_html_report(record)
    monkeypatch.setattr("archsift.narrative.VOCABULARY_VERSION", "9.9.9-test")
    after = render_detailed_html_report(record)
    assert after != before
    assert b"9.9.9-test" in after
    # The record itself is untouched by the vocabulary.
    assert record["record_content_identity"] in after.decode("utf-8")
