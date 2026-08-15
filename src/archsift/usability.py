"""Deterministic validation for the independent usability protocols."""

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

PROTOCOL_VERSION_2 = "2.0.0"
RESULT_SCHEMA_VERSION_2 = 2
REQUIRED_SESSION_COUNT_2 = 4
REQUIRED_PASS_COUNT_2 = 3

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


@dataclass(frozen=True, slots=True)
class _CohortSpec:
    """One frozen protocol's schema, thresholds, and diagnostic wording."""

    schema_name: str
    schema_version: int
    protocol_version: str
    requirement: str
    session_count: int
    pass_count: int
    identity_key: str
    duplicate_id: str
    duplicate_message: str
    duplicate_remediation: str
    overall_remediation: str
    threshold_remediation: str


_V1_SPEC = _CohortSpec(
    schema_name="usability-results-v1",
    schema_version=RESULT_SCHEMA_VERSION,
    protocol_version=PROTOCOL_VERSION,
    requirement="USABILITY-1.0.0",
    session_count=REQUIRED_SESSION_COUNT,
    pass_count=REQUIRED_PASS_COUNT,
    identity_key="participant_id",
    duplicate_id="usability-participant-duplicate",
    duplicate_message="Participant IDs must be unique within the five-session cohort.",
    duplicate_remediation="Assign each independent session one unused pseudonymous participant ID.",
    overall_remediation="Claim met only when at least four of exactly five sessions pass.",
    threshold_remediation=(
        "Record a new precommitted five-session cohort; do not rewrite completed sessions."
    ),
)

_V2_SPEC = _CohortSpec(
    schema_name="usability-results-v2",
    schema_version=RESULT_SCHEMA_VERSION_2,
    protocol_version=PROTOCOL_VERSION_2,
    requirement="USABILITY-2.0.0",
    session_count=REQUIRED_SESSION_COUNT_2,
    pass_count=REQUIRED_PASS_COUNT_2,
    identity_key="agent_product",
    duplicate_id="usability-agent-product-duplicate",
    duplicate_message=(
        "Agent product names must be unique within the four-session simulated cohort."
    ),
    duplicate_remediation="Assign each independent simulated session one distinct agent product.",
    overall_remediation=(
        "Claim met only when at least three of exactly four simulated sessions pass."
    ),
    threshold_remediation=(
        "Record a new precommitted four-session simulated cohort; "
        "do not rewrite completed sessions."
    ),
)


class _DuplicateKeyError(ValueError):
    """A JSON object repeated a key."""


class _InvalidConstantError(ValueError):
    """JSON contained a non-standard numeric constant."""


