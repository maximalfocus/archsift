from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Any, cast

import pytest

from archsift.canonical import JsonObject, JsonValue
from archsift.html_report import HTML_REPORT_FORMAT_VERSION, render_detailed_html_report
from archsift.masking import (
    MASKING_POLICY_VERSION,
    MASKING_WARNING,
    masked_decision_record_view,
)
from archsift.record_view import ReportRecordError
from archsift.report_text import visible_text

_GOLDEN_DIR = Path(__file__).parent / "golden"
_POSITIVE_RECORD = _GOLDEN_DIR / "decision-record-positive-v1.json"
_INCOMPLETE_RECORD = _GOLDEN_DIR / "decision-record-incomplete-v1.json"
_INCOMPLETE_GOLDEN = _GOLDEN_DIR / "decision-report-incomplete-v1.html"
_POSITIVE_GOLDEN = _GOLDEN_DIR / "decision-report-positive-v1.html"

# Every payload that would escape a text node, an attribute, a raw-text
# element, or a URL context if authored strings were ever emitted as markup.
_INJECTION_PAYLOAD = (
    '<script>alert(1)</script><img src=x onerror="alert(2)">'
    "</textarea><textarea>forged</textarea>"
    "</style><style>body{display:none}</style>"
    '</title><a href="javascript:alert(3)">forged link</a>'
    "</dd></dl><h1>forged heading</h1>"
    "\"'&<>` \x00\x1b\u200b\u2028\u202e caf\u00e9"
)


def _record(path: Path = _POSITIVE_RECORD) -> JsonObject:
    return cast(JsonObject, json.loads(path.read_bytes()))


def _scalars(value: JsonValue) -> list[JsonValue]:
    if type(value) is list:
        return [item for entry in cast(list[JsonValue], value) for item in _scalars(entry)]
    if type(value) is dict:
        mapping = cast(JsonObject, value)
        return [item for key in sorted(mapping) for item in _scalars(mapping[key])]
    return [value]


def _authored_strings(record: JsonObject) -> list[str]:
    return [
        value
        for value in _scalars(cast(JsonValue, record))
        if type(value) is str and len(value) >= 3
    ]


def test_detailed_report_matches_exact_golden_and_marks_absent_sections() -> None:
    content = render_detailed_html_report(_record(_INCOMPLETE_RECORD))

    assert content == _INCOMPLETE_GOLDEN.read_bytes()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert b"\r" not in content
    text = content.decode("utf-8")
    assert text.startswith('<!DOCTYPE html>\n<html lang="en">')
    assert text.count("(not provided)") >= 5
    assert "insufficient-evidence" in text
    assert "(abstention)" in text


def test_recommending_report_matches_exact_golden_across_all_decision_areas() -> None:
    record = _record()
    content = render_detailed_html_report(record)

    assert content == _POSITIVE_GOLDEN.read_bytes()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert b"\r" not in content
    text = content.decode("utf-8")
    # All four decision areas, an active veto, and a recommendation path.
    assert "<h4>Problem Value</h4>" in text
    assert "<h4>Agency Necessity</h4>" in text
    assert "<h4>Autonomy Permission</h4>" in text
    assert "<h4>Comparative Fit</h4>" in text
    assert "<dt>Active Hard Veto IDs</dt>" in text
    assert '<p class="value">active</p>' in text
    assert '<p class="value">conditional</p>' in text
    assert '<p class="value">fixed-ai-workflow</p>' in text
    assert "(abstention)" not in text


def test_golden_report_is_pinned_to_lf_line_endings_on_every_platform() -> None:
    attributes = (Path(__file__).parent.parent / ".gitattributes").read_text(encoding="utf-8")

    assert "tests/golden/*.html text eol=lf" in attributes


