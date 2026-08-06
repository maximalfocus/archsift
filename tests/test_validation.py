from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.validation import validate_workspace
from archsift.workspace import initialize_workspace


def _workspace(tmp_path: Path) -> Path:
    target = tmp_path / "case"
    assert initialize_workspace(target).exit_code == ExitCode.SUCCESS
    return target


def _write_case(workspace: Path, content: object) -> None:
    (workspace / "case.yaml").write_text(yaml.safe_dump(content, sort_keys=False))


def test_packaged_schema_is_available() -> None:
    schema = files("archsift").joinpath("schemas/dossier-v1.schema.json")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    assert payload["properties"]["schema_version"]["const"] == 1
    assert payload["additionalProperties"] is False
    assert payload["properties"]["case"]["additionalProperties"] is False


def test_generated_workspace_validates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.diagnostics == ()
    assert result.dossier is not None
    assert result.dossier.schema_version == 1
    assert result.dossier.case.id == "case"


def test_missing_workspace_fails_closed(tmp_path: Path) -> None:
    result = validate_workspace(tmp_path / "missing")

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == "workspace-missing"
    assert diagnostic.file == "case.yaml"
    assert diagnostic.field == "$"
    assert diagnostic.requirement == "FR-001"
    assert diagnostic.remediation


def test_missing_case_file_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "case-file-missing"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_case_file_symlink_escape_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("schema_version: 1\ncase: {id: x, title: x}\n")
    (workspace / "case.yaml").symlink_to(outside)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "case-file-outside-workspace"
    assert result.diagnostics[0].requirement == "NFR-004"


@pytest.mark.parametrize("content", ["case: [\n", "\xff"])
def test_malformed_or_non_utf8_yaml_is_distinct(tmp_path: Path, content: str) -> None:
    workspace = _workspace(tmp_path)
    if content == "\xff":
        (workspace / "case.yaml").write_bytes(b"\xff")
    else:
        (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert result.diagnostics[0].requirement == "FR-012"


def test_unsafe_yaml_constructor_is_rejected_without_execution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    marker = tmp_path / "executed"
    payload = f"!!python/object/apply:pathlib.Path.touch ['{marker}']\n"
    (workspace / "case.yaml").write_text(payload)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert not marker.exists()


@pytest.mark.parametrize("content", [None, [], "text", 42])
def test_non_mapping_document_is_malformed(tmp_path: Path, content: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "dossier-not-mapping"


def test_missing_schema_version_is_structural_failure(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"case": {"id": "x", "title": "X"}})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "schema-version-missing"
    assert result.diagnostics[0].field == "$.schema_version"


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_unsupported_schema_version_has_distinct_exit(tmp_path: Path, version: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": version, "case": {"id": "x", "title": "X"}})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "schema-version-unsupported"


@pytest.mark.parametrize(
    ("document", "field"),
    [
        ({"schema_version": 1, "case": {"id": "x", "title": "X"}, "extra": 1}, "$.extra"),
        (
            {"schema_version": 1, "case": {"id": "x", "title": "X", "extra": 1}},
            "$.case.extra",
        ),
    ],
)
def test_unknown_fields_fail_closed(tmp_path: Path, document: object, field: str) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, document)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "unknown-field"
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize(
    "case",
    [
        {},
        {"id": "x"},
        {"title": "X"},
        {"id": "", "title": "X"},
        {"id": "x", "title": ""},
        {"id": 1, "title": "X"},
        {"id": "x", "title": []},
    ],
)
def test_required_case_fields_are_validated(tmp_path: Path, case: object) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": 1, "case": case})

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.VALIDATION_FAILED
    assert result.diagnostics
    for diagnostic in result.diagnostics:
        assert diagnostic.file == "case.yaml"
        assert diagnostic.field.startswith("$")
        assert diagnostic.requirement == "FR-002"
        assert diagnostic.remediation


def test_validate_json_is_deterministic_and_actionable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _write_case(workspace, {"schema_version": 1, "case": {"unexpected": True}})

    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    first = capsys.readouterr()
    assert main(["validate", str(workspace), "--json"]) == ExitCode.VALIDATION_FAILED
    second = capsys.readouterr()

    assert first.out == second.out
    assert first.err == second.err == ""
    payload = json.loads(first.out)
    assert payload["status"] == "invalid"
    assert payload["exit_code"] == 12
    assert payload["diagnostics"]
    for diagnostic in payload["diagnostics"]:
        assert set(diagnostic) == {"field", "file", "id", "message", "remediation", "requirement"}


def test_validate_quiet_preserves_failure_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "missing"

    assert main(["validate", str(workspace), "--quiet"]) == ExitCode.VALIDATION_FAILED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_json_and_quiet_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["validate", str(tmp_path), "--json", "--quiet"])
    assert caught.value.code == ExitCode.USAGE


def test_internal_error_maps_to_stable_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_path: Path) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("archsift.cli.validate_workspace", boom)

    assert main(["validate", str(tmp_path)]) == ExitCode.INTERNAL_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "internal-error" in captured.err


def test_pathologically_nested_yaml_is_malformed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text("[" * 50_000 + "]" * 50_000)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_case_file_symlink_loop_is_unsafe_path(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "case.yaml").symlink_to("case.yaml")

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "case-file-unresolvable"


@pytest.mark.skipif(os.name == "nt", reason="Windows CI may not permit unprivileged symlinks")
def test_workspace_symlink_loop_is_unsafe_path(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to("loop")

    result = validate_workspace(loop)

    assert result.exit_code == ExitCode.UNSAFE_PATH
    assert result.diagnostics[0].id == "workspace-unresolvable"


def test_utf8_bom_in_case_yaml_is_accepted(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_bytes(
        b"\xef\xbb\xbf" + b"schema_version: 1\ncase: {id: x, title: X}\n"
    )

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.SUCCESS
    assert result.dossier is not None
    assert result.dossier.case.id == "x"


@pytest.mark.parametrize(
    "content",
    [
        "schema_version: 2\nschema_version: 1\ncase: {id: x, title: X}\n",
        "schema_version: 1\ncase:\n  id: a\n  id: b\n  title: X\n",
    ],
)
def test_duplicate_mapping_keys_are_rejected(tmp_path: Path, content: str) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "case.yaml").write_text(content)

    result = validate_workspace(workspace)

    assert result.exit_code == ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "malformed-yaml"
    assert "duplicate key" in result.diagnostics[0].message


def test_malformed_yaml_diagnostics_are_path_independent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _workspace(tmp_path / "one")
    second = _workspace(tmp_path / "two")
    content = "case: [\n"
    (first / "case.yaml").write_text(content)
    (second / "case.yaml").write_text(content)

    result_first = validate_workspace(first)
    result_second = validate_workspace(second)

    assert result_first.exit_code == result_second.exit_code == ExitCode.MALFORMED_INPUT
    assert [d.to_dict() for d in result_first.diagnostics] == [
        d.to_dict() for d in result_second.diagnostics
    ]
    message = result_first.diagnostics[0].message
    assert str(first) not in message
    assert str(second) not in message

    assert main(["validate", str(first), "--json"]) == ExitCode.MALFORMED_INPUT
    first_json = capsys.readouterr().out
    assert main(["validate", str(second), "--json"]) == ExitCode.MALFORMED_INPUT
    second_json = capsys.readouterr().out
    assert first_json == second_json
