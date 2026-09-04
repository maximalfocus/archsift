"""Deterministic, self-contained, injection-safe HTML views of decision records.

FR-016: the detailed HTML report renders one already-composed canonical
decision record for architecture review in a browser. It carries the same
content as the Markdown review view — task boundary, candidate comparison, the
four decision areas, vetoes, recommendation or abstention, trade-offs, evidence
links with their content identities, unresolved gaps, the dossier schema,
ruleset and tool versions, and reassessment triggers.

FR-017: the executive HTML report renders the same
:class:`~archsift.executive_summary.ExecutiveSummary` that the PPTX deck
renders, so the two presentation formats state identical facts.

Both reports are outputs of the record, never separate authoritative
artifacts: each restates the record's own content identity and derives no
identity of its own.

Three properties are structural rather than incidental:

* **Offline and self-contained (NFR-001).** The document references no
  network resource. Its only stylesheet is the fixed literal declared in this
  module, and it contains no script, font, image, frame, or link target.
* **Injection-safe (NFR-004).** Authored text reaches the document only as an
  escaped text node. Nothing authored is ever written into an attribute, a
  URL, a style block, or a raw-text element, so a dossier cannot create
  markup, script, or executable content, and cannot break out of the field it
  is rendered in.
* **Masked (NFR-009).** The renderer applies the masking policy itself rather
  than trusting its caller, so no call path can emit an unmasked report.

Rendering is deterministic (NFR-003): fixed structure, sorted mapping order,
UTF-8, LF line endings, and no generation timestamp or other run-variant
metadata.
"""

from __future__ import annotations

import re
from html import escape
from typing import Final, cast

from archsift.canonical import JsonObject, JsonValue
from archsift.executive_summary import (
    EXECUTIVE_SUMMARY_VERSION,
    ExecutiveSummary,
    build_executive_summary,
)
from archsift.masking import MASKING_POLICY_VERSION, MASKING_WARNING
from archsift.narrative import Narrative, build_narrative
from archsift.record_view import (
    ABSENT,
    EMPTY,
    ReportRecordError,
    masked_record_view,
    recommendation,
)
from archsift.report_text import visible_text

HTML_REPORT_FORMAT_VERSION: Final = 2

#: The fixed text joining one summary point's values in a rendered line.
VALUE_SEPARATOR: Final = " — "

# A declared record field name; any other mapping key is an authored or
# generated identifier (an evidence ID, a configuration key) and is shown
# exactly as recorded instead of being reworded into a title.
_FIELD_NAME: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")

# The complete presentation of the document. It is a fixed literal with no
# authored content, so it cannot be broken out of, and it references no
# external font, image, or stylesheet.
_STYLESHEET: Final = """\
:root { color-scheme: light dark; }
body {
  margin: 0 auto;
  max-width: 60rem;
  padding: 2rem 1rem 4rem;
  font-family: system-ui, sans-serif;
  line-height: 1.5;
}
h1 { font-size: 1.6rem; }
h2 { font-size: 1.25rem; margin-top: 2.5rem; border-bottom: 1px solid currentColor; }
h3 { font-size: 1.05rem; margin-top: 1.75rem; }
dl { margin: 0; }
dt { font-weight: 600; margin-top: 0.75rem; }
dd { margin: 0 0 0 1.25rem; }
ol { margin: 0; padding-left: 1.5rem; }
p { margin: 0.25rem 0; }
p.value { white-space: pre-wrap; overflow-wrap: anywhere; }
p.empty { opacity: 0.7; }
p.case { font-size: 1.15rem; font-weight: 600; }
.part dd { margin-bottom: 0.5rem; }
.notice { margin-top: 2.5rem; padding: 0.75rem 1rem; border: 1px solid currentColor; }
"""


def _text(value: str) -> str:
    """Return authored text as an inert escaped HTML text node."""
    return escape(visible_text(value), quote=True)


def _label(key: str) -> str:
    """Return one mapping key as inert label text."""
    if _FIELD_NAME.fullmatch(key):
        return _text(key.replace("_", " ").title())
    return _text(key)


def _scalar(value: JsonValue) -> str:
    if value is None:
        return ABSENT
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return _text(value)
    raise ReportRecordError(f"Unsupported {type(value).__name__} report scalar.")


def _emit_value(lines: list[str], value: JsonValue) -> None:
    if type(value) is list:
        items = value
        if not items:
            lines.append(f'<p class="empty">{EMPTY}</p>')
            return
        lines.append("<ol>")
        for item in items:
            lines.append("<li>")
            _emit_value(lines, item)
            lines.append("</li>")
        lines.append("</ol>")
        return
    if type(value) is dict:
        mapping = value
        if not mapping:
            lines.append(f'<p class="empty">{EMPTY}</p>')
            return
        lines.append("<dl>")
        # Sorted order keeps the document byte-identical whatever order the
        # loaded record happens to iterate in.
        for key in sorted(mapping):
            lines.append(f"<dt>{_label(key)}</dt>")
            lines.append("<dd>")
            _emit_value(lines, mapping[key])
            lines.append("</dd>")
        lines.append("</dl>")
        return
    lines.append(f'<p class="value">{_scalar(value)}</p>')