def test_detailed_report_carries_every_required_record_section() -> None:
    text = render_detailed_html_report(_record()).decode("utf-8")

    for heading in (
        "<h1>ArchSift Decision Report</h1>",
        "<h2>The result</h2>",
        "<h2>Traceability Appendix</h2>",
        "<h3>Record Metadata</h3>",
        "<h3>Case Identity</h3>",
        "<h3>Task Boundary</h3>",
        "<h3>Evidence Ledger</h3>",
        "<h3>Decision Areas</h3>",
        "<h4>Problem Value</h4>",
        "<h4>Agency Necessity</h4>",
        "<h4>Autonomy Permission</h4>",
        "<h4>Comparative Fit</h4>",
        "<h3>Decision Conditions</h3>",
        "<h3>Verdict and Recommendation</h3>",
        "<h3>Assessment Trace</h3>",
        "<h3>Evidence Identities</h3>",
        "<h3>Artefact Identities</h3>",
        "<h3>Unresolved Gaps</h3>",
        "<h3>Reassessment Triggers</h3>",
        "<h3>Masking Notice</h3>",
    ):
        assert heading in text, heading
    for label in (
        "Candidate Comparison and Trade-offs",
        "Active Hard Veto IDs",
        "Mandatory Human Control IDs",
        "Ruleset Version",
        "Tool Version",
        "Dossier Schema Version",
    ):
        assert f"<dt>{label}</dt>" in text, label
    assert f'<p class="value">{HTML_REPORT_FORMAT_VERSION}</p>' in text
    assert MASKING_WARNING in text
    assert f'<p class="value">{MASKING_POLICY_VERSION}</p>' in text


def test_detailed_report_renders_every_scalar_the_record_holds() -> None:
    record = _record()
    text = render_detailed_html_report(record).decode("utf-8")

    authored = _authored_strings(masked_decision_record_view(record))
    assert len(authored) >= 50
    for value in authored:
        assert escape(visible_text(value), quote=True) in text, value


def test_report_restates_the_record_identity_and_derives_no_other() -> None:
    record = _record()
    text = render_detailed_html_report(record).decode("utf-8")

    identity = cast(str, record["record_content_identity"])
    assert identity in text
    # The rendered report is an output of the record, never addressed as a
    # distinct record: no identity appears that the record does not declare.
    declared = {
        cast(str, record["record_content_identity"]),
        cast(str, record["dossier_content_identity"]),
        cast(str, record["configuration_content_identity"]),
        *(
            cast(str, cast(JsonObject, link)["content_identity"])
            for link in cast(JsonObject, record["evidence_links"]).values()
        ),
    }
    assert set(re.findall(r"sha256:[0-9a-f]{64}", text)) <= declared


def test_authored_markup_scripts_and_controls_render_as_inert_text() -> None:
    record = _record()
    dossier = cast(dict[str, Any], record["dossier"])
    dossier["case"]["title"] = _INJECTION_PAYLOAD
    dossier["evidence"][0]["claim"] = _INJECTION_PAYLOAD
    dossier["task"]["operation"] = _INJECTION_PAYLOAD
    dossier["candidate_comparison"]["candidates"][0]["name"] = _INJECTION_PAYLOAD

    text = render_detailed_html_report(record).decode("utf-8")

    # Only this module's own fixed markup may appear as markup.
    assert text.count("<script") == 0 and text.count("<img") == 0
    assert text.count("<textarea") == 0 and text.count("<a ") == 0
    assert text.count("<style>") == 1 and text.count("</style>") == 1
    assert text.count("<h1>") == 1 and text.count("<title>") == 1
    # Authored quotes are escaped, so a raw `name="` can only be an attribute
    # the renderer itself wrote: the document carries no authored attribute.
    assert set(re.findall(r'([a-zA-Z-]+)="', text)) == {
        "charset",
        "class",
        "content",
        "lang",
        "name",
    }
    # The payload survives as escaped, visible, inert text.
    # The narrative restates the title, claim, operation, and name once more each.
    assert text.count(escape(visible_text(_INJECTION_PAYLOAD), quote=True)) == 11
    assert "\x00" not in text and "\x1b" not in text
    assert "\u200b" not in text and "\u2028" not in text and "\u202e" not in text
    assert "\\u0000" in text and "\\u001b" in text
    assert "\\u200b" in text and "\\u2028" in text and "\\u202e" in text
    assert "caf\u00e9" in text


