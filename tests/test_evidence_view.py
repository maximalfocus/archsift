"""The evidence-set view of a record (FR-021): one row per slot, listing and never tallying."""

from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from archsift import vocabulary
from archsift.cli import main
from archsift.decision import ArchitectureVerdict
from archsift.diagnostics import ExitCode
from archsift.evidence_set import evidence_set_profile
from archsift.evidence_view import VIEW_TITLE, build_evidence_view
from archsift.executive_summary import build_executive_summary
from archsift.html_report import render_detailed_html_report, render_executive_html_report
from archsift.masking import masked_decision_record_view
from archsift.rules import list_rules
from archsift.validation import ControlClass, DecisionArea
from archsift.vocabulary import VocabularyError, excluded_words_in

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"
_EXAMPLES = ("fixed-workflow", "agentic-control", "insufficient-evidence", "no-technology-change")
_TALLY = re.compile(r"\b(\d+ of \d+|scores?|totals?|percent(?:age)?|complete(?:ness)?:)\b|%")


def _assess(tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    workspace = tmp_path / name
    if not workspace.exists():
        shutil.copytree(EXAMPLES / name, workspace)
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return json.loads(capsys.readouterr().out)


def _strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found |= _strings(item)
    elif isinstance(value, list):
        for item in value:
            found |= _strings(item)
    elif isinstance(value, str):
        found.add(value)
    return found


def _forbidden(record: dict[str, Any], text: str) -> list[str]:
    hits: list[str] = []
    for rule in list_rules():
        if re.search(rf"\b{re.escape(rule.id)}\b", text):
            hits.append(rule.id)
    for evidence_id in record["evidence_links"]:
        if re.search(rf"\b{re.escape(evidence_id)}\b", text):
            hits.append(evidence_id)
    if "$." in text or re.search(r"\bN?FR-\d{3}\b", text):
        hits.append("path or requirement")
    for token in (
        *(v.value for v in ArchitectureVerdict),
        *(c.value for c in ControlClass),
        *(a.value for a in DecisionArea),
        "require-evidence",
        "dossier",
        "ledger",
    ):
        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text):
            hits.append(token)
    return hits