def _diagnostic(
    id: str,
    message: str,
    field: str,
    remediation: str,
    requirement: str = _REQUIREMENT,
) -> Diagnostic:
    return Diagnostic(
        id=id,
        message=message,
        file="usability-results",
        field=field,
        requirement=requirement,
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
def _schema_validator(schema_name: str) -> Draft202012Validator:
    raw = json.loads(
        files("archsift").joinpath(f"schemas/{schema_name}.schema.json").read_text(encoding="utf-8")
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


def _select_spec(payload: dict[str, object]) -> _CohortSpec | None:
    for spec in (_V1_SPEC, _V2_SPEC):
        if (
            payload.get("schema_version") == spec.schema_version
            and payload.get("protocol_version") == spec.protocol_version
        ):
            return spec
    return None


def _unsupported_result(payload: dict[str, object]) -> UsabilityValidationResult:
    schema_version = payload.get("schema_version")
    declared_protocol = payload.get("protocol_version")
    protocol_text = declared_protocol if type(declared_protocol) is str else None
    if type(schema_version) is int and schema_version not in (
        RESULT_SCHEMA_VERSION,
        RESULT_SCHEMA_VERSION_2,
    ):
        return _result(
            ExitCode.UNSUPPORTED_SCHEMA,
            (
                _diagnostic(
                    "usability-schema-unsupported",
                    "The declared usability result schema version is unsupported.",
                    "$.schema_version",
                    f"Use schema version {RESULT_SCHEMA_VERSION} with protocol {PROTOCOL_VERSION}, "
                    f"or schema version {RESULT_SCHEMA_VERSION_2} with protocol "
                    f"{PROTOCOL_VERSION_2}.",
                ),
            ),
            protocol_version=protocol_text,
        )
    if type(declared_protocol) is str and declared_protocol not in (
        PROTOCOL_VERSION,
        PROTOCOL_VERSION_2,
    ):
        return _result(
            ExitCode.UNSUPPORTED_SCHEMA,
            (
                _diagnostic(
                    "usability-protocol-unsupported",
                    "The declared usability protocol version is unsupported.",
                    "$.protocol_version",
                    f"Use protocol version {PROTOCOL_VERSION} or {PROTOCOL_VERSION_2}.",
                ),
            ),
            protocol_version=declared_protocol,
        )
    if type(schema_version) is int:
        expected = (
            PROTOCOL_VERSION if schema_version == RESULT_SCHEMA_VERSION else PROTOCOL_VERSION_2
        )
        remediation = f"Use protocol version {expected} with schema version {schema_version}."
    else:
        remediation = (
            f"Declare schema version {RESULT_SCHEMA_VERSION} with protocol {PROTOCOL_VERSION}, "
            f"or schema version {RESULT_SCHEMA_VERSION_2} with protocol {PROTOCOL_VERSION_2}."
        )
    return _result(
        ExitCode.UNSUPPORTED_SCHEMA,
        (
            _diagnostic(
                "usability-protocol-unsupported",
                "The declared usability protocol version does not match the result schema version.",
                "$.protocol_version",
                remediation,
            ),
        ),
        protocol_version=protocol_text,
    )


def _validate_cohort(
    payload: object,
    spec: _CohortSpec,
    *,
    declared_protocol: str | None,
) -> UsabilityValidationResult:
    errors = sorted(_schema_validator(spec.schema_name).iter_errors(payload), key=_error_sort_key)
    if errors:
        first = errors[0]
        return _result(
            ExitCode.VALIDATION_FAILED,
            (
                _diagnostic(
                    "usability-results-contract",
                    f"The result data does not match the {spec.schema_name} contract.",
                    _path(first.absolute_path),
                    "Correct the named field using the protocol and packaged JSON schema.",
                ),
            ),
            protocol_version=declared_protocol,
        )

    result_payload = cast(dict[str, object], payload)
    sessions = cast(list[dict[str, object]], result_payload["sessions"])
    diagnostics: list[Diagnostic] = []
    identity_ids = [cast(str, session[spec.identity_key]) for session in sessions]
    if len(identity_ids) != len(set(identity_ids)):
        diagnostics.append(
            _diagnostic(
                spec.duplicate_id,
                spec.duplicate_message,
                "$.sessions",
                spec.duplicate_remediation,
                requirement=spec.requirement,
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
                    requirement=spec.requirement,
                )
            )

    criterion_met = passed_session_count >= spec.pass_count
    declared_met = result_payload["overall_result"] == "met"
    if declared_met != criterion_met:
        diagnostics.append(
            _diagnostic(
                "usability-overall-inconsistent",
                "The overall result conflicts with the derived session count.",
                "$.overall_result",
                spec.overall_remediation,
                requirement=spec.requirement,
            )
        )
    if not criterion_met:
        diagnostics.append(
            _diagnostic(
                "usability-threshold-not-met",
                "The independent usability success threshold was not met.",
                "$.sessions",
                spec.threshold_remediation,
                requirement=spec.requirement,
            )
        )

    return _result(
        ExitCode.VALIDATION_FAILED if diagnostics else ExitCode.SUCCESS,
        diagnostics,
        protocol_version=spec.protocol_version,
        session_count=len(sessions),
        passed_session_count=passed_session_count,
    )


def validate_usability_results(path: Path) -> UsabilityValidationResult:
    """Validate one completed protocol result file and its success threshold."""
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
        spec = _select_spec(payload)
        if spec is None:
            return _unsupported_result(payload)
        return _validate_cohort(payload, spec, declared_protocol=spec.protocol_version)
    return _validate_cohort(payload, _V1_SPEC, declared_protocol=None)


__all__ = [
    "PROTOCOL_VERSION",
    "PROTOCOL_VERSION_2",
    "REQUIRED_MILESTONES",
    "REQUIRED_PASS_COUNT",
    "REQUIRED_PASS_COUNT_2",
    "REQUIRED_SESSION_COUNT",
    "REQUIRED_SESSION_COUNT_2",
    "RESULT_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION_2",
    "UsabilityValidationResult",
    "validate_usability_results",
]
