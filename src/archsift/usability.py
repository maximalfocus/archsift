"""Deterministic validation for the independent usability protocol."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator

from archsift.diagnostics import Diagnostic, ExitCode

PROTOCOL_VERSION = "1.0.0"
RESULT_SCHEMA_VERSION = 1
REQUIRED_MILESTONES = ("initialize", "complete", "validate", "assess")
REQUIRED_SESSION_COUNT = 5
REQUIRED_PASS_COUNT = 4
MAX_RESULT_BYTES = 64 * 1024
_REQUIREMENT = "USABILITY-1.0.0"


@dataclass(frozen=True, slots=True)
class UsabilityValidationResult:
    """One deterministic usability-result gate outcome."""

    exit_code: ExitCode
    diagnostics: tuple[Diagnostic, ...]
    protocol_version: str | None
    session_count: int
    passed_session_count: int
    criterion_met: bool


class _DuplicateKeyError(ValueError):
    """A JSON object repeated a key."""


class _InvalidConstantError(ValueError):
    """JSON contained a non-standard numeric constant."""


def _diagnostic(
    id: str,
    message: str,
    field: str,
    remediation: str,
) -> Diagnostic:
    return Diagnostic(
        id=id,
        message=message,
        file="usability-results",
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
) -> UsabilityValidationResult:
    return UsabilityValidationResult(
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
        .joinpath("schemas/usability-results-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if type(raw) is not dict:
        raise TypeError("packaged usability schema must be an object")
    schema = cast(dict[str, Any], raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _path(parts: Iterable[object]) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if type(part) is int else f".{part}"
    return rendered


def _error_sort_key(error: object) -> tuple[tuple[str, str], ...]:
    path = cast(Any, error).absolute_path
    return tuple((type(part).__name__, repr(part)) for part in path)


def _malformed(message: str, remediation: str) -> UsabilityValidationResult:
    return _result(
        ExitCode.MALFORMED_INPUT,
        (_diagnostic("usability-results-malformed", message, "$", remediation),),
    )


def validate_usability_results(path: Path) -> UsabilityValidationResult:
    """Validate one completed protocol-1.0.0 result file and its success threshold."""
    try:
        content = path.read_bytes()
    except OSError:
        return _result(
            ExitCode.ARTEFACT_UNAVAILABLE,
            (
                _diagnostic(
                    "usability-results-unavailable",
                    "The requested usability result file is unavailable.",
                    "$",
                    "Provide a readable regular JSON file.",
                ),
            ),
        )
    if len(content) > MAX_RESULT_BYTES:
        return _malformed(
            "The usability result file exceeds the supported size limit.",
            f"Provide a result file no larger than {MAX_RESULT_BYTES} bytes.",
        )
    try:
        text = content.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError:
        return _malformed(
            "The usability result file is not valid UTF-8.",
            "Encode the completed JSON result as UTF-8.",
        )
    except (json.JSONDecodeError, _DuplicateKeyError, _InvalidConstantError, RecursionError):
        return _malformed(
            "The usability result file is not strict JSON.",
            "Provide one JSON object without duplicate keys or non-standard numbers.",
        )

    if type(payload) is dict:
        declared_protocol = payload.get("protocol_version")
        if type(declared_protocol) is str and declared_protocol != PROTOCOL_VERSION:
            return _result(
                ExitCode.UNSUPPORTED_SCHEMA,
                (
                    _diagnostic(
                        "usability-protocol-unsupported",
                        "The declared usability protocol version is unsupported.",
                        "$.protocol_version",
                        f"Use protocol version {PROTOCOL_VERSION}.",
                    ),
                ),
                protocol_version=declared_protocol,
            )

    errors = sorted(_schema_validator().iter_errors(payload), key=_error_sort_key)
    if errors:
        first = errors[0]
        return _result(
            ExitCode.VALIDATION_FAILED,
            (
                _diagnostic(
                    "usability-results-contract",
                    "The result data does not match the usability-results-v1 contract.",
                    _path(first.absolute_path),
                    "Correct the named field using the protocol and packaged JSON schema.",
                ),
            ),
            protocol_version=(
                cast(str, payload["protocol_version"])
                if type(payload) is dict and type(payload.get("protocol_version")) is str
                else None
            ),
        )

    result_payload = cast(dict[str, object], payload)
    sessions = cast(list[dict[str, object]], result_payload["sessions"])
    diagnostics: list[Diagnostic] = []
    participant_ids = [cast(str, session["participant_id"]) for session in sessions]
    if len(participant_ids) != len(set(participant_ids)):
        diagnostics.append(
            _diagnostic(
                "usability-participant-duplicate",
                "Participant IDs must be unique within the five-session cohort.",
                "$.sessions",
                "Assign each independent session one unused pseudonymous participant ID.",
            )
        )

    passed_session_count = 0
    for index, session in enumerate(sessions):
        milestones = cast(dict[str, str], session["milestones"])
        derived_pass = all(milestones[name] == "pass" for name in REQUIRED_MILESTONES) and not cast(
            bool, session["maintainer_intervention"]
        )
        declared_pass = session["session_result"] == "pass"
        if derived_pass:
            passed_session_count += 1
        if declared_pass != derived_pass:
            diagnostics.append(
                _diagnostic(
                    "usability-session-inconsistent",
                    "The session outcome conflicts with its milestones or intervention state.",
                    f"$.sessions[{index}].session_result",
                    "Mark the session pass only when all milestones pass without intervention.",
                )
            )

    criterion_met = passed_session_count >= REQUIRED_PASS_COUNT
    declared_met = result_payload["overall_result"] == "met"
    if declared_met != criterion_met:
        diagnostics.append(
            _diagnostic(
                "usability-overall-inconsistent",
                "The overall result conflicts with the derived session count.",
                "$.overall_result",
                "Claim met only when at least four of exactly five sessions pass.",
            )
        )
    if not criterion_met:
        diagnostics.append(
            _diagnostic(
                "usability-threshold-not-met",
                "The independent usability success threshold was not met.",
                "$.sessions",
                "Record a new precommitted five-session cohort; do not rewrite completed sessions.",
            )
        )

    return _result(
        ExitCode.VALIDATION_FAILED if diagnostics else ExitCode.SUCCESS,
        diagnostics,
        protocol_version=PROTOCOL_VERSION,
        session_count=len(sessions),
        passed_session_count=passed_session_count,
    )


__all__ = [
    "PROTOCOL_VERSION",
    "REQUIRED_MILESTONES",
    "REQUIRED_PASS_COUNT",
    "REQUIRED_SESSION_COUNT",
    "RESULT_SCHEMA_VERSION",
    "UsabilityValidationResult",
    "validate_usability_results",
]
