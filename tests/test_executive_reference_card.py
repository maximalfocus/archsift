"""The executive summary cites framework rules and carries the card page (FR-017, FR-020)."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from html import unescape
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any
from xml.etree import ElementTree

import pytest

from archsift import vocabulary
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.evidence_view import VIEW_TITLE
from archsift.executive_summary import PART_TITLES, build_executive_summary
from archsift.framework import CARD_TITLE, build_framework_card, card_lines
from archsift.html_report import render_executive_html_report
from archsift.pptx_report import POINTS_PER_SLIDE, render_executive_pptx_report
from archsift.rules import list_rules
from archsift.vocabulary import FRAMEWORK_MAPPING, VocabularyError

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"
_EXAMPLES = ("fixed-workflow", "agentic-control", "insufficient-evidence", "no-technology-change")
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_FLAG = re.compile(r"\b(Stop|Gap|Condition|Fit|Noted) flag(?! \(framework rule \d+\))")
_CITED = re.compile(r"\b(Stop|Gap|Condition|Fit|Noted) flag \(framework rule (\d+)\)")


def _assess(tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    workspace = tmp_path / name
    shutil.copytree(EXAMPLES / name, workspace)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return json.loads(capsys.readouterr().out)


def _slides(deck: bytes) -> list[list[str]]:
    slides: list[list[str]] = []
    with zipfile.ZipFile(BytesIO(deck)) as archive:
        names = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[0]),
        )
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            slides.append([node.text or "" for node in root.iter(f"{_A}t")])
    return slides


@pytest.mark.parametrize("example", _EXAMPLES)
def test_every_flag_cites_the_framework_rule_that_raised_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    record = _assess(tmp_path, example, capsys)
    summary = build_executive_summary(record)
    reasoning = summary.parts[2]
    flag_texts = [
        statement.text
        for statement in reasoning.statements
        if statement.label in {"Option", "The options as a whole"}
    ]

    cited = [match for text in flag_texts for match in _CITED.finditer(text)]
    # Every flag on an option is cited; the legend is fixed text and cites nothing.
    for text in flag_texts:
        assert _FLAG.search(text) is None, text
    numbers = {int(match.group(2)) for match in cited}
    valid = {rule.number for rule in vocabulary.FRAMEWORK_RULES}
    assert numbers and numbers <= valid
    # The cited numbers are exactly the mapping of the rules that fired.
    assessment = record["assessment"]
    fired = {
        finding["rule_id"]
        for evaluation in ("prerequisite_evaluation", "ordered_elimination_evaluation")
        for finding in assessment[evaluation]["findings"]
        if finding["effect"] != "non-decisive"
    }
    assert numbers == {FRAMEWORK_MAPPING[rule_id] for rule_id in fired}
    legend = next(s for s in reasoning.statements if s.label == "How to read the flags")
    assert "framework rule" not in legend.text


@pytest.mark.parametrize("example", _EXAMPLES)
def test_the_card_page_follows_the_three_parts_unchanged_in_both_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    record = _assess(tmp_path, example, capsys)
    summary = build_executive_summary(record)
    card = build_framework_card()
    assert summary.card == card
    assert summary.framework_version == card.framework_version

    html = render_executive_html_report(record).decode("utf-8")
    body = html.split("<body>", 1)[1]
    assert re.findall(r"<h2>(.*?)</h2>", body) == [*PART_TITLES, CARD_TITLE, VIEW_TITLE]
    _, _, rest = body.partition('<section class="reference">')
    page, _, remainder = rest.partition("</section>")
    # The evidence-set view page follows the card; the footer closes the document.
    assert remainder.lstrip().startswith('<section class="reference">')
    footer = remainder.split('<footer class="notice">', 1)[1]
    page_text = unescape(re.sub(r"<[^>]+>", "\n", page))
    for item in (*card.questions, *card.options, *card.flags):
        assert item.name in page_text and item.sentence in page_text, item
    for group in card.groups:
        assert group.title in page_text
        for rule in group.rules:
            assert rule.sentence in page_text, rule.number
    assert re.findall(r'<ol start="(\d+)">', page) == [
        str(group.rules[0].number) for group in card.groups
    ]
    assert card.statement in page_text
    assert f"Framework {card.framework_version}" in page_text
    for rule in list_rules():
        assert rule.id not in page_text
    assert f'<dt>Framework version</dt>\n<dd><p class="value">{card.framework_version}' in footer

    slides = _slides(render_executive_pptx_report(record))
    titles = [slide[0] for slide in slides]
    first = titles.index(CARD_TITLE)
    assert first > titles.index("Result and reasoning")
    card_slides = [
        slide for slide in slides if slide[0] in {CARD_TITLE, f"{CARD_TITLE} (continued)"}
    ]
    assert card_slides and all(len(slide) <= POINTS_PER_SLIDE + 1 for slide in card_slides)
    runs = [run for slide in card_slides for run in slide[1:]]
    assert runs == card_lines(card)[1:]
    assert titles[-1] == "Masking Notice"
    assert f"Framework: {card.framework_version}" in slides[0]


def test_rendering_is_addressed_by_the_framework_version(monkeypatch: pytest.MonkeyPatch) -> None:
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())
    html_before = render_executive_html_report(record)
    deck_before = render_executive_pptx_report(record)

    monkeypatch.setattr(vocabulary, "FRAMEWORK_VERSION", "9.9.9-test")

    html_after = render_executive_html_report(record)
    deck_after = render_executive_pptx_report(record)
    assert html_after != html_before and deck_after != deck_before
    assert b"9.9.9-test" in html_after
    assert any(run == "Framework: 9.9.9-test" for slide in _slides(deck_after) for run in slide)
    assert record["record_content_identity"].encode() in html_after


def test_rendering_fails_closed_when_a_fired_rule_has_no_framework_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())
    incomplete = {k: v for k, v in FRAMEWORK_MAPPING.items() if k != "binding-outcome-failed"}
    monkeypatch.setattr(vocabulary, "FRAMEWORK_MAPPING", MappingProxyType(incomplete))

    with pytest.raises(VocabularyError, match="binding-outcome-failed"):
        build_executive_summary(record)
    with pytest.raises(VocabularyError):
        render_executive_pptx_report(record)
