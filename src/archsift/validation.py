"""Safe loading and structural validation of case dossiers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from archsift.diagnostics import Diagnostic, ExitCode


@dataclass(frozen=True, slots=True)
class CaseIdentity:
    """Validated minimal case identity."""

    id: str
    title: str


@dataclass(frozen=True, slots=True)
class Dossier:
    """Typed version-1 dossier envelope."""

    schema_version: int
    case: CaseIdentity


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Typed validation result, independent of terminal rendering."""

    exit_code: ExitCode
    dossier: Dossier | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


_SCHEMA_RESOURCE = "schemas/dossier-v1.schema.json"


def _diagnostic(
    identifier: str,
    message: str,
    field: str,
    requirement: str,
    remediation: str,
) -> Diagnostic:
    return Diagnostic(identifier, message, "case.yaml", field, requirement, remediation)


def _field_path(parts: Sequence[object]) -> str:
    return "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts)


def _schema() -> Mapping[str, Any]:
    content = files("archsift").joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")
    parsed: Any = json.loads(content)
    if not isinstance(parsed, Mapping):
        raise TypeError("packaged dossier schema must be an object")
    return parsed


def _remediation(error: ValidationError, field: str) -> str:
    if error.validator == "required":
        required = cast(Sequence[str], error.validator_value)
        instance = cast(Mapping[str, object], error.instance)
        missing = sorted(set(required) - set(instance))
        return f"Add the required field {field}.{missing[0]} using the documented schema."
    if error.validator == "additionalProperties":
        return "Remove the unknown field or use a supported schema version that defines it."
    if error.validator == "type":
        return f"Set {field} to a value of type {error.validator_value}."
    if error.validator == "minLength":
        return f"Set {field} to a non-empty string."
    return "Update the field to satisfy the packaged version-1 schema."


def _schema_diagnostics(error: ValidationError) -> tuple[Diagnostic, ...]:
    base_field = _field_path(list(error.absolute_path))
    if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
        error_schema = cast(Mapping[str, Any], error.schema)
        properties = cast(Mapping[str, Any], error_schema.get("properties", {}))
        unknown = sorted(set(error.instance) - set(properties))
        return tuple(
            _diagnostic(
                "unknown-field",
                f"Unknown field {name!r} is not permitted by schema version 1.",
                f"{base_field}.{name}",
                "FR-002",
                "Remove the unknown field or use a supported schema version that defines it.",
            )
            for name in unknown
        )
    return (
        _diagnostic(
            "schema-validation-failed",
            error.message,
            base_field,
            "FR-002",
            _remediation(error, base_field),
        ),
    )


def _case_file(workspace: Path) -> tuple[Path | None, ValidationResult | None]:
    try:
        root = workspace.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "workspace-missing",
                    "The case workspace directory does not exist.",
                    "$",
                    "FR-001",
                    "Create it with `archsift init <case>` or provide an existing workspace.",
                ),
            ),
        )
    if not root.is_dir():
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "workspace-not-directory",
                    "The case workspace path is not a directory.",
                    "$",
                    "FR-001",
                    "Provide the directory containing case.yaml.",
                ),
            ),
        )

    candidate = root / "case.yaml"
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        return None, ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "case-file-missing",
                    "The workspace does not contain case.yaml.",
                    "$",
                    "FR-001",
                    "Run `archsift init <case>` or add the required case.yaml file.",
                ),
            ),
        )
    if not resolved.is_relative_to(root):
        return None, ValidationResult(
            ExitCode.UNSAFE_PATH,
            diagnostics=(
                _diagnostic(
                    "case-file-outside-workspace",
                    "case.yaml resolves outside the case workspace.",
                    "$",
                    "NFR-004",
                    "Replace the link with a regular case.yaml file inside the workspace.",
                ),
            ),
        )
    if not resolved.is_file():
        return None, ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "case-file-not-regular",
                    "case.yaml is not a regular file.",
                    "$",
                    "FR-002",
                    "Replace it with a UTF-8 YAML file.",
                ),
            ),
        )
    return resolved, None


def validate_workspace(workspace: Path) -> ValidationResult:
    """Safely load and validate one versioned case workspace."""
    case_file, failure = _case_file(workspace)
    if failure is not None:
        return failure
    assert case_file is not None

    try:
        with case_file.open(encoding="utf-8") as stream:
            loaded: Any = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "malformed-yaml",
                    f"case.yaml is not valid UTF-8 YAML: {error}.",
                    "$",
                    "FR-012",
                    "Correct the YAML syntax and encoding, then run validation again.",
                ),
            ),
        )

    if not isinstance(loaded, Mapping):
        return ValidationResult(
            ExitCode.MALFORMED_INPUT,
            diagnostics=(
                _diagnostic(
                    "dossier-not-mapping",
                    "The dossier root must be a YAML mapping.",
                    "$",
                    "FR-002",
                    "Replace the document with a mapping containing schema_version and case.",
                ),
            ),
        )

    if "schema_version" not in loaded:
        return ValidationResult(
            ExitCode.VALIDATION_FAILED,
            diagnostics=(
                _diagnostic(
                    "schema-version-missing",
                    "The required schema_version field is missing.",
                    "$.schema_version",
                    "FR-002",
                    "Add `schema_version: 1` at the dossier root.",
                ),
            ),
        )
    if type(loaded["schema_version"]) is not int or loaded["schema_version"] != 1:
        return ValidationResult(
            ExitCode.UNSUPPORTED_SCHEMA,
            diagnostics=(
                _diagnostic(
                    "schema-version-unsupported",
                    f"Schema version {loaded['schema_version']!r} is not supported.",
                    "$.schema_version",
                    "FR-002",
                    "Use schema_version 1 or upgrade ArchSift when a newer version is supported.",
                ),
            ),
        )

    validator = Draft202012Validator(_schema())
    errors = sorted(
        validator.iter_errors(loaded),
        key=lambda item: (_field_path(list(item.absolute_path)), item.validator, item.message),
    )
    if errors:
        diagnostics = tuple(
            diagnostic for error in errors for diagnostic in _schema_diagnostics(error)
        )
        return ValidationResult(ExitCode.VALIDATION_FAILED, diagnostics=diagnostics)

    case = loaded["case"]
    assert isinstance(case, Mapping)
    dossier = Dossier(
        schema_version=1,
        case=CaseIdentity(id=str(case["id"]), title=str(case["title"])),
    )
    return ValidationResult(ExitCode.SUCCESS, dossier=dossier)
