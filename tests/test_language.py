from __future__ import annotations

import json
import re
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from archsift.canonical import canonical_dossier_bytes, canonical_dossier_dict
from archsift.canonical import dossier_content_identity as identity_of
from archsift.cli import main
from archsift.decision_record import compose_decision_record
from archsift.diagnostics import ExitCode
from archsift.executive_summary import build_executive_summary
from archsift.html_report import render_detailed_html_report, render_executive_html_report
from archsift.language import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    UnsupportedLanguageError,
    is_supported_language,
    is_well_formed_language,
    workspace_guidance,
)
from archsift.markdown_report import render_markdown_decision_report
from archsift.pptx_report import render_executive_pptx_report
from archsift.record_view import ReportRecordError
from archsift.validation import validate_workspace
from archsift.workspace import initialize_workspace

_GOLDEN_RECORD = Path(__file__).parent / "golden" / "decision-record-abstention-veto-v1.json"


def _workspace(tmp_path: Path, name: str = "case") -> Path:
    workspace = tmp_path / name
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    return workspace


def _write_case(workspace: Path, dossier: dict[str, Any]) -> None:
    (workspace / "case.yaml").write_text(
        yaml.safe_dump(dossier, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def _dossier(**overrides: Any) -> dict[str, Any]:
    dossier: dict[str, Any] = {
        "schema_version": 1,
        "case": {"id": "language", "title": "Synthetic language case"},
        "evidence": [],
        "decision_conditions": [],
    }
    dossier.update(overrides)
    return dossier


def test_init_declares_the_default_language_and_is_reproducible(tmp_path: Path) -> None:
    # Identical inputs means the same workspace name: `init` derives the case
    # identity from it, so only the parent directory differs here.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _workspace(tmp_path / "a", "my-case")
    second = _workspace(tmp_path / "b", "my-case")

    parsed = yaml.safe_load((first / "case.yaml").read_text(encoding="utf-8"))
    assert parsed["language"] == DEFAULT_LANGUAGE == "en"
    assert (first / "case.yaml").read_bytes() == (second / "case.yaml").read_bytes()
    # The workspace guidance is the packaged text for the declared language.
    assert (first / "README.md").read_text(encoding="utf-8") == workspace_guidance("en")
    assert (first / "README.md").read_bytes() == (second / "README.md").read_bytes()


def test_a_declared_supported_language_validates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="en"))

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.language == "en"


def test_an_omitted_language_defaults_to_english(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier())

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.language == DEFAULT_LANGUAGE


def test_omitting_the_language_addresses_the_same_record_as_declaring_the_default(
    tmp_path: Path,
) -> None:
    omitted = _workspace(tmp_path, "omitted")
    declared = _workspace(tmp_path, "declared")
    _write_case(omitted, _dossier())
    _write_case(declared, _dossier(language="en"))

    first = validate_workspace(omitted).dossier
    second = validate_workspace(declared).dossier

    assert first is not None and second is not None
    assert canonical_dossier_bytes(first) == canonical_dossier_bytes(second)
    assert identity_of(first) == identity_of(second)


def test_a_well_formed_but_unsupported_language_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="fr"))

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.dossier is None
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "language-unsupported"
    assert diagnostic.field == "$.language"
    assert diagnostic.requirement == "NFR-010"
    assert "'fr'" in diagnostic.message
    # The remediation names the supported set rather than only rejecting.
    assert "en" in diagnostic.remediation


@pytest.mark.parametrize(
    "code", ["", "English", "EN", "e", "en_GB", "en-", "12", "en-toolongsubtag"]
)
def test_a_malformed_language_code_fails_closed(tmp_path: Path, code: str) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language=code))

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.dossier is None
    assert any(diagnostic.field == "$.language" for diagnostic in result.diagnostics)


def test_a_non_string_language_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language=7))

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert any(diagnostic.field == "$.language" for diagnostic in result.diagnostics)


def test_the_cli_reports_an_unsupported_language_with_a_stable_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="de"))

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"][0]["id"] == "language-unsupported"
    assert payload["diagnostics"][0]["requirement"] == "NFR-010"


def test_the_language_participates_in_the_canonical_dossier_bytes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="en"))
    dossier = validate_workspace(workspace).dossier
    assert dossier is not None

    payload = canonical_dossier_dict(dossier)

    assert payload["language"] == "en"
    assert b'"language":"en"' in canonical_dossier_bytes(dossier)


