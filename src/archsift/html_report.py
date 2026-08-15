"""Deterministic, self-contained, injection-safe HTML views of decision records.

FR-016: the detailed HTML report renders one already-composed canonical
decision record for architecture review in a browser. It carries the same
content as the Markdown review view — task boundary, candidate comparison, the
four decision areas, vetoes, recommendation or abstention, trade-offs, evidence
links with their content identities, unresolved gaps, the dossier schema,
ruleset and tool versions, and reassessment triggers.

The report is an output of the record, never a separate authoritative
artifact: it restates the record's own content identity and derives no
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
from typing import Final

from archsift.canonical import JsonObject, JsonValue
from archsift.masking import (
    MASKING_POLICY_VERSION,
    MASKING_WARNING,
    masked_decision_record_view,
)
from archsift.report_text import visible_text

HTML_REPORT_FORMAT_VERSION: Final = 1

_ABSENT: Final = "(not provided)"
_EMPTY: Final = "(none)"
_ABSTENTION: Final = "(abstention)"
_NO_PERMISSIBLE_CANDIDATE: Final = "(no permissible candidate)"

# A declared record field name; any other mapping key is an authored or
# generated identifier (an evidence ID, a configuration key) and is shown
# exactly as recorded instead of being reworded into a title.
_FIELD_NAME: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")

_REQUIRED_RECORD_KEYS: Final[tuple[str, ...]] = (
    "artefact_links",
    "assessment",
    "configuration",
    "configuration_content_identity",
    "dossier",
    "dossier_content_identity",
    "dossier_schema_version",
    "evidence_links",
    "reassessment_triggers",
    "record_content_identity",
    "record_schema_version",
    "ruleset_version",
    "tool_version",
    "unresolved_gaps",
)
_REQUIRED_DOSSIER_KEYS: Final[tuple[str, ...]] = (
    "agency_necessity",
    "autonomy_permission",
    "candidate_comparison",
    "case",
    "decision_conditions",
    "evidence",
    "problem_value",
    "schema_version",
    "task",
)
_REQUIRED_ASSESSMENT_KEYS: Final[tuple[str, ...]] = (
    "active_hard_veto_ids",
    "evidence_state",
    "mandatory_human_control_ids",
    "ordered_elimination_evaluation",
    "prerequisite_evaluation",
    "recommended_class",
    "ruleset_version",
    "schema_version",
    "surviving_candidate_ids",
    "unmet_conditions",
    "verdict",
    "verdict_rule_id",
)

_ABSTAINING_VERDICTS: Final[dict[str, str]] = {
    "insufficient-evidence": _ABSTENTION,
    "no-permissible-candidate": _NO_PERMISSIBLE_CANDIDATE,
}

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
.notice { margin-top: 2.5rem; padding: 0.75rem 1rem; border: 1px solid currentColor; }
"""


class HtmlReportError(ValueError):
    """A decision record cannot be rendered as HTML without ambiguity."""


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
        return _ABSENT
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return _text(value)
    raise HtmlReportError(f"Unsupported {type(value).__name__} report scalar.")


def _emit_value(lines: list[str], value: JsonValue) -> None:
    if type(value) is list:
        items = value
        if not items:
            lines.append(f'<p class="empty">{_EMPTY}</p>')
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
            lines.append(f'<p class="empty">{_EMPTY}</p>')
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


def _require_object(value: JsonValue, name: str) -> JsonObject:
    if type(value) is not dict:
        raise HtmlReportError(f"Decision record {name} is not a JSON object.")
    return value


def _require_keys(mapping: JsonObject, expected: tuple[str, ...], name: str) -> None:
    missing = [key for key in expected if key not in mapping]
    if missing:
        raise HtmlReportError(f"Decision record {name} is missing {', '.join(missing)}.")


def _recommendation(assessment: JsonObject) -> JsonValue:
    """Return the recommendation exactly as the Markdown review view states it."""
    recommended = assessment["recommended_class"]
    if recommended is not None:
        return recommended
    verdict = assessment["verdict"]
    if type(verdict) is str and verdict in _ABSTAINING_VERDICTS:
        return _ABSTAINING_VERDICTS[verdict]
    raise HtmlReportError("A recommending verdict has no recommended class.")


def render_detailed_html_report(record: JsonObject) -> bytes:
    """Return one deterministic self-contained detailed HTML report.

    ``record`` is a loaded canonical decision record. The masking policy is
    applied here rather than by the caller, so the rendered document can never
    carry an unmasked authored value.
    """
    if type(record) is not dict:
        raise HtmlReportError("Decision record is not a JSON object.")
    masked = masked_decision_record_view(record)
    _require_keys(masked, _REQUIRED_RECORD_KEYS, "$")
    dossier = _require_object(masked["dossier"], "$.dossier")
    _require_keys(dossier, _REQUIRED_DOSSIER_KEYS, "$.dossier")
    assessment = _require_object(masked["assessment"], "$.assessment")
    _require_keys(assessment, _REQUIRED_ASSESSMENT_KEYS, "$.assessment")
    recommendation = _recommendation(assessment)

    lines: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>ArchSift Decision Report</title>",
        "<style>",
        _STYLESHEET.rstrip("\n"),
        "</style>",
        "</head>",
        "<body>",
        "<h1>ArchSift Decision Report</h1>",
        "<h2>Record Metadata</h2>",
    ]
    _emit_field(lines, "Report Format Version", HTML_REPORT_FORMAT_VERSION)
    _emit_field(lines, "Record Schema Version", masked["record_schema_version"])
    _emit_field(lines, "Record Content Identity", masked["record_content_identity"])
    _emit_field(lines, "Dossier Schema Version", masked["dossier_schema_version"])
    _emit_field(lines, "Dossier Content Identity", masked["dossier_content_identity"])
    _emit_field(lines, "Ruleset Version", masked["ruleset_version"])
    _emit_field(lines, "Tool Version", masked["tool_version"])
    _emit_field(lines, "Assessment Configuration", masked["configuration"])
    _emit_field(lines, "Configuration Content Identity", masked["configuration_content_identity"])

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
    _emit_field(lines, "Recommendation", recommendation)
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
    lines.append("</body>")
    lines.append("</html>")
    return ("\n".join(lines) + "\n").encode("utf-8")
