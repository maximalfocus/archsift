from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

import pytest

from archsift.canonical import canonical_json_bytes
from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.report_text import visible_text
from archsift.workspace import initialize_workspace

_EXAMPLES = Path(__file__).parent.parent / "examples"
_GOLDEN_RECORD = Path(__file__).parent / "golden" / "decision-record-positive-v1.json"


def _assessed_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    example: str = "agentic-control",
) -> tuple[Path, str]:
    """Assess one runnable synthetic example inside an isolated workspace."""
    workspace = tmp_path / example
    workspace.mkdir()
    (workspace / "evidence").mkdir()
    (workspace / "output").mkdir()
    source = _EXAMPLES / example
    (workspace / "case.yaml").write_bytes((source / "case.yaml").read_bytes())
    for artefact in sorted((source / "evidence").iterdir()):
        (workspace / "evidence" / artefact.name).write_bytes(artefact.read_bytes())

    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    return workspace, str(payload["record_content_identity"])


def _incomplete_workspace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, str]:
    workspace = tmp_path / "case"
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    payload = json.loads(capsys.readouterr().out)
    return workspace, str(payload["record_content_identity"])


def _record_path(workspace: Path, identity: str) -> Path:
    return workspace / "output" / f"sha256-{identity[7:]}.json"


def test_report_renders_a_detailed_html_sibling_of_the_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)

    assert main(["report", str(relative), "--format", "html", "--level", "detailed"]) == (
        ExitCode.SUCCESS
    )

    output = capsys.readouterr()
    target = _record_path(workspace, identity).with_suffix(".detailed.html")
    assert output.err == ""
    assert identity in output.out
    assert target.name in output.out
    assert target.is_file()
    content = target.read_bytes()
    assert content.startswith(b"<!DOCTYPE html>")
    assert b"\r" not in content
    assert identity.encode("ascii") in content


def test_report_defaults_to_the_detailed_html_format(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _incomplete_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)

    assert main(["report", str(relative), "--json"]) == ExitCode.SUCCESS

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "diagnostics": [],
        "exit_code": 0,
        "format": "html",
        "level": "detailed",
        "record_content_identity": identity,
        "report": (relative.parent / f"sha256-{identity[7:]}.detailed.html").as_posix(),
        "reused": False,
        "status": "rendered",
    }


def test_report_reuses_byte_identical_output_without_rewriting_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    target = _record_path(workspace, identity).with_suffix(".detailed.html")

    assert main(["report", str(relative), "--json"]) == ExitCode.SUCCESS
    first = json.loads(capsys.readouterr().out)
    first_bytes = target.read_bytes()
    stamp = target.stat().st_mtime_ns

    assert main(["report", str(relative), "--json"]) == ExitCode.SUCCESS
    second = json.loads(capsys.readouterr().out)

    assert first["reused"] is False and second["reused"] is True
    assert target.read_bytes() == first_bytes
    assert target.stat().st_mtime_ns == stamp


def test_report_preserves_a_non_identical_file_at_the_derived_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _incomplete_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    target = _record_path(workspace, identity).with_suffix(".detailed.html")
    target.write_bytes(b"<!DOCTYPE html><p>different</p>\n")

    assert main(["report", str(relative), "--json"]) == ExitCode.PERSISTENCE_FAILED

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "persistence-failed"
    assert payload["diagnostics"][0]["requirement"] == "FR-011"
    assert target.read_bytes() == b"<!DOCTYPE html><p>different</p>\n"


