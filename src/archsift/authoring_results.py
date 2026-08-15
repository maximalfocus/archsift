"""Offline validation for the independent simulated assisted-authoring protocol."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator

from archsift.diagnostics import Diagnostic, ExitCode

PROTOCOL_VERSION_1_0_0 = "1.0.0"
PROTOCOL_VERSION = "1.0.1"
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION_1_0_0, PROTOCOL_VERSION)
RESULT_SCHEMA_VERSION = 1
REQUIRED_SESSION_COUNT = 4
REQUIRED_PASS_COUNT = 3
REQUIRED_MILESTONES = (
    "register_material",
    "inspect_schema",
    "author_dossier",
    "complete_prerequisites",
    "validate",
    "assess",
)
MATERIAL_SET_CONTENT_IDENTITY = (
    "sha256:deca6741b7c69fbb313ed1292caa55a7a698eecb60f4a42aed849b3dcffd57ee"
)
MAX_RESULT_BYTES = 64 * 1024
_REQUIREMENT = "AUTHORING-RESULTS-v1"


@dataclass(frozen=True, slots=True)
class AuthoringValidationResult:
    """One deterministic authoring-result gate outcome."""

    exit_code: ExitCode
    diagnostics: tuple[Diagnostic, ...]
    protocol_version: str | None
    session_count: int
    passed_session_count: int
    criterion_met: bool


class _DuplicateKeyError(ValueError):
    pass


class _InvalidConstantError(ValueError):
    pass


class _InputFailure(ValueError):
    def __init__(self, exit_code: ExitCode, identifier: str, message: str) -> None:
        self.exit_code = exit_code
        self.identifier = identifier
        self.message = message
        super().__init__(message)


def _diagnostic(
    identifier: str,
    message: str,
    field: str,
    remediation: str,
) -> Diagnostic:
    return Diagnostic(
        id=identifier,
        message=message,
        file="authoring-results",
        field=field,
        requirement=_REQUIREMENT,
        remediation=remediation,
    )


def _result(
    exit_code: ExitCode,
    diagnostics: Iterable[Diagnostic] = (),
    *,
    protocol_version: str | None = None,
    session_count: int = 0,
    passed_session_count: int = 0,
) -> AuthoringValidationResult:
    return AuthoringValidationResult(
        exit_code=exit_code,
        diagnostics=tuple(diagnostics),
        protocol_version=protocol_version,
        session_count=session_count,
        passed_session_count=passed_session_count,
        criterion_met=exit_code is ExitCode.SUCCESS,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError
        value[key] = item
    return value


def _reject_constant(_: str) -> NoReturn:
    raise _InvalidConstantError


@cache
def _schema_validator() -> Draft202012Validator:
    raw = json.loads(
        files("archsift")
        .joinpath("schemas/authoring-results-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if type(raw) is not dict:
        raise TypeError("packaged authoring-result schema must be an object")
    schema = cast(dict[str, Any], raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _json_path(parts: Iterable[object]) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if type(part) is int else f".{part}"
    return rendered


def _read_contained_regular_file(path: Path) -> bytes:
    try:
        root = Path(".").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-root-unsafe",
            "The current authoring-result root cannot be resolved safely.",
        ) from error
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-outside-root",
            "The authoring-result path is outside the current authorised root.",
        ) from error
    if ".." in relative.parts:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-outside-root",
            "The authoring-result path is outside the current authorised root.",
        )
    current = root
    try:
        for segment in relative.parts:
            current = current / segment
            if stat.S_ISLNK(current.lstat().st_mode):
                raise _InputFailure(
                    ExitCode.UNSAFE_PATH,
                    "authoring-results-link-unsafe",
                    "The authoring-result path cannot contain symbolic links.",
                )
        resolved = candidate.resolve(strict=True)
    except _InputFailure:
        raise
    except (FileNotFoundError, NotADirectoryError) as error:
        raise _InputFailure(
            ExitCode.ARTEFACT_UNAVAILABLE,
            "authoring-results-unavailable",
            "The requested authoring-result file is unavailable.",
        ) from error
    except (OSError, RuntimeError) as error:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-path-unsafe",
            "The authoring-result path cannot be resolved safely.",
        ) from error
    if not resolved.is_relative_to(root):
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-outside-root",
            "The authoring-result path resolves outside the current authorised root.",
        )
    try:
        surface_before = resolved.lstat()
    except OSError as error:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-path-unsafe",
            "The authoring-result file cannot be inspected safely.",
        ) from error
    if not stat.S_ISREG(surface_before.st_mode):
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-not-regular",
            "The authoring-result input is not a regular file.",
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except (FileNotFoundError, PermissionError) as error:
        raise _InputFailure(
            ExitCode.ARTEFACT_UNAVAILABLE,
            "authoring-results-unavailable",
            "The requested authoring-result file cannot be read.",
        ) from error
    except OSError as error:
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-path-unsafe",
            "The authoring-result file cannot be opened safely.",
        ) from error
    try:
        opened = os.fstat(descriptor)
    except OSError as error:
        os.close(descriptor)
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-path-unsafe",
            "The opened authoring-result input cannot be inspected safely.",
        ) from error
    if not stat.S_ISREG(opened.st_mode):
        os.close(descriptor)
        raise _InputFailure(
            ExitCode.UNSAFE_PATH,
            "authoring-results-not-regular",
            "The opened authoring-result input is not a stable regular file.",
        )
    try:
        with os.fdopen(descriptor, "rb") as stream:
            surface = resolved.lstat()
            if not stat.S_ISREG(surface.st_mode) or not os.path.samestat(opened, surface):
                raise _InputFailure(
                    ExitCode.UNSAFE_PATH,
                    "authoring-results-not-regular",
                    "The opened authoring-result input is not a stable regular file.",
                )
            return stream.read(MAX_RESULT_BYTES + 1)
    except _InputFailure:
        raise
    except OSError as error:
        raise _InputFailure(
            ExitCode.ARTEFACT_UNAVAILABLE,
            "authoring-results-unavailable",
            "The requested authoring-result file cannot be read.",
        ) from error


def _input_failure(error: _InputFailure) -> AuthoringValidationResult:
    return _result(
        error.exit_code,
        (
            _diagnostic(
                error.identifier,
                error.message,
                "$",
                "Provide one readable regular result file beneath the current directory.",
            ),
        ),
    )


def _malformed(message: str) -> AuthoringValidationResult:
    return _result(
        ExitCode.MALFORMED_INPUT,
        (
            _diagnostic(
                "authoring-results-malformed",
                message,
                "$",
                (
                    "Provide one strict UTF-8 JSON object without duplicate keys or "
                    "non-standard numbers."
                ),
            ),
        ),
    )


def _unsupported(payload: dict[str, object]) -> AuthoringValidationResult:
    field = (
        "$.schema_version"
        if payload.get("schema_version") != RESULT_SCHEMA_VERSION
        else "$.protocol_version"
    )
    protocol = payload.get("protocol_version")
    return _result(
        ExitCode.UNSUPPORTED_SCHEMA,
        (
            _diagnostic(
                "authoring-results-version-unsupported",
                "The declared authoring-result schema and protocol versions are unsupported.",
                field,
                (
                    f"Use schema version {RESULT_SCHEMA_VERSION} with protocol "
                    f"{PROTOCOL_VERSION_1_0_0} or {PROTOCOL_VERSION}."
                ),
            ),
        ),
        protocol_version=protocol if type(protocol) is str else None,
    )


def _validate_payload(payload: object) -> AuthoringValidationResult:
    declared_protocol = (
        payload.get("protocol_version")
        if type(payload) is dict and type(payload.get("protocol_version")) is str
        else None
    )
    errors = sorted(
        _schema_validator().iter_errors(payload),
        key=lambda error: tuple((type(part).__name__, repr(part)) for part in error.absolute_path),
    )
    if errors:
        return _result(
            ExitCode.VALIDATION_FAILED,
            (
                _diagnostic(
                    "authoring-results-contract",
                    "The result data does not match the authoring-results-v1 contract.",
                    _json_path(errors[0].absolute_path),
                    "Correct the named field using a supported protocol and the packaged schema.",
                ),
            ),
            protocol_version=cast(str | None, declared_protocol),
        )
    result_payload = cast(dict[str, object], payload)
    sessions = cast(list[dict[str, object]], result_payload["sessions"])
    diagnostics: list[Diagnostic] = []
    session_ids = [cast(str, session["session_id"]) for session in sessions]
    products = [cast(str, session["agent_product"]) for session in sessions]
    if len(session_ids) != len(set(session_ids)):
        diagnostics.append(
            _diagnostic(
                "authoring-session-id-duplicate",
                "Session IDs must be unique within the four-session cohort.",
                "$.sessions",
                "Assign each independent session one unused pseudonymous session ID.",
            )
        )
    if len(products) != len(set(products)):
        diagnostics.append(
            _diagnostic(
                "authoring-agent-product-duplicate",
                "Agent product names must be unique within the four-session cohort.",
                "$.sessions",
                "Use four distinct agent products as required by the supported protocol.",
            )
        )
    if result_payload["material_set_content_identity"] != MATERIAL_SET_CONTENT_IDENTITY:
        diagnostics.append(
            _diagnostic(
                "authoring-material-set-mismatch",
                "The result does not bind the frozen protocol material set.",
                "$.material_set_content_identity",
                "Use the exact identity declared by authoring-material/manifest-v1.json.",
            )
        )

    passed = 0
    for index, session in enumerate(sessions):
        milestones = cast(dict[str, str], session["milestones"])
        derived = all(milestones[name] == "pass" for name in REQUIRED_MILESTONES) and not cast(
            bool, session["maintainer_intervention"]
        )
        if derived:
            passed += 1
        if (session["session_result"] == "pass") != derived:
            diagnostics.append(
                _diagnostic(
                    "authoring-session-inconsistent",
                    "The session result conflicts with its milestones or intervention state.",
                    f"$.sessions[{index}].session_result",
                    "Mark pass only when every milestone passes without intervention.",
                )
            )
    criterion_met = passed >= REQUIRED_PASS_COUNT
    if (result_payload["overall_result"] == "met") != criterion_met:
        diagnostics.append(
            _diagnostic(
                "authoring-overall-inconsistent",
                "The overall result conflicts with the derived passing-session count.",
                "$.overall_result",
                "Declare met only when at least three of exactly four sessions pass.",
            )
        )
    if not criterion_met:
        diagnostics.append(
            _diagnostic(
                "authoring-threshold-not-met",
                "The independent assisted-authoring threshold was not met.",
                "$.sessions",
                "Record a new precommitted cohort; do not rewrite completed sessions.",
            )
        )
    return _result(
        ExitCode.VALIDATION_FAILED if diagnostics else ExitCode.SUCCESS,
        diagnostics,
        protocol_version=cast(str, result_payload["protocol_version"]),
        session_count=len(sessions),
        passed_session_count=passed,
    )


def validate_authoring_results(path: Path) -> AuthoringValidationResult:
    """Validate one completed protocol result file and its success threshold."""
    try:
        content = _read_contained_regular_file(path)
    except _InputFailure as error:
        return _input_failure(error)
    if len(content) > MAX_RESULT_BYTES:
        return _malformed("The authoring-result file exceeds the supported size limit.")
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError:
        return _malformed("The authoring-result file is not valid UTF-8.")
    except (json.JSONDecodeError, _DuplicateKeyError, _InvalidConstantError, RecursionError):
        return _malformed("The authoring-result file is not strict JSON.")
    if type(payload) is dict and (
        payload.get("schema_version") != RESULT_SCHEMA_VERSION
        or payload.get("protocol_version") not in SUPPORTED_PROTOCOL_VERSIONS
    ):
        return _unsupported(payload)
    return _validate_payload(payload)


__all__ = [
    "MATERIAL_SET_CONTENT_IDENTITY",
    "PROTOCOL_VERSION",
    "PROTOCOL_VERSION_1_0_0",
    "REQUIRED_MILESTONES",
    "REQUIRED_PASS_COUNT",
    "REQUIRED_SESSION_COUNT",
    "RESULT_SCHEMA_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "AuthoringValidationResult",
    "validate_authoring_results",
]