def test_changing_the_declared_language_produces_a_distinct_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-011/NFR-010: language is part of the address, not presentation.

    Only English is supported today, so a second language is registered for
    the duration of this test; the property under test is that the canonical
    address changes with the declared language, which is what makes adding a
    language safe.
    """
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="en"))
    english = validate_workspace(workspace).dossier
    assert english is not None
    monkeypatch.setitem(
        cast(dict[str, str], __import__("archsift.language", fromlist=["_"])._WORKSPACE_GUIDANCE),
        "cy",
        "templates/workspace-README.md",
    )
    other = replace(english, language="cy")

    assert canonical_dossier_bytes(other) != canonical_dossier_bytes(english)
    assert identity_of(other) != identity_of(english)
    first = compose_decision_record(english, tool_version="0.1.0-test")
    second = compose_decision_record(other, tool_version="0.1.0-test")
    assert second.record_content_identity != first.record_content_identity
    assert second.dossier_content_identity != first.dossier_content_identity


def test_authored_prose_language_is_never_validated_as_truth(tmp_path: Path) -> None:
    """NFR-010: conformance of authored prose is a convention, not a check."""
    workspace = _workspace(tmp_path)
    _write_case(
        workspace,
        _dossier(
            language="en",
            case={"id": "prose", "title": "Décision d'architecture entièrement fictive"},
            evidence=[
                {
                    "id": "observee",
                    "kind": "assumption",
                    "claim": "Une hypothèse synthétique non vérifiée.",
                    "owner": "Réviseur synthétique",
                    "affects": ["problem-value"],
                    "falsified_by": "Un essai contrôlé la réfute.",
                }
            ],
        ),
    )

    result = validate_workspace(workspace)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.language == "en"


def test_every_generated_representation_declares_the_case_language() -> None:
    record = cast(dict[str, Any], json.loads(_GOLDEN_RECORD.read_bytes()))
    assert record["dossier"]["language"] == "en"

    detailed = render_detailed_html_report(record).decode("utf-8")
    executive = render_executive_html_report(record).decode("utf-8")
    deck = render_executive_pptx_report(record)

    assert detailed.startswith('<!DOCTYPE html>\n<html lang="en">')
    assert executive.startswith('<!DOCTYPE html>\n<html lang="en">')
    assert "<dt>Case Language</dt>" in detailed
    assert "<dt>Language</dt>" in executive
    with zipfile.ZipFile(BytesIO(deck)) as archive:
        slides = [
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ]
    assert slides
    for slide in slides:
        assert 'lang="en"' in slide
        assert 'lang="en-US"' not in slide
    assert build_executive_summary(record).language == "en"


def test_the_markdown_review_view_states_the_declared_language(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, _dossier(language="en"))
    dossier = validate_workspace(workspace).dossier
    assert dossier is not None

    report = render_markdown_decision_report(
        compose_decision_record(dossier, tool_version="0.1.0-test")
    ).decode("utf-8")

    assert "**Case Language**" in report
    assert re.search(r"\*\*Case Language\*\*\n\n    en\n", report)


def test_a_record_declaring_an_unsupported_language_is_refused_by_every_renderer() -> None:
    record = cast(dict[str, Any], json.loads(_GOLDEN_RECORD.read_bytes()))
    record["dossier"]["language"] = "fr"

    for render in (
        render_detailed_html_report,
        render_executive_html_report,
        render_executive_pptx_report,
    ):
        with pytest.raises(ReportRecordError, match="'fr' is not supported"):
            render(record)


def test_the_supported_language_registry_can_generate_every_language_it_claims() -> None:
    assert SUPPORTED_LANGUAGES == ("en",)
    assert DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES
    for code in SUPPORTED_LANGUAGES:
        assert is_supported_language(code)
        assert is_well_formed_language(code)
        assert workspace_guidance(code).startswith("# ArchSift case workspace")
    with pytest.raises(UnsupportedLanguageError):
        workspace_guidance("fr")


@pytest.mark.parametrize(
    ("code", "well_formed"),
    [
        ("en", True),
        ("cy", True),
        ("gsw", True),
        ("en-GB", True),
        ("zh-Hant-TW", True),
        ("EN", False),
        ("e", False),
        ("english", False),
        ("en_GB", False),
        ("en-", False),
        ("", False),
        (7, False),
        (None, False),
    ],
)
def test_language_code_shape_is_recognised_without_claiming_support(
    code: object, well_formed: bool
) -> None:
    assert is_well_formed_language(code) is well_formed
    # A well-formed code is still unsupported until ArchSift can generate it.
    assert is_supported_language(code) is (code == "en")