def test_report_is_self_contained_and_references_no_external_resource() -> None:
    record = _record()
    dossier = cast(dict[str, Any], record["dossier"])
    dossier["case"]["title"] = "https://example.invalid/case data:text/html,x"

    text = render_detailed_html_report(record).decode("utf-8")

    for forbidden in ("<script", "<iframe", "<object", "<embed", "<link", "@import", "url("):
        assert forbidden not in text, forbidden
    assert not re.search(r"\b(?:src|href|integrity|srcset|action|formaction)\s*=", text)
    # A URL authored into the dossier stays text and never becomes a target.
    assert "https://example.invalid/case" in text
    assert 'href="https' not in text


def test_masking_is_applied_by_the_renderer_and_is_idempotent() -> None:
    record = _record()
    dossier = cast(dict[str, Any], record["dossier"])
    dossier["case"]["title"] = "Card 4111 1111 1111 1111 and api_key: AKIAIOSFODNN7EXAMPLE"
    record.pop("masking", None)

    first = render_detailed_html_report(record).decode("utf-8")

    assert "4111 1111 1111 1111" not in first
    assert "AKIAIOSFODNN7EXAMPLE" not in first
    assert "[ARCHSIFT-MASKED:payment-card]" in first
    assert "[ARCHSIFT-MASKED:credential]" in first
    # A record read back after persistence is already masked; rendering it
    # again must not mask the placeholders a second time.
    second = render_detailed_html_report(masked_decision_record_view(record)).decode("utf-8")
    assert second == first


def test_rendering_is_pure_and_does_not_mutate_or_read_the_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    before = json.dumps(record, sort_keys=True)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("renderer crossed its pure typed boundary")

    monkeypatch.setattr(Path, "open", forbidden)

    first = render_detailed_html_report(record)
    second = render_detailed_html_report(record)

    assert first == second
    assert json.dumps(record, sort_keys=True) == before


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda record: record.pop("assessment"), r"\$ is missing assessment"),
        (lambda record: record.pop("evidence_links"), r"\$ is missing evidence_links"),
        (lambda record: cast(dict[str, Any], record["dossier"]).pop("task"), r"\$\.dossier"),
        (
            lambda record: cast(dict[str, Any], record["assessment"]).pop("verdict"),
            r"\$\.assessment",
        ),
        (lambda record: record.__setitem__("dossier", "not-an-object"), r"\$\.dossier"),
    ],
)
def test_unknown_record_shape_fails_closed(
    mutate: Any,
    match: str,
) -> None:
    record = _record()
    mutate(record)

    with pytest.raises(ReportRecordError, match=match):
        render_detailed_html_report(record)


def test_recommending_verdict_without_a_recommended_class_fails_closed() -> None:
    record = _record()
    assessment = cast(dict[str, Any], record["assessment"])
    assessment["recommended_class"] = None
    assessment["verdict"] = "supported"

    with pytest.raises(ReportRecordError, match="recommending verdict"):
        render_detailed_html_report(record)


def test_abstaining_verdicts_state_their_outcome_without_a_recommended_class() -> None:
    for verdict, expected in (
        ("insufficient-evidence", "(abstention)"),
        ("no-permissible-candidate", "(no permissible candidate)"),
    ):
        record = _record()
        assessment = cast(dict[str, Any], record["assessment"])
        assessment["recommended_class"] = None
        assessment["verdict"] = verdict

        text = render_detailed_html_report(record).decode("utf-8")

        assert f'<p class="value">{escape(expected)}</p>' in text


def test_unsupported_scalar_type_fails_closed() -> None:
    record = _record()
    cast(dict[str, Any], record["dossier"])["case"]["title"] = 1.5

    with pytest.raises(ReportRecordError, match="float"):
        render_detailed_html_report(record)


def test_report_bytes_are_hash_seed_independent() -> None:
    script = f"""
import json
from pathlib import Path
from archsift.html_report import render_detailed_html_report
record = json.loads(Path({str(_POSITIVE_RECORD)!r}).read_bytes())
print(render_detailed_html_report(record).hex())
"""
    outputs = []
    for seed in ("1", "947"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]


def test_mapping_order_does_not_change_the_rendered_bytes() -> None:
    record = _record()
    reversed_record = cast(JsonObject, dict(reversed(list(record.items()))))

    assert list(reversed_record) != list(record)
    assert render_detailed_html_report(reversed_record) == render_detailed_html_report(record)