def test_report_and_markdown_views_carry_the_same_authored_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-016: the HTML report states the same content as the Markdown view."""
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    assert main(["report", str(relative), "--quiet"]) == ExitCode.SUCCESS

    markdown = (workspace / "output" / f"sha256-{identity[7:]}.md").read_text(encoding="utf-8")
    html = (
        _record_path(workspace, identity).with_suffix(".detailed.html").read_text(encoding="utf-8")
    )
    record = json.loads(_record_path(workspace, identity).read_bytes())

    def authored(value: object) -> list[str]:
        if isinstance(value, dict):
            return [item for key in sorted(value) for item in authored(value[key])]
        if isinstance(value, list):
            return [item for entry in value for item in authored(entry)]
        return [value] if isinstance(value, str) and len(value) >= 3 else []

    values = authored(record)
    assert len(values) >= 100
    for value in values:
        rendered = visible_text(value)
        assert rendered in markdown, value
        assert escape(rendered, quote=True) in html, value

    for section in (
        "Task Boundary",
        "Evidence Ledger",
        "Decision Areas",
        "Verdict and Recommendation",
        "Assessment Trace",
        "Evidence Identities",
        "Unresolved Gaps",
        "Reassessment Triggers",
        "Masking Notice",
    ):
        assert section in markdown and section in html, section


def test_report_refuses_a_record_outside_the_authorised_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _incomplete_workspace(tmp_path, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    assert main(["report", str(_record_path(workspace, identity)), "--json"]) == (
        ExitCode.UNSAFE_PATH
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unsafe"
    assert payload["diagnostics"][0]["id"] == "report-target-outside-root"
    assert payload["diagnostics"][0]["requirement"] == "FR-016"
    assert payload["diagnostics"][0]["file"] == "record"


def test_report_refuses_a_missing_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["report", "absent.json", "--json"]) == ExitCode.ARTEFACT_UNAVAILABLE

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "artefact-unavailable"
    assert payload["diagnostics"][0]["id"] == "report-target-missing"


def test_report_refuses_a_non_canonical_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "record.json").write_bytes(b'{"record_schema_version": 1, "extra": true}\n')

    assert main(["report", "record.json", "--json"]) == ExitCode.MALFORMED_INPUT

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "malformed"
    assert payload["diagnostics"][0]["id"] == "report-malformed-record"


def test_report_refuses_an_unsupported_record_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    record = json.loads(_GOLDEN_RECORD.read_bytes())
    record["record_schema_version"] = 99
    (tmp_path / "record.json").write_bytes(canonical_json_bytes(record))

    assert main(["report", "record.json", "--json"]) == ExitCode.UNSUPPORTED_SCHEMA

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unsupported"
    assert payload["diagnostics"][0]["id"] == "report-unsupported-schema"


def test_report_quiet_mode_writes_the_output_without_printing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _incomplete_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)

    assert main(["report", str(relative), "--quiet"]) == ExitCode.SUCCESS

    output = capsys.readouterr()
    assert output.out == "" and output.err == ""
    assert _record_path(workspace, identity).with_suffix(".detailed.html").is_file()


def test_report_rejects_conflicting_output_options(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["report", str(tmp_path / "record.json"), "--json", "--quiet"])

    assert exit_info.value.code == ExitCode.USAGE


def test_report_rejects_an_unsupported_format_or_level(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for argument in (["--format", "pdf"], ["--level", "summary"]):
        with pytest.raises(SystemExit) as exit_info:
            main(["report", str(tmp_path / "record.json"), *argument])
        assert exit_info.value.code == ExitCode.USAGE


def test_report_rejects_a_format_and_level_combination_with_no_renderer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-016 defines only a detailed HTML report; PPTX is executive-only."""
    with pytest.raises(SystemExit) as exit_info:
        main(["report", str(tmp_path / "record.json"), "--format", "pptx", "--level", "detailed"])

    assert exit_info.value.code == ExitCode.USAGE
    assert "--format pptx does not support --level detailed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("report_format", "level", "suffix", "magic"),
    [
        ("html", "detailed", ".detailed.html", b"<!DOCTYPE html>"),
        ("html", "executive", ".executive.html", b"<!DOCTYPE html>"),
        ("pptx", "executive", ".executive.pptx", b"PK"),
    ],
)
def test_report_renders_every_supported_format_and_level(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    report_format: str,
    level: str,
    suffix: str,
    magic: bytes,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)

    assert (
        main(["report", str(relative), "--format", report_format, "--level", level, "--json"])
        == ExitCode.SUCCESS
    )

    payload = json.loads(capsys.readouterr().out)
    target = workspace / "output" / f"sha256-{identity[7:]}{suffix}"
    assert payload["format"] == report_format
    assert payload["level"] == level
    assert payload["record_content_identity"] == identity
    assert payload["report"] == target.relative_to(tmp_path).as_posix()
    assert target.read_bytes().startswith(magic)


def test_every_report_of_one_record_is_named_from_that_record_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    for report_format, level in (
        ("html", "detailed"),
        ("html", "executive"),
        ("pptx", "executive"),
    ):
        assert (
            main(["report", str(relative), "--format", report_format, "--level", level, "--quiet"])
            == ExitCode.SUCCESS
        )

    generated = sorted(
        path.name for path in (workspace / "output").iterdir() if path.name != ".gitkeep"
    )
    assert generated == [
        f"sha256-{identity[7:]}.detailed.html",
        f"sha256-{identity[7:]}.executive.html",
        f"sha256-{identity[7:]}.executive.pptx",
        f"sha256-{identity[7:]}.json",
        f"sha256-{identity[7:]}.md",
    ]


def test_executive_reports_reuse_byte_identical_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    target = workspace / "output" / f"sha256-{identity[7:]}.executive.pptx"

    executive = ["report", str(relative), "--format", "pptx", "--level", "executive", "--json"]

    assert main(executive) == ExitCode.SUCCESS
    first = json.loads(capsys.readouterr().out)
    content = target.read_bytes()
    stamp = target.stat().st_mtime_ns

    assert main(executive) == ExitCode.SUCCESS
    second = json.loads(capsys.readouterr().out)

    assert first["reused"] is False and second["reused"] is True
    assert target.read_bytes() == content
    assert target.stat().st_mtime_ns == stamp


def test_report_writes_no_output_beyond_its_own_derived_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _assessed_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    assert main(["report", str(relative), "--quiet"]) == ExitCode.SUCCESS

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert after - before == {
        relative.parent / f"sha256-{identity[7:]}.detailed.html",
    }


def test_report_output_name_binds_the_record_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity = _incomplete_workspace(tmp_path, capsys)
    monkeypatch.chdir(tmp_path)
    relative = _record_path(workspace, identity).relative_to(tmp_path)

    assert main(["report", str(relative), "--json"]) == ExitCode.SUCCESS

    payload = json.loads(capsys.readouterr().out)
    name = Path(str(payload["report"])).name
    assert re.fullmatch(r"sha256-[0-9a-f]{64}\.detailed\.html", name)
    assert name.startswith(f"sha256-{identity[7:]}.")
