"""The executive summary's reader-facing register (FR-017, NFR-011).

Independently authored checks over the packaged synthetic examples: exactly
three parts in both formats, no forbidden part or identifier class, identical
facts across formats, fail-closed rendering on an unmapped term, and a rendering
addressed by the vocabulary version.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any
from xml.etree import ElementTree

import pytest

from archsift import vocabulary
from archsift.cli import main
from archsift.decision import ArchitectureVerdict
from archsift.diagnostics import ExitCode
from archsift.executive_summary import PART_TITLES, build_executive_summary
from archsift.framework import CARD_TITLE
from archsift.html_report import render_executive_html_report
from archsift.pptx_report import render_executive_pptx_report
from archsift.rules import list_rules
from archsift.validation import ControlClass, DecisionArea
from archsift.vocabulary import VocabularyError

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"
_EXAMPLES = ("fixed-workflow", "agentic-control", "insufficient-evidence", "no-technology-change")

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
    "verdict",
    "trade-off",
)

# Headings and labels the earlier, record-shaped summary carried and the
# three-part summary must not.
_FORBIDDEN_PARTS = (
    "Case and Task Boundary",
    "Case ID",
    "Verdict",
    "Verdict Rule",
    "Decision Space",
    "Candidate",
    "Vetoes and Mandatory Human Controls",
    "Assistance Envelope",
    "Abstention Scope",
    "Evidence State",
    "Material Gap",
    "Decisive Trade-offs",
    "Trade-off",
    "Traceability Appendix",
    "Observed",
    "Assumption",
    "Estimate",
    "Missing",
)

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _assess_example(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    workspace = tmp_path / name
    shutil.copytree(EXAMPLES / name, workspace)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return json.loads(capsys.readouterr().out)


def _forbidden(record: dict[str, Any], text: str) -> list[str]:
    hits: list[str] = []
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
        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text, re.IGNORECASE):
            hits.append(f"token {token}")
    for section in (
        "candidate_comparison",
        "problem_value",
        "agency_necessity",
        "autonomy_permission",
    ):
        if section in text:
            hits.append(f"field {section}")
    problem = record["dossier"].get("problem_value") or {}
    for element in problem.get("outcomes", []):
        if re.search(rf"(?<![\w-]){re.escape(element['id'])}(?![\w-])", text):
            hits.append(f"outcome id {element['id']}")
    for label in _FORBIDDEN_PARTS:
        if re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", text):
            hits.append(f"part {label}")
    return hits


def _slides(deck: bytes) -> list[list[str]]:
    slides: list[list[str]] = []
    with zipfile.ZipFile(BytesIO(deck)) as archive:
        names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.findall(r"\d+", name)[0]),
        )
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            slides.append([node.text or "" for node in root.iter(f"{_A}t")])
    return slides


@pytest.mark.parametrize("example", _EXAMPLES)
def test_both_formats_tell_exactly_three_parts_with_no_identifier_and_no_appendix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    record = _assess_example(tmp_path, example, capsys)

    summary = build_executive_summary(record)
    assert [part.title for part in summary.parts] == list(PART_TITLES)
    statements = "\n".join(
        f"{statement.label}: {statement.text}"
        for part in summary.parts
        for statement in part.statements
    )
    assert _forbidden(record, statements) == []
    # Every authored option is named, as are the task and its actions.
    for candidate in record["dossier"]["candidate_comparison"]["candidates"]:
        assert candidate["name"] in statements
    assert record["dossier"]["task"]["operation"].rstrip(".") in statements
    for action in record["dossier"]["task"]["actions"]:
        assert action["description"].rstrip(".") in statements

    html = render_executive_html_report(record).decode("utf-8")
    body = html.split("<body>", 1)[1]
    narrative, _, footer = body.partition('<footer class="notice">')
    assert footer, "the executive HTML has no footer"
    assert re.findall(r"<h2>(.*?)</h2>", body) == [*PART_TITLES, CARD_TITLE]
    assert body.count('<section class="part">') == 3
    assert body.count('<section class="reference">') == 1
    assert _forbidden(record, narrative) == []
    assert "Traceability" not in body
    assert record["record_content_identity"] in footer
    assert vocabulary.VOCABULARY_VERSION in footer

    slides = _slides(render_executive_pptx_report(record))
    titles = [slide[0] for slide in slides]
    assert titles[0] == "ArchSift Executive Summary" and titles[-1] == "Masking Notice"
    pages = (*PART_TITLES, CARD_TITLE)
    assert [title for title in titles if title in pages] == list(pages)
    assert all(title in pages or title.endswith(" (continued)") for title in titles[1:-1]), titles
    deck_text = "\n".join(run for slide in slides[1:-1] for run in slide)
    assert _forbidden(record, deck_text) == []


@pytest.mark.parametrize("example", _EXAMPLES)
def test_both_formats_state_identical_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    record = _assess_example(tmp_path, example, capsys)
    summary = build_executive_summary(record)
    html = render_executive_html_report(record).decode("utf-8")
    deck_runs = {run for slide in _slides(render_executive_pptx_report(record)) for run in slide}

    for part in summary.parts:
        for statement in part.statements:
            assert f"<dt>{statement.label}</dt>" in html, statement.label
            assert f"{statement.label}: {statement.text}" in deck_runs, statement.label
    # The HTML paragraph text of the three parts is exactly the statements.
    parts_html = html.split('<section class="reference">', 1)[0]
    paragraphs = re.findall(r'<dd><p class="value">(.*?)</p></dd>', parts_html)
    statements = [statement.text for part in summary.parts for statement in part.statements]
    assert len(paragraphs) == len(statements)


def test_rendering_fails_closed_on_an_unmapped_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    incomplete = {
        key: value for key, value in vocabulary.RULES.items() if key != "binding-outcome-failed"
    }
    monkeypatch.setattr(vocabulary, "RULES", MappingProxyType(incomplete))
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())

    with pytest.raises(VocabularyError, match="binding-outcome-failed"):
        render_executive_html_report(record)
    with pytest.raises(VocabularyError, match="binding-outcome-failed"):
        render_executive_pptx_report(record)


def test_rendering_fails_closed_on_an_unmapped_disposition() -> None:
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())
    record["assessment"]["ordered_elimination_evaluation"]["candidates"][0]["disposition"] = (
        "shelved"
    )

    with pytest.raises(VocabularyError, match="shelved"):
        build_executive_summary(record)


def test_rendering_is_addressed_by_the_record_identity_and_the_vocabulary_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())
    html_before = render_executive_html_report(record)
    deck_before = render_executive_pptx_report(record)
    assert html_before == render_executive_html_report(record)
    assert deck_before == render_executive_pptx_report(record)

    monkeypatch.setattr(vocabulary, "VOCABULARY_VERSION", "9.9.9-test")

    html_after = render_executive_html_report(record)
    deck_after = render_executive_pptx_report(record)
    assert html_after != html_before and deck_after != deck_before
    assert b"9.9.9-test" in html_after
    assert any("9.9.9-test" in run for slide in _slides(deck_after) for run in slide)
    assert record["record_content_identity"].encode() in html_after