def _emit_field(lines: list[str], label: str, value: JsonValue) -> None:
    lines.append("<dl>")
    lines.append(f"<dt>{_text(label)}</dt>")
    lines.append("<dd>")
    _emit_value(lines, value)
    lines.append("</dd>")
    lines.append("</dl>")


def _section(lines: list[str], title: str, label: str, value: JsonValue) -> None:
    lines.append(f"<h2>{_text(title)}</h2>")
    _emit_field(lines, label, value)


def _recorded_context_ids(masked: JsonObject) -> list[JsonValue]:
    """Return the evidence IDs the record marks as recorded context (schema 3+)."""
    links = cast(dict[str, JsonValue], masked["evidence_links"])
    return [
        identifier
        for identifier, link in sorted(links.items())
        if cast(dict[str, JsonValue], link).get("decision_bearing") is False
    ]


def _demoted(lines: list[str]) -> list[str]:
    """Push every heading one level down so the appendix nests under its own heading."""
    demoted: list[str] = []
    for line in lines:
        if line.startswith("<h3>") and line.endswith("</h3>"):
            demoted.append("<h4>" + line[4:-5] + "</h4>")
        elif line.startswith("<h2>") and line.endswith("</h2>"):
            demoted.append("<h3>" + line[4:-5] + "</h3>")
        else:
            demoted.append(line)
    return demoted


def _emit_narrative(lines: list[str], narrative: Narrative) -> None:
    for section in narrative.sections:
        lines.append(f"<h2>{_text(section.title)}</h2>")
        lines.append("<dl>")
        for item in section.items:
            lines.append(f"<dt>{_text(item.label)}</dt>")
            lines.append(f'<dd><p class="value">{_text(item.text)}</p></dd>')
        lines.append("</dl>")