@pytest.mark.parametrize("example", _EXAMPLES)
def test_one_row_per_slot_in_profile_order_with_authored_items_and_states(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    record = _assess(tmp_path, example, capsys)
    view = build_evidence_view(masked_decision_record_view(record))
    profile = evidence_set_profile(record["dossier_schema_version"])

    assert [row.name for row in view.rows] == [slot.phrases.name for slot in profile.slots]
    assert all(row.texts for row in view.rows)
    text = "\n".join(f"{row.name}: {' '.join(row.texts)}" for row in view.rows)
    dossier = record["dossier"]
    # Every authored item is named: actions, outcomes, options with their tests, controls.
    for action in dossier["task"]["actions"]:
        assert action["description"].rstrip(".") in text
    for outcome in dossier["problem_value"]["outcomes"]:
        assert outcome["description"].rstrip(".") in text
    for candidate in dossier["candidate_comparison"]["candidates"]:
        assert candidate["name"] in text
    for control in dossier["autonomy_permission"]["mandatory_human_controls"]:
        assert control["description"].rstrip(".") in text
    # Every decision-bearing entry's claim and state appear; a context-only one does not.
    for entry in dossier["evidence"]:
        bearing = record["evidence_links"][entry["id"]].get("decision_bearing", True)
        assert (entry["claim"].rstrip(".") in text) is bearing, entry["id"]
    assert "seen and recorded from" in text or "estimated by" in text
    assert "accountable person" in text
    assert _forbidden(record, text) == []
    # The fixed text tallies nothing; authored values (a target "95 percent") are the author's.
    fixed = text
    for value in sorted(_strings(record), key=len, reverse=True):
        if len(value) > 3:
            fixed = fixed.replace(value.rstrip("."), " ")
    assert _TALLY.search(fixed) is None, _TALLY.search(fixed)
    assert view.dossier_schema_version == record["dossier_schema_version"]
    assert view.vocabulary_version == vocabulary.VOCABULARY_VERSION


def test_two_cases_from_different_material_render_the_same_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = build_evidence_view(
        masked_decision_record_view(_assess(tmp_path, "fixed-workflow", capsys))
    )
    second = build_evidence_view(
        masked_decision_record_view(_assess(tmp_path, "no-technology-change", capsys))
    )

    assert [row.name for row in first.rows] == [row.name for row in second.rows]
    assert first.rows != second.rows


def test_empty_slots_gaps_and_unacceptable_kinds_are_stated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "gaps"
    shutil.copytree(EXAMPLES / "fixed-workflow", workspace)
    dossier: dict[str, Any] = yaml.safe_load((workspace / "case.yaml").read_text(encoding="utf-8"))
    dossier["evidence"].append(
        {
            "id": "an-assumption",
            "kind": "assumption",
            "claim": "Fictional throughput is assumed adequate.",
            "owner": "Fictional owner",
            "affects": ["comparative-fit"],
            "falsified_by": "A measured throughput below the target.",
        }
    )
    candidate = dossier["candidate_comparison"]["candidates"][1]
    candidate["outcome_tests"][0]["evidence_ids"] = ["an-assumption"]
    (workspace / "case.yaml").write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")
    record = _assess(tmp_path, "gaps", capsys)
    assert record["assessment"]["verdict"] == "insufficient-evidence"

    view = build_evidence_view(masked_decision_record_view(record))
    rows = {row.name: " ".join(row.texts) for row in view.rows}
    tests_row = rows["Each option against each required outcome"]
    assert "Fictional throughput is assumed adequate: assumed" in tests_row
    assert "This kind does not count as support here" in tests_row
    assert "Gap flag (framework rule 2):" in tests_row
    assert "What would settle it:" in tests_row
    assert rows["Conditions on the result"] == "Nothing is recorded at this slot."

    incomplete = json.loads((GOLDEN / "decision-record-incomplete-v1.json").read_bytes())
    empty = build_evidence_view(masked_decision_record_view(incomplete))
    assert len(empty.rows) == 43
    assert empty.rows[0].texts[0].startswith("Gap flag (framework rule 1):")
    assert sum(row.texts == ("Nothing is recorded at this slot.",) for row in empty.rows) >= 30


@pytest.mark.parametrize("golden", ["positive-v1", "positive-v3", "positive-v5"])
def test_earlier_schema_records_render_with_their_own_profile(golden: str) -> None:
    record = json.loads((GOLDEN / f"decision-record-{golden}.json").read_bytes())
    view = build_evidence_view(masked_decision_record_view(record))
    version = record["dossier_schema_version"]

    assert len(view.rows) == len(evidence_set_profile(version).slots)
    assert ("Keeping the current way of working" in [row.name for row in view.rows]) is (
        version >= 4
    )


def test_view_is_the_last_narrative_section_of_both_detailed_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _assess(tmp_path, "fixed-workflow", capsys)
    identity = record["record_content_identity"].removeprefix("sha256:")
    markdown = (tmp_path / "fixed-workflow" / "output" / f"sha256-{identity}.md").read_text("utf-8")
    narrative, _, _ = markdown.partition("\n## Traceability Appendix\n")
    headings = re.findall(r"^## (.*)$", narrative, flags=re.M)
    assert headings[-1] == VIEW_TITLE
    view = build_evidence_view(masked_decision_record_view(record))
    for row in view.rows:
        assert f"**{row.name}**" in narrative
    assert excluded_words_in(re.sub(r"^    .*$", "", narrative, flags=re.M)) == ()

    html = render_detailed_html_report(record).decode("utf-8")
    body, _, _ = html.partition("<h2>Traceability Appendix</h2>")
    assert re.findall(r"<h2>(.*?)</h2>", body)[-1] == VIEW_TITLE


def test_view_is_the_second_executive_reference_page_in_both_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _assess(tmp_path, "agentic-control", capsys)
    summary = build_executive_summary(record)
    html = render_executive_html_report(record).decode("utf-8")
    body = html.split("<body>", 1)[1]
    pages = re.findall(r"<h2>(.*?)</h2>", body)

    assert pages[-1] == VIEW_TITLE and pages[-2] == "How the result was reached"
    page = body.split(f"<h2>{VIEW_TITLE}</h2>", 1)[1].split("</section>", 1)[0]
    for row in summary.view.rows:
        assert f"<dt>{escape(row.name, quote=True)}</dt>" in page
    assert f"Evidence set of case file format {record['dossier_schema_version']}" in body
    assert _forbidden(record, re.sub(r"<[^>]+>", " ", page)) == []


def test_view_fails_closed_on_an_unmapped_slot_and_is_addressed_by_the_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = json.loads((GOLDEN / "decision-record-abstention-veto-v1.json").read_bytes())
    before = render_executive_html_report(record)
    assert before == render_executive_html_report(record)

    without = {k: v for k, v in vocabulary.SLOTS.items() if k != "$.problem_value.outcomes[]"}
    monkeypatch.setattr(vocabulary, "SLOTS", MappingProxyType(without))
    with pytest.raises(VocabularyError, match=r"outcomes"):
        build_evidence_view(masked_decision_record_view(record))
    with pytest.raises(VocabularyError):
        render_detailed_html_report(record)