def render_detailed_html_report(record: JsonObject) -> bytes:
    """Return one deterministic self-contained detailed HTML report.

    ``record`` is a loaded canonical decision record. The masking policy is
    applied here rather than by the caller, so the rendered document can never
    carry an unmasked authored value.
    """
    view = masked_record_view(record)
    masked, dossier, assessment = view.record, view.dossier, view.assessment
    recommended = recommendation(assessment)

    narrative = build_narrative(masked)
    lines: list[str] = []
    _emit_narrative(lines, narrative)
    lines.append("<h2>Traceability Appendix</h2>")
    appendix: list[str] = ["<h2>Record Metadata</h2>"]
    outer = lines
    lines = appendix
    _emit_field(lines, "Report Format Version", HTML_REPORT_FORMAT_VERSION)
    _emit_field(lines, "Vocabulary Version", narrative.vocabulary_version)
    _emit_field(lines, "Record Schema Version", masked["record_schema_version"])
    _emit_field(lines, "Record Content Identity", masked["record_content_identity"])
    _emit_field(lines, "Dossier Schema Version", masked["dossier_schema_version"])
    # NFR-010: the report states the language it is written in.
    _emit_field(lines, "Case Language", dossier["language"])
    _emit_field(lines, "Dossier Content Identity", masked["dossier_content_identity"])
    _emit_field(lines, "Ruleset Version", masked["ruleset_version"])
    _emit_field(lines, "Tool Version", masked["tool_version"])
    _emit_field(lines, "Assessment Configuration", masked["configuration"])
    _emit_field(lines, "Configuration Content Identity", masked["configuration_content_identity"])
    if "graph_use" in masked:
        _section(lines, "Graph Use", "Graph Use", masked["graph_use"])
    if "assistance_envelope" in masked:
        _section(lines, "Assistance Envelope", "Assistance Envelope", masked["assistance_envelope"])
    if "abstention_scope" in masked:
        _section(lines, "Abstention Scope", "Abstention Scope", masked["abstention_scope"])

    _section(lines, "Case Identity", "Case", dossier["case"])
    _section(lines, "Task Boundary", "Task", dossier["task"])
    _section(lines, "Evidence Ledger", "Evidence", dossier["evidence"])

    lines.append("<h2>Decision Areas</h2>")
    lines.append("<h3>Problem Value</h3>")
    _emit_field(lines, "Problem Value", dossier["problem_value"])
    lines.append("<h3>Agency Necessity</h3>")
    _emit_field(lines, "Agency Necessity", dossier["agency_necessity"])
    lines.append("<h3>Autonomy Permission</h3>")
    _emit_field(lines, "Autonomy Permission", dossier["autonomy_permission"])
    lines.append("<h3>Comparative Fit</h3>")
    _emit_field(lines, "Candidate Comparison and Trade-offs", dossier["candidate_comparison"])

    _section(lines, "Decision Conditions", "Decision Conditions", dossier["decision_conditions"])

    lines.append("<h2>Verdict and Recommendation</h2>")
    _emit_field(lines, "Assessment Schema Version", assessment["schema_version"])
    _emit_field(lines, "Assessment Ruleset Version", assessment["ruleset_version"])
    _emit_field(lines, "Verdict", assessment["verdict"])
    _emit_field(lines, "Verdict Rule ID", assessment["verdict_rule_id"])
    _emit_field(lines, "Qualitative Evidence State", assessment["evidence_state"])
    _emit_field(lines, "Recommendation", recommended)
    _emit_field(lines, "Surviving Candidate IDs", assessment["surviving_candidate_ids"])
    _emit_field(lines, "Unmet Conditions", assessment["unmet_conditions"])
    _emit_field(lines, "Active Hard Veto IDs", assessment["active_hard_veto_ids"])
    _emit_field(lines, "Mandatory Human Control IDs", assessment["mandatory_human_control_ids"])

    lines.append("<h2>Assessment Trace</h2>")
    _emit_field(lines, "Prerequisite Evaluation", assessment["prerequisite_evaluation"])
    _emit_field(
        lines,
        "Ordered Elimination Evaluation",
        assessment["ordered_elimination_evaluation"],
    )

    _section(lines, "Evidence Identities", "Evidence Links", masked["evidence_links"])
    if cast(int, masked["record_schema_version"]) >= 3:
        lines.append("<h2>Recorded Context</h2>")
        _emit_field(lines, "Recorded Context Evidence IDs", _recorded_context_ids(masked))
    _section(lines, "Artefact Identities", "Artefact Links", masked["artefact_links"])
    _section(lines, "Unresolved Gaps", "Unresolved Gaps", masked["unresolved_gaps"])
    _section(
        lines, "Reassessment Triggers", "Reassessment Triggers", masked["reassessment_triggers"]
    )

    lines.append('<section class="notice">')
    lines.append("<h2>Masking Notice</h2>")
    _emit_field(lines, "Policy Version", MASKING_POLICY_VERSION)
    _emit_field(lines, "Warning", MASKING_WARNING)
    lines.append("</section>")
    outer.extend(_demoted(appendix))
    return _document("ArchSift Decision Report", outer, language=view.language)


def _document(title: str, body: list[str], *, language: str) -> bytes:
    """Wrap rendered body markup in the shared self-contained document shell.

    NFR-010: the document declares the case's language, so a reader and an
    assistive technology are told what language the report is written in.
    """
    lines = [
        "<!DOCTYPE html>",
        f'<html lang="{_text(language)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_text(title)}</title>",
        "<style>",
        _STYLESHEET.rstrip("\n"),
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{_text(title)}</h1>",
        *body,
        "</body>",
        "</html>",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_executive_summary_html(summary: ExecutiveSummary) -> bytes:
    """Return one deterministic self-contained executive summary as HTML.

    The body is exactly the summary's three parts; the record identity, the
    vocabulary version, and the masking notice follow in a footer so the
    document is addressed and its masking is declared without a fourth part.
    """
    body: list[str] = [f'<p class="case">{_text(summary.case_title)}</p>']
    for part in summary.parts:
        body.append('<section class="part">')
        body.append(f"<h2>{_text(part.title)}</h2>")
        body.append("<dl>")
        for statement in part.statements:
            body.append(f"<dt>{_text(statement.label)}</dt>")
            body.append(f'<dd><p class="value">{_text(statement.text)}</p></dd>')
        body.append("</dl>")
        body.append("</section>")
    body.append('<footer class="notice">')
    body.append("<dl>")
    for label, value in (
        ("Record", summary.record_content_identity),
        ("Vocabulary version", summary.vocabulary_version),
        ("Summary format version", str(EXECUTIVE_SUMMARY_VERSION)),
        ("Masking policy version", str(MASKING_POLICY_VERSION)),
        ("Masking notice", MASKING_WARNING),
    ):
        body.append(f"<dt>{_text(label)}</dt>")
        body.append(f'<dd><p class="value">{_text(value)}</p></dd>')
    body.append("</dl>")
    body.append("</footer>")
    return _document("ArchSift Executive Summary", body, language=summary.language)


def render_executive_html_report(record: JsonObject) -> bytes:
    """Return one deterministic executive summary of a loaded canonical record."""
    return render_executive_summary_html(build_executive_summary(record))
