"""Read-only deterministic comparison of canonical decision records."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from enum import StrEnum
from functools import cache
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

from archsift.canonical import JsonObject, JsonValue, canonical_json_bytes
from archsift.decision_record import RECORD_SCHEMA_VERSION
from archsift.diagnostics import ExitCode
from archsift.masking import MASKING_POLICY_VERSION

COMPARISON_SCHEMA_VERSION = 4
_SUPPORTED_RECORD_SCHEMAS = {1, RECORD_SCHEMA_VERSION}

_RECORD_KEYS = {
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
}
_ASSESSMENT_KEYS = {
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
}
_PREREQUISITE_FINDING_KEYS = {
    "consequence",
    "counterpart",
    "effect",
    "evidence_ids",
    "field",
    "message",
    "remediation",
    "requirement",
    "rule_id",
}
_DECISION_FINDING_KEYS = {
    "action_ids",
    "candidate_id",
    "consequence",
    "control_class",
    "criterion_id",
    "criterion_kind",
    "effect",
    "evidence_ids",
    "message",
    "requirement",
    "rule_id",
}
_EFFECTS = {
    "block",
    "require-evidence",
    "support-candidate",
    "constrain-autonomy",
    "non-decisive",
}
_CONTROL_CLASSES = {
    "human-owned-work",
    "process-redesign",
    "deterministic-automation",
    "fixed-ai-workflow",
    "agentic-control",
}
_OPTIONAL_DOSSIER_SECTIONS = {
    "agency_necessity",
    "autonomy_permission",
    "candidate_comparison",
    "problem_value",
    "task",
}
_VERDICTS = {
    "supported",
    "conditional",
    "insufficient-evidence",
    "no-permissible-candidate",
    "no-technology-change",
}
_VERDICT_FIELDS = (
    ("verdict", "verdict"),
    ("verdict_rule", "verdict_rule_id"),
    ("recommended_class", "recommended_class"),
    ("surviving_candidate_ids", "surviving_candidate_ids"),
    ("evidence_state", "evidence_state"),
    ("unmet_condition_ids", "unmet_conditions"),
)


class ComparisonInputFailure(StrEnum):
    """Stable failure categories at the comparison input boundary."""

    ROOT_UNAVAILABLE = "root-unavailable"
    TARGET_MISSING = "target-missing"
    TARGET_UNRESOLVABLE = "target-unresolvable"
    TARGET_OUTSIDE_ROOT = "target-outside-root"
    TARGET_NOT_REGULAR = "target-not-regular"
    TARGET_UNREADABLE = "target-unreadable"
    INVALID_UTF8 = "invalid-utf8"
    INVALID_JSON = "invalid-json"
    MALFORMED_RECORD = "malformed-record"
    UNSUPPORTED_SCHEMA = "unsupported-schema"


class ComparisonInputError(ValueError):
    """One safely classified comparison input failure."""

    def __init__(
        self,
        category: ComparisonInputFailure,
        role: str,
        field: str,
        message: str,
        remediation: str,
    ) -> None:
        self.category = category
        self.role = role
        self.field = field
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    @property
    def exit_code(self) -> ExitCode:
        """Map the stable input category to the public CLI contract."""
        if self.category is ComparisonInputFailure.UNSUPPORTED_SCHEMA:
            return ExitCode.UNSUPPORTED_SCHEMA
        if self.category in {
            ComparisonInputFailure.INVALID_UTF8,
            ComparisonInputFailure.INVALID_JSON,
            ComparisonInputFailure.MALFORMED_RECORD,
        }:
            return ExitCode.MALFORMED_INPUT
        if self.category in {
            ComparisonInputFailure.TARGET_MISSING,
            ComparisonInputFailure.TARGET_UNREADABLE,
        }:
            return ExitCode.ARTEFACT_UNAVAILABLE
        return ExitCode.UNSAFE_PATH


def _input_error(
    category: ComparisonInputFailure,
    role: str,
    field: str,
    message: str,
    remediation: str,
) -> ComparisonInputError:
    return ComparisonInputError(category, role, field, message, remediation)


def _identity(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


@cache
def _dossier_validator(schema_version: int) -> Draft202012Validator:
    raw = json.loads(
        files("archsift")
        .joinpath(f"schemas/dossier-v{schema_version}.schema.json")
        .read_text(encoding="utf-8")
    )
    if type(raw) is not dict:
        raise TypeError("packaged dossier schema must be an object")
    return Draft202012Validator(cast(dict[str, Any], raw), format_checker=FormatChecker())


def _require_identity(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 content identity")
    return value


def _require_object(value: object, field: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _require_keys(value: dict[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{field} has an unsupported field contract")


def _require_list(value: object, field: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{field} must be an array")
    return cast(list[object], value)


def _require_text(value: object, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value:
        raise ValueError(f"{field} must be non-empty text")
    return value


def _require_string_list(value: object, field: str) -> list[str]:
    items = _require_list(value, field)
    if not all(type(item) is str for item in items):
        raise ValueError(f"{field} must contain only text")
    return cast(list[str], items)


def _validate_json_value(value: object, field: str = "$") -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is list:
        for index, item in enumerate(cast(list[object], value)):
            _validate_json_value(item, f"{field}[{index}]")
        return
    if type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            if type(key) is not str:
                raise ValueError(f"{field} has a non-text key")
            _validate_json_value(item, f"{field}.{key}")
        return
    raise ValueError(f"{field} contains a non-canonical JSON value")


def _authored_schema_view(dossier: JsonObject) -> JsonObject:
    """Remove only the optional top-level nulls added by canonical serialization."""
    return {
        key: value
        for key, value in dossier.items()
        if value is not None or key not in _OPTIONAL_DOSSIER_SECTIONS
    }


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _resolve_record(path: Path, *, root: Path, role: str) -> Path:
    try:
        authorised_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _input_error(
            ComparisonInputFailure.ROOT_UNAVAILABLE,
            role,
            "$",
            "The comparison root cannot be resolved to an authorised directory.",
            "Run compare from an existing resolvable directory containing both records.",
        ) from error
    if not authorised_root.is_dir():
        raise _input_error(
            ComparisonInputFailure.ROOT_UNAVAILABLE,
            role,
            "$",
            "The comparison root is not an authorised directory.",
            "Run compare from the directory containing both decision records.",
        )
    candidate = path if path.is_absolute() else authorised_root / path
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_MISSING,
            role,
            "$",
            "The decision-record file does not exist.",
            "Provide an existing canonical JSON decision-record file.",
        ) from error
    except (OSError, RuntimeError) as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_UNRESOLVABLE,
            role,
            "$",
            "The decision-record path cannot be resolved safely.",
            "Remove unsafe or looping links and provide a resolvable record path.",
        ) from error
    if not resolved.is_relative_to(authorised_root):
        raise _input_error(
            ComparisonInputFailure.TARGET_OUTSIDE_ROOT,
            role,
            "$",
            "The decision-record path resolves outside the comparison root.",
            "Place the record beneath the current directory and use that contained path.",
        )
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_UNRESOLVABLE,
            role,
            "$",
            "The decision-record file cannot be inspected safely.",
            "Provide a resolvable regular file beneath the current directory.",
        ) from error
    if not stat.S_ISREG(mode):
        raise _input_error(
            ComparisonInputFailure.TARGET_NOT_REGULAR,
            role,
            "$",
            "The decision-record path is not a regular file.",
            "Provide a regular canonical JSON decision-record file.",
        )
    return resolved


def _read_record_bytes(path: Path, *, role: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_MISSING,
            role,
            "$",
            "The decision-record file disappeared before it could be read.",
            "Provide an existing stable canonical JSON decision-record file.",
        ) from error
    except PermissionError as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_UNREADABLE,
            role,
            "$",
            "The decision-record file cannot be read.",
            "Grant read access or provide another readable canonical record.",
        ) from error
    except OSError as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_UNRESOLVABLE,
            role,
            "$",
            "The decision-record file cannot be opened safely.",
            "Remove unsafe links and provide a stable regular file.",
        ) from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            try:
                surface = path.lstat()
            except OSError as error:
                raise _input_error(
                    ComparisonInputFailure.TARGET_UNRESOLVABLE,
                    role,
                    "$",
                    "The decision-record path changed while it was being opened.",
                    "Provide a stable regular canonical JSON decision-record file.",
                ) from error
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(surface.st_mode)
                or not os.path.samestat(opened, surface)
            ):
                raise _input_error(
                    ComparisonInputFailure.TARGET_NOT_REGULAR,
                    role,
                    "$",
                    "The opened decision-record input is not a regular file.",
                    "Provide a regular canonical JSON decision-record file.",
                )
            return stream.read()
    except ComparisonInputError:
        raise
    except OSError as error:
        raise _input_error(
            ComparisonInputFailure.TARGET_UNREADABLE,
            role,
            "$",
            "The decision-record file cannot be read.",
            "Grant read access or provide another readable canonical record.",
        ) from error


def _parse_record(content: bytes, *, role: str) -> JsonObject:
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise _input_error(
            ComparisonInputFailure.INVALID_UTF8,
            role,
            "$",
            "The decision-record file is not valid UTF-8.",
            "Replace it with the exact canonical JSON bytes emitted by assess.",
        ) from error
    try:
        loaded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"unsupported JSON constant {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise _input_error(
            ComparisonInputFailure.INVALID_JSON,
            role,
            "$",
            "The decision-record file is not unambiguous JSON.",
            "Replace it with the exact canonical JSON bytes emitted by assess.",
        ) from error
    try:
        _validate_json_value(loaded)
        record = _require_object(loaded, "$")
        schema = record.get("record_schema_version")
        if type(schema) is int and schema not in _SUPPORTED_RECORD_SCHEMAS:
            raise _input_error(
                ComparisonInputFailure.UNSUPPORTED_SCHEMA,
                role,
                "$.record_schema_version",
                f"Decision-record schema version {schema} is not supported.",
                "Use record schema version 1 or 2, or upgrade ArchSift.",
            )
        _validate_record(record)
        canonical = canonical_json_bytes(cast(JsonObject, record))
        if canonical != content:
            raise ValueError("record bytes are not canonical JSON")
        return cast(JsonObject, record)
    except ComparisonInputError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise _input_error(
            ComparisonInputFailure.MALFORMED_RECORD,
            role,
            "$",
            "The JSON is not a well-formed canonical decision record.",
            "Regenerate the record with assess and compare the immutable generated JSON file.",
        ) from error


def _validate_finding(value: object, *, prerequisite: bool, field: str) -> None:
    finding = _require_object(value, field)
    _require_keys(
        finding,
        _PREREQUISITE_FINDING_KEYS if prerequisite else _DECISION_FINDING_KEYS,
        field,
    )
    _require_text(finding["rule_id"], f"{field}.rule_id")
    effect = _require_text(finding["effect"], f"{field}.effect")
    if effect not in _EFFECTS:
        raise ValueError(f"{field}.effect is unsupported")
    evidence_ids = _require_string_list(finding["evidence_ids"], f"{field}.evidence_ids")
    if evidence_ids != sorted(set(evidence_ids)):
        raise ValueError(f"{field}.evidence_ids must be a sorted unique union")
    if prerequisite:
        _require_text(finding["field"], f"{field}.field")
        _require_text(finding["counterpart"], f"{field}.counterpart", nullable=True)
    else:
        _require_text(finding["candidate_id"], f"{field}.candidate_id", nullable=True)
        _require_text(finding["control_class"], f"{field}.control_class", nullable=True)
        if (finding["candidate_id"] is None) != (finding["control_class"] is None):
            raise ValueError(f"{field} candidate and control class must be both present or absent")
        for name in ("criterion_id", "criterion_kind"):
            _require_text(finding[name], f"{field}.{name}")
        _require_string_list(finding["action_ids"], f"{field}.action_ids")


def _validate_assessment(value: object, *, ruleset_version: str, dossier_schema: int) -> None:
    assessment = _require_object(value, "$.assessment")
    _require_keys(assessment, _ASSESSMENT_KEYS, "$.assessment")
    if assessment["schema_version"] != dossier_schema:
        raise ValueError("assessment schema version is inconsistent")
    if assessment["ruleset_version"] != ruleset_version:
        raise ValueError("assessment ruleset version is inconsistent")
    for name in (
        "active_hard_veto_ids",
        "mandatory_human_control_ids",
        "surviving_candidate_ids",
    ):
        _require_string_list(assessment[name], f"$.assessment.{name}")
    for name in ("verdict", "verdict_rule_id", "evidence_state"):
        _require_text(assessment[name], f"$.assessment.{name}")
    if assessment["verdict"] not in _VERDICTS:
        raise ValueError("assessment verdict is unsupported")
    if assessment["evidence_state"] not in {"evidence-complete", "evidence-incomplete"}:
        raise ValueError("assessment evidence state is unsupported")
    recommended = _require_text(
        assessment["recommended_class"], "$.assessment.recommended_class", nullable=True
    )
    if recommended is not None and recommended not in _CONTROL_CLASSES:
        raise ValueError("assessment recommended class is unsupported")
    conditions = _require_list(assessment["unmet_conditions"], "$.assessment.unmet_conditions")
    condition_ids: set[str] = set()
    for index, raw in enumerate(conditions):
        condition = _require_object(raw, f"$.assessment.unmet_conditions[{index}]")
        _require_keys(
            condition,
            {
                "decision_area",
                "evidence_ids",
                "id",
                "resolved_by",
                "statement",
                "status",
                "target_control_class",
            },
            "unmet condition",
        )
        identifier = cast(str, _require_text(condition.get("id"), "unmet condition id"))
        if identifier in condition_ids:
            raise ValueError("unmet condition IDs must be unique")
        condition_ids.add(identifier)
        _require_string_list(condition["evidence_ids"], "unmet condition evidence IDs")
        for name in ("decision_area", "resolved_by", "statement", "status"):
            _require_text(condition[name], f"unmet condition {name}")
        target_class = _require_text(
            condition["target_control_class"], "unmet condition target class"
        )
        if target_class not in _CONTROL_CLASSES:
            raise ValueError("unmet condition target class is unsupported")

    prerequisite = _require_object(
        assessment["prerequisite_evaluation"], "$.assessment.prerequisite_evaluation"
    )
    _require_keys(prerequisite, {"findings", "ready", "ruleset_version"}, "prerequisite")
    if (
        prerequisite["ruleset_version"] != ruleset_version
        or type(prerequisite["ready"]) is not bool
    ):
        raise ValueError("prerequisite evaluation is inconsistent")
    for index, finding in enumerate(_require_list(prerequisite["findings"], "findings")):
        _validate_finding(finding, prerequisite=True, field=f"prerequisite.findings[{index}]")

    ordered = _require_object(
        assessment["ordered_elimination_evaluation"],
        "$.assessment.ordered_elimination_evaluation",
    )
    _require_keys(
        ordered,
        {"candidates", "control_classes", "findings", "least_surviving_class", "ruleset_version"},
        "ordered elimination",
    )
    if ordered["ruleset_version"] != ruleset_version:
        raise ValueError("ordered-elimination ruleset version is inconsistent")
    candidates = _require_list(ordered["candidates"], "ordered candidates")
    for index, raw in enumerate(candidates):
        candidate = _require_object(raw, f"ordered candidates[{index}]")
        _require_keys(candidate, {"candidate_id", "control_class", "disposition"}, "candidate")
        _require_text(candidate["candidate_id"], "candidate id")
        if candidate["control_class"] not in _CONTROL_CLASSES:
            raise ValueError("candidate control class is unsupported")
        if candidate["disposition"] not in {"eliminated", "undetermined", "survives"}:
            raise ValueError("candidate disposition is unsupported")
    classes = _require_list(ordered["control_classes"], "ordered control classes")
    for index, raw in enumerate(classes):
        control_class = _require_object(raw, f"ordered control classes[{index}]")
        _require_keys(
            control_class,
            {"candidate_ids", "control_class", "disposition"},
            "control class",
        )
        _require_string_list(control_class["candidate_ids"], "control-class candidate IDs")
        if control_class["control_class"] not in _CONTROL_CLASSES:
            raise ValueError("ordered control class is unsupported")
        if control_class["disposition"] not in {"eliminated", "undetermined", "survives"}:
            raise ValueError("control-class disposition is unsupported")
    least_class = _require_text(
        ordered["least_surviving_class"], "least surviving class", nullable=True
    )
    if least_class is not None and least_class not in _CONTROL_CLASSES:
        raise ValueError("least surviving class is unsupported")
    for index, finding in enumerate(_require_list(ordered["findings"], "findings")):
        _validate_finding(finding, prerequisite=False, field=f"ordered.findings[{index}]")


def _validate_masking_declaration(value: object) -> None:
    """Validate the NFR-009 disclosure on a masked decision-record file.

    A masked presentation declares the policy that transformed its emitted
    field values. The canonical dossier bytes, evidence content identities and
    record content identity that address the immutable record cannot be
    recomputed from masked bytes, so the file's declared identities are
    checked for shape while every structural, schema, and cross-reference
    check still applies.
    """
    declaration = _require_object(value, "$.masking")
    _require_keys(declaration, {"applied", "policy_version", "warning"}, "$.masking")
    if declaration["applied"] is not True:
        raise ValueError("masking disclosure must declare masking applied")
    if declaration["policy_version"] != MASKING_POLICY_VERSION:
        raise ValueError("masking policy version is unsupported")
    _require_text(declaration["warning"], "$.masking.warning")


def _validate_graph_use(value: object, assessment: dict[str, object]) -> None:
    graph_use = _require_object(value, "$.graph_use")
    _require_keys(
        graph_use,
        {
            "case_view_content_identity",
            "finding_relevant_nodes",
            "finding_relevant_relations",
            "graph_schema_version",
            "graph_snapshot_content_identity",
            "graph_version",
            "supported_finding_rule_ids",
        },
        "$.graph_use",
    )
    if graph_use["graph_schema_version"] != 1:
        raise ValueError("graph-use schema version is unsupported")
    version = cast(str, _require_text(graph_use["graph_version"], "graph-use version"))
    if (
        len(version) != 68
        or not version.startswith("gv1:")
        or any(character not in "0123456789abcdef" for character in version[4:])
    ):
        raise ValueError("graph-use immutable graph version is invalid")
    _require_identity(
        graph_use["graph_snapshot_content_identity"], "graph snapshot content identity"
    )
    _require_identity(graph_use["case_view_content_identity"], "case-view content identity")
    supported = _require_string_list(
        graph_use["supported_finding_rule_ids"], "supported finding rule IDs"
    )
    if not supported or supported != sorted(set(supported)):
        raise ValueError("supported finding rule IDs require canonical unique order")
    prerequisite = cast(dict[str, object], assessment["prerequisite_evaluation"])
    ordered = cast(dict[str, object], assessment["ordered_elimination_evaluation"])
    emitted = {
        cast(str, finding["rule_id"])
        for finding in (
            *cast(list[dict[str, object]], prerequisite["findings"]),
            *cast(list[dict[str, object]], ordered["findings"]),
        )
        if cast(list[object], finding["evidence_ids"])
    }
    if not set(supported).issubset(emitted):
        raise ValueError("graph use names a rule ID not emitted with case evidence")
    for name in ("finding_relevant_nodes", "finding_relevant_relations"):
        references = _require_list(graph_use[name], f"$.graph_use.{name}")
        identifiers: list[str] = []
        if not references:
            raise ValueError(f"graph use {name} cannot be empty")
        for index, raw in enumerate(references):
            reference = _require_object(raw, f"$.graph_use.{name}[{index}]")
            _require_keys(reference, {"content_identity", "id"}, "graph entry reference")
            identifiers.append(cast(str, _require_text(reference["id"], "graph entry semantic ID")))
            _require_identity(reference["content_identity"], "graph entry content identity")
        if identifiers != sorted(set(identifiers)):
            raise ValueError(f"graph use {name} require canonical unique order")


def _validate_record(record: dict[str, object]) -> None:
    masked = record.get("masking") is not None
    if masked:
        _validate_masking_declaration(record["masking"])
    optional = ({"masking"} if masked else set()) | (
        {"graph_use"} if "graph_use" in record else set()
    )
    _require_keys(record, _RECORD_KEYS | optional, "$")
    record_schema = record["record_schema_version"]
    if type(record_schema) is not int or record_schema not in _SUPPORTED_RECORD_SCHEMAS:
        raise ValueError("record schema version is missing or unsupported")
    record_identity = _require_identity(record["record_content_identity"], "record identity")
    dossier_schema = record["dossier_schema_version"]
    supported_dossiers = {1, 2} if record_schema == 1 else {1, 2, 3, 4}
    if type(dossier_schema) is not int or dossier_schema not in supported_dossiers:
        raise ValueError("dossier schema version is unsupported")
    ruleset_version = cast(str, _require_text(record["ruleset_version"], "ruleset version"))
    _require_text(record["tool_version"], "tool version")

    dossier = _require_object(record["dossier"], "$.dossier")
    if dossier.get("schema_version") != dossier_schema:
        raise ValueError("dossier schema version is inconsistent")
    schema_view = _authored_schema_view(cast(JsonObject, dossier))
    if next(_dossier_validator(dossier_schema).iter_errors(schema_view), None) is not None:
        raise ValueError(f"embedded dossier does not satisfy schema version {dossier_schema}")
    evidence = _require_list(dossier.get("evidence"), "$.dossier.evidence")
    if dossier_schema in {2, 3, 4} and any(
        type(entry) is not dict or "authorship" not in entry for entry in evidence
    ):
        raise ValueError("canonical schema-version-2 record evidence lacks effective authorship")
    dossier_identity = _require_identity(record["dossier_content_identity"], "dossier identity")
    if not masked and dossier_identity != _identity(
        canonical_json_bytes(cast(JsonObject, dossier))
    ):
        raise ValueError("dossier content identity is inconsistent")

    configuration = _require_object(record["configuration"], "$.configuration")
    _require_keys(configuration, {"entries", "schema_version"}, "$.configuration")
    if configuration["schema_version"] != 1:
        raise ValueError("configuration schema version is unsupported")
    entries = _require_list(configuration["entries"], "$.configuration.entries")
    keys: list[str] = []
    for index, raw in enumerate(entries):
        entry = _require_object(raw, f"$.configuration.entries[{index}]")
        _require_keys(entry, {"key", "value"}, "configuration entry")
        keys.append(cast(str, _require_text(entry["key"], "configuration key")))
        _require_text(entry["value"], "configuration value")
    if keys != sorted(set(keys)):
        raise ValueError("configuration entries are not in canonical unique order")
    configuration_identity = _require_identity(
        record["configuration_content_identity"], "configuration identity"
    )
    if not masked and configuration_identity != _identity(
        canonical_json_bytes(cast(JsonObject, configuration))
    ):
        raise ValueError("configuration content identity is inconsistent")

    evidence_links = _require_object(record["evidence_links"], "$.evidence_links")
    evidence_by_id: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(evidence):
        entry = _require_object(raw, f"$.dossier.evidence[{index}]")
        identifier = cast(str, _require_text(entry.get("id"), "evidence id"))
        if identifier in evidence_by_id:
            raise ValueError("evidence IDs must be unique")
        evidence_by_id[identifier] = entry
    if set(evidence_links) != set(evidence_by_id):
        raise ValueError("evidence links do not match the dossier evidence ledger")
    for identifier, raw in evidence_links.items():
        link = _require_object(raw, f"$.evidence_links.{identifier}")
        _require_keys(link, {"content_identity", "evidence_id", "kind"}, "evidence link")
        if link["evidence_id"] != identifier or link["kind"] != evidence_by_id[identifier].get(
            "kind"
        ):
            raise ValueError("evidence link identity or kind is inconsistent")
        content_identity = _require_identity(link["content_identity"], "evidence content identity")
        if not masked and content_identity != _identity(
            canonical_json_bytes(cast(JsonObject, evidence_by_id[identifier]))
        ):
            raise ValueError("evidence content identity is inconsistent")

    artefact_links = _require_list(record["artefact_links"], "$.artefact_links")
    artefact_keys: set[tuple[str, str]] = set()
    actual_artefact_contract: set[tuple[str, str, str, str]] = set()
    registration_contracts: dict[str, tuple[object, object, object]] = {}
    for index, raw in enumerate(artefact_links):
        link = _require_object(raw, f"$.artefact_links[{index}]")
        link_keys = {
            "artefact_id",
            "byte_length",
            "content_identity",
            "evidence_id",
            "path",
            "root",
        }
        if record_schema == 2:
            link_keys |= {
                "declared_material_type",
                "registration_content_identity",
                "registration_id",
                "repository_commit",
                "repository_logical_path",
            }
        _require_keys(link, link_keys, "artefact link")
        evidence_id = cast(str, _require_text(link["evidence_id"], "artefact evidence id"))
        artefact_id = cast(str, _require_text(link["artefact_id"], "artefact id"))
        if evidence_id not in evidence_by_id or (evidence_id, artefact_id) in artefact_keys:
            raise ValueError("artefact link ownership is inconsistent")
        artefact_keys.add((evidence_id, artefact_id))
        artefact_path = cast(str, _require_text(link["path"], "artefact path"))
        if link["root"] not in {"workspace", "external"}:
            raise ValueError("artefact root is unsupported")
        actual_artefact_contract.add((evidence_id, artefact_id, link["root"], artefact_path))
        if type(link["byte_length"]) is not int or link["byte_length"] < 0:
            raise ValueError("artefact byte length is invalid")
        _require_identity(link["content_identity"], "artefact content identity")
        if record_schema == 2:
            registration_id = _require_text(
                link["registration_id"],
                "artefact registration ID",
                nullable=True,
            )
            registration_values = (
                link["registration_content_identity"],
                link["declared_material_type"],
                link["repository_commit"],
                link["repository_logical_path"],
            )
            if registration_id is None:
                if any(value is not None for value in registration_values):
                    raise ValueError("unregistered artefact has registration provenance")
            else:
                _require_identity(
                    link["registration_content_identity"],
                    "registration content identity",
                )
                _require_text(link["declared_material_type"], "declared material type")
                commit = _require_text(
                    link["repository_commit"],
                    "repository commit",
                    nullable=True,
                )
                if commit is not None and (
                    len(commit) not in {40, 64}
                    or any(character not in "0123456789abcdef" for character in commit)
                ):
                    raise ValueError("repository commit identity is invalid")
                _require_text(
                    link["repository_logical_path"],
                    "repository logical path",
                    nullable=True,
                )
                registration_contract = (
                    link["registration_content_identity"],
                    link["declared_material_type"],
                    link["repository_commit"],
                )
                previous = registration_contracts.setdefault(
                    registration_id,
                    registration_contract,
                )
                if previous != registration_contract:
                    raise ValueError("one registration ID has conflicting immutable provenance")
    expected_artefact_contract = {
        (
            identifier,
            cast(str, artefact["id"]),
            cast(str, artefact["root"]),
            cast(str, artefact["path"]),
        )
        for identifier, entry in evidence_by_id.items()
        for artefact in cast(list[dict[str, object]], entry["artefacts"])
    }
    if actual_artefact_contract != expected_artefact_contract:
        raise ValueError("artefact links do not match the dossier artefact contract")
    if record_schema == 2:
        dossier_registrations = {
            (
                identifier,
                cast(str, artefact["id"]),
                artefact.get("registration_id"),
                artefact.get("registration_logical_path"),
            )
            for identifier, entry in evidence_by_id.items()
            for artefact in cast(list[dict[str, object]], entry["artefacts"])
        }
        record_registrations = {
            (
                cast(str, link["evidence_id"]),
                cast(str, link["artefact_id"]),
                link["registration_id"],
                link["repository_logical_path"],
            )
            for link in cast(list[dict[str, object]], artefact_links)
        }
        if dossier_registrations != record_registrations:
            raise ValueError("artefact registration provenance does not match the dossier")

    gaps = _require_list(record["unresolved_gaps"], "$.unresolved_gaps")
    for index, raw in enumerate(gaps):
        gap = _require_object(raw, f"$.unresolved_gaps[{index}]")
        source = gap.get("source")
        expected = (
            _PREREQUISITE_FINDING_KEYS | {"source"}
            if source == "prerequisite"
            else _DECISION_FINDING_KEYS | {"source"}
        )
        if source not in {"prerequisite", "decision"}:
            raise ValueError("unresolved gap source is unsupported")
        _require_keys(gap, expected, "unresolved gap")
        _validate_finding(
            {key: value for key, value in gap.items() if key != "source"},
            prerequisite=source == "prerequisite",
            field=f"$.unresolved_gaps[{index}]",
        )

    triggers = _require_list(record["reassessment_triggers"], "$.reassessment_triggers")
    trigger_ids: list[str] = []
    for index, raw in enumerate(triggers):
        trigger = _require_object(raw, f"$.reassessment_triggers[{index}]")
        _require_keys(trigger, {"evidence_id", "kind", "observation"}, "reassessment trigger")
        trigger_id = cast(str, _require_text(trigger["evidence_id"], "trigger evidence id"))
        trigger_ids.append(trigger_id)
        if trigger_id not in evidence_by_id or trigger["kind"] not in {"assumption", "missing"}:
            raise ValueError("reassessment trigger is inconsistent")
        _require_text(trigger["observation"], "reassessment trigger observation")
    if trigger_ids != sorted(set(trigger_ids)):
        raise ValueError("reassessment triggers are not in canonical unique order")
    _validate_assessment(
        record["assessment"], ruleset_version=ruleset_version, dossier_schema=dossier_schema
    )

    assessment = cast(dict[str, object], record["assessment"])
    if "graph_use" in record:
        _validate_graph_use(record["graph_use"], assessment)
    prerequisite = cast(dict[str, object], assessment["prerequisite_evaluation"])
    ordered = cast(dict[str, object], assessment["ordered_elimination_evaluation"])
    prerequisite_findings = cast(list[dict[str, object]], prerequisite["findings"])
    decision_findings = cast(list[dict[str, object]], ordered["findings"])
    cited_evidence = {
        identifier
        for finding in (*prerequisite_findings, *decision_findings)
        for identifier in cast(list[str], finding["evidence_ids"])
    }
    for condition in cast(list[dict[str, object]], assessment["unmet_conditions"]):
        cited_evidence.update(cast(list[str], condition["evidence_ids"]))
    if not cited_evidence.issubset(evidence_by_id):
        raise ValueError("assessment cites evidence absent from the record")

    expected_gaps = [{**finding, "source": "prerequisite"} for finding in prerequisite_findings]
    expected_gaps.extend(
        {**finding, "source": "decision"}
        for finding in decision_findings
        if finding["effect"] == "require-evidence"
    )
    if gaps != expected_gaps:
        raise ValueError("unresolved gaps are inconsistent with assessment findings")

    expected_triggers: list[dict[str, object]] = []
    for identifier in sorted(evidence_by_id):
        entry = evidence_by_id[identifier]
        kind = entry["kind"]
        if kind == "assumption":
            expected_triggers.append(
                {
                    "evidence_id": identifier,
                    "kind": kind,
                    "observation": entry["falsified_by"],
                }
            )
        elif kind == "missing":
            expected_triggers.append(
                {
                    "evidence_id": identifier,
                    "kind": kind,
                    "observation": entry["resolved_by"],
                }
            )
    if triggers != expected_triggers:
        raise ValueError("reassessment triggers are inconsistent with the dossier")

    payload = cast(
        JsonObject,
        {key: value for key, value in record.items() if key != "record_content_identity"},
    )
    if not masked and record_identity != _identity(canonical_json_bytes(payload)):
        raise ValueError("record content identity is inconsistent")


def resolve_record_path(path: Path, *, root: Path, role: str) -> Path:
    """Return one canonical record's fully resolved path beneath an authorised root.

    Every reader of a generated record shares this boundary, so a record that
    escapes the authorised root, is not a regular file, or cannot be resolved
    safely is refused identically wherever it is read.
    """
    return _resolve_record(path, root=root, role=role)


def load_decision_record(path: Path, *, root: Path, role: str) -> JsonObject:
    """Safely load and validate one canonical record beneath an authorised root."""
    resolved = _resolve_record(path, root=root, role=role)
    return _parse_record(_read_record_bytes(resolved, role=role), role=role)


def _assessment(record: Mapping[str, object]) -> dict[str, object]:
    return cast(dict[str, object], record["assessment"])


def _unmet_condition_ids(assessment: Mapping[str, object]) -> list[str]:
    conditions = cast(list[dict[str, object]], assessment["unmet_conditions"])
    return sorted(cast(str, condition["id"]) for condition in conditions)


def _verdict_value(assessment: Mapping[str, object], source: str) -> JsonValue:
    if source == "unmet_conditions":
        return cast(list[JsonValue], _unmet_condition_ids(assessment))
    value = assessment[source]
    if source == "surviving_candidate_ids":
        return cast(list[JsonValue], sorted(cast(list[str], value)))
    return cast(JsonValue, value)


def _normalise_finding(raw: Mapping[str, object], source: str) -> JsonObject:
    if source == "prerequisite":
        criterion: JsonObject = {
            "counterpart": cast(JsonValue, raw["counterpart"]),
            "field": cast(str, raw["field"]),
        }
    else:
        criterion = {
            "candidate_id": cast(str, raw["candidate_id"]),
            "control_class": cast(str, raw["control_class"]),
            "criterion_id": cast(str, raw["criterion_id"]),
            "criterion_kind": cast(str, raw["criterion_kind"]),
        }
    return {
        "criterion": criterion,
        "effect": cast(str, raw["effect"]),
        "evidence_ids": cast(list[JsonValue], sorted(cast(list[str], raw["evidence_ids"]))),
        "rule_id": cast(str, raw["rule_id"]),
        "source": source,
    }


def _findings(record: Mapping[str, object]) -> list[JsonObject]:
    assessment = _assessment(record)
    prerequisite = cast(dict[str, object], assessment["prerequisite_evaluation"])
    ordered = cast(dict[str, object], assessment["ordered_elimination_evaluation"])
    result = [
        _normalise_finding(raw, "prerequisite")
        for raw in cast(list[dict[str, object]], prerequisite["findings"])
    ]
    result.extend(
        _normalise_finding(raw, "ordered-elimination")
        for raw in cast(list[dict[str, object]], ordered["findings"])
    )
    return sorted(result, key=lambda item: canonical_json_bytes(item))


def _criterion_key(finding: JsonObject) -> bytes:
    return canonical_json_bytes(
        {
            "criterion": finding["criterion"],
            "source": cast(str, finding["source"]),
        }
    )


def _finding_delta(old: list[JsonObject], new: list[JsonObject]) -> JsonObject:
    old_groups: dict[bytes, list[JsonObject]] = {}
    new_groups: dict[bytes, list[JsonObject]] = {}
    for finding in old:
        old_groups.setdefault(_criterion_key(finding), []).append(finding)
    for finding in new:
        new_groups.setdefault(_criterion_key(finding), []).append(finding)
    added: list[JsonValue] = []
    removed: list[JsonValue] = []
    changed: list[JsonValue] = []
    for key in sorted(set(old_groups) | set(new_groups)):
        old_items = list(old_groups.get(key, ()))
        new_items = list(new_groups.get(key, ()))
        old_by_bytes = {canonical_json_bytes(item): item for item in old_items}
        new_by_bytes = {canonical_json_bytes(item): item for item in new_items}
        shared = set(old_by_bytes) & set(new_by_bytes)
        old_remaining = [old_by_bytes[item] for item in sorted(set(old_by_bytes) - shared)]
        new_remaining = [new_by_bytes[item] for item in sorted(set(new_by_bytes) - shared)]
        paired = min(len(old_remaining), len(new_remaining))
        for index in range(paired):
            changed.append({"new": new_remaining[index], "old": old_remaining[index]})
        removed.extend(old_remaining[paired:])
        added.extend(new_remaining[paired:])
    return {"added": added, "changed": changed, "removed": removed}


def _graph_use(record: Mapping[str, object]) -> dict[str, object] | None:
    value = record.get("graph_use")
    return cast(dict[str, object], value) if type(value) is dict else None


def _graph_reference_delta(old: object, new: object) -> JsonObject:
    old_items = cast(list[dict[str, object]], old) if type(old) is list else []
    new_items = cast(list[dict[str, object]], new) if type(new) is list else []
    old_by_id = {cast(str, item["id"]): item for item in old_items}
    new_by_id = {cast(str, item["id"]): item for item in new_items}
    shared = set(old_by_id) & set(new_by_id)
    changed: list[JsonValue] = [
        {
            "id": identifier,
            "new_content_identity": cast(str, new_by_id[identifier]["content_identity"]),
            "old_content_identity": cast(str, old_by_id[identifier]["content_identity"]),
        }
        for identifier in sorted(shared)
        if old_by_id[identifier]["content_identity"] != new_by_id[identifier]["content_identity"]
    ]
    return {
        "added": cast(
            list[JsonValue], [new_by_id[item] for item in sorted(set(new_by_id) - shared)]
        ),
        "changed": changed,
        "removed": cast(
            list[JsonValue], [old_by_id[item] for item in sorted(set(old_by_id) - shared)]
        ),
    }


def _changed_graph(old: Mapping[str, object], new: Mapping[str, object]) -> JsonObject:
    old_use = _graph_use(old)
    new_use = _graph_use(new)
    identities: JsonObject = {}
    for name in (
        "case_view_content_identity",
        "graph_schema_version",
        "graph_snapshot_content_identity",
        "graph_version",
    ):
        old_value = cast(JsonValue, old_use.get(name)) if old_use is not None else None
        new_value = cast(JsonValue, new_use.get(name)) if new_use is not None else None
        identities[name] = {"changed": old_value != new_value, "new": new_value, "old": old_value}
    old_findings = (
        set(cast(list[str], old_use["supported_finding_rule_ids"]))
        if old_use is not None
        else set()
    )
    new_findings = (
        set(cast(list[str], new_use["supported_finding_rule_ids"]))
        if new_use is not None
        else set()
    )
    return {
        "finding_relevant_nodes": _graph_reference_delta(
            old_use.get("finding_relevant_nodes") if old_use is not None else None,
            new_use.get("finding_relevant_nodes") if new_use is not None else None,
        ),
        "finding_relevant_relations": _graph_reference_delta(
            old_use.get("finding_relevant_relations") if old_use is not None else None,
            new_use.get("finding_relevant_relations") if new_use is not None else None,
        ),
        "identities": identities,
        "presence": {
            "changed": (old_use is None) != (new_use is None),
            "new": new_use is not None,
            "old": old_use is not None,
        },
        "supported_finding_rule_ids": {
            "added": cast(list[JsonValue], sorted(new_findings - old_findings)),
            "removed": cast(list[JsonValue], sorted(old_findings - new_findings)),
        },
    }


def _graph_changed_entry_keys(changed_graph: Mapping[str, object]) -> list[JsonObject]:
    result: list[JsonObject] = []
    for public_kind, field in (
        ("node", "finding_relevant_nodes"),
        ("relation", "finding_relevant_relations"),
    ):
        delta = cast(dict[str, list[dict[str, object]]], changed_graph[field])
        identifiers = {
            cast(str, item["id"])
            for name in ("added", "changed", "removed")
            for item in delta[name]
        }
        result.extend({"id": identifier, "kind": public_kind} for identifier in sorted(identifiers))
    return result


def _evidence_entries(record: Mapping[str, object]) -> dict[str, dict[str, object]]:
    dossier = cast(dict[str, object], record["dossier"])
    entries = cast(list[dict[str, object]], dossier["evidence"])
    return {cast(str, entry["id"]): entry for entry in entries}


def _effective_authorship(entry: Mapping[str, object]) -> tuple[str, bool]:
    raw = entry.get("authorship")
    if type(raw) is not dict:
        return ("accountable-person", True)
    authorship = cast(dict[str, object], raw)
    return (
        cast(str, authorship["authored_by"]),
        cast(bool, authorship["attested_by_accountable_person"]),
    )


def _attestation_delta(old: Mapping[str, object], new: Mapping[str, object]) -> list[JsonObject]:
    old_entries = _evidence_entries(old)
    new_entries = _evidence_entries(new)
    result: list[JsonObject] = []
    for identifier in sorted(set(old_entries) & set(new_entries)):
        _, old_attested = _effective_authorship(old_entries[identifier])
        _, new_attested = _effective_authorship(new_entries[identifier])
        if old_attested != new_attested:
            result.append(
                {
                    "evidence_id": identifier,
                    "new": new_attested,
                    "old": old_attested,
                }
            )
    return result


def _attestation_eligibility_changes(
    old: Mapping[str, object], new: Mapping[str, object]
) -> set[str]:
    old_entries = _evidence_entries(old)
    new_entries = _evidence_entries(new)
    changed: set[str] = set()
    for identifier in set(old_entries) & set(new_entries):
        old_entry = old_entries[identifier]
        new_entry = new_entries[identifier]
        old_author, old_attested = _effective_authorship(old_entry)
        new_author, new_attested = _effective_authorship(new_entry)
        old_eligible = old_entry.get("kind") in {"observed", "estimate"} and (
            old_author == "accountable-person" or old_attested
        )
        new_eligible = new_entry.get("kind") in {"observed", "estimate"} and (
            new_author == "accountable-person" or new_attested
        )
        if old_attested != new_attested and old_eligible != new_eligible:
            changed.add(identifier)
    return changed


def _registration_snapshot(record: Mapping[str, object]) -> dict[str, JsonObject]:
    registrations: dict[str, JsonObject] = {}
    for raw in cast(list[dict[str, object]], record["artefact_links"]):
        registration_id = raw.get("registration_id")
        if type(registration_id) is not str:
            continue
        snapshot = registrations.setdefault(
            registration_id,
            {
                "declared_material_type": cast(str, raw["declared_material_type"]),
                "files": [],
                "registration_content_identity": cast(
                    str,
                    raw["registration_content_identity"],
                ),
                "repository_commit": cast(JsonValue, raw["repository_commit"]),
            },
        )
        cast(list[JsonValue], snapshot["files"]).append(
            {
                "artefact_id": cast(str, raw["artefact_id"]),
                "byte_length": cast(int, raw["byte_length"]),
                "content_identity": cast(str, raw["content_identity"]),
                "evidence_id": cast(str, raw["evidence_id"]),
                "repository_logical_path": cast(
                    JsonValue,
                    raw["repository_logical_path"],
                ),
            }
        )
    for snapshot in registrations.values():
        cast(list[JsonValue], snapshot["files"]).sort(
            key=lambda item: (
                cast(dict[str, object], item)["evidence_id"],
                cast(dict[str, object], item)["artefact_id"],
            )
        )
    return registrations


def _registration_delta(old: Mapping[str, object], new: Mapping[str, object]) -> JsonObject:
    old_registrations = _registration_snapshot(old)
    new_registrations = _registration_snapshot(new)
    old_ids = set(old_registrations)
    new_ids = set(new_registrations)
    changed: list[JsonValue] = []
    for registration_id in sorted(old_ids & new_ids):
        old_snapshot = old_registrations[registration_id]
        new_snapshot = new_registrations[registration_id]
        if old_snapshot != new_snapshot:
            changed.append(
                {
                    "new_content_identity": cast(
                        str,
                        new_snapshot["registration_content_identity"],
                    ),
                    "old_content_identity": cast(
                        str,
                        old_snapshot["registration_content_identity"],
                    ),
                    "registration_id": registration_id,
                }
            )
    return {
        "added": cast(list[JsonValue], sorted(new_ids - old_ids)),
        "changed": changed,
        "removed": cast(list[JsonValue], sorted(old_ids - new_ids)),
    }


def compare_decision_records(old: JsonObject, new: JsonObject) -> JsonObject:
    """Return the stable canonical comparison payload for two validated records."""
    old_assessment = _assessment(old)
    new_assessment = _assessment(new)
    verdict_fields: list[JsonValue] = []
    for public_name, source_name in _VERDICT_FIELDS:
        old_value = _verdict_value(old_assessment, source_name)
        new_value = _verdict_value(new_assessment, source_name)
        if old_value != new_value:
            verdict_fields.append({"field": public_name, "new": new_value, "old": old_value})

    old_links = cast(dict[str, dict[str, object]], old["evidence_links"])
    new_links = cast(dict[str, dict[str, object]], new["evidence_links"])
    old_ids = set(old_links)
    new_ids = set(new_links)
    changed_ids = sorted(
        identifier
        for identifier in old_ids & new_ids
        if old_links[identifier]["content_identity"] != new_links[identifier]["content_identity"]
    )
    evidence_delta: JsonObject = {
        "added": cast(list[JsonValue], sorted(new_ids - old_ids)),
        "changed": cast(list[JsonValue], changed_ids),
        "dossier_content_identity": {
            "changed": old["dossier_content_identity"] != new["dossier_content_identity"],
            "new": cast(str, new["dossier_content_identity"]),
            "old": cast(str, old["dossier_content_identity"]),
        },
        "removed": cast(list[JsonValue], sorted(old_ids - new_ids)),
    }

    finding_delta = _finding_delta(_findings(old), _findings(new))
    ruleset_delta: JsonObject = {
        "changed": old["ruleset_version"] != new["ruleset_version"],
        "new": cast(str, new["ruleset_version"]),
        "old": cast(str, old["ruleset_version"]),
    }
    changed_rules: JsonObject = {"findings": finding_delta, "ruleset_version": ruleset_delta}

    all_changed_evidence = set(cast(list[str], evidence_delta["added"]))
    all_changed_evidence.update(cast(list[str], evidence_delta["removed"]))
    all_changed_evidence.update(changed_ids)
    all_finding_evidence = {
        evidence_id
        for finding in (*_findings(old), *_findings(new))
        for evidence_id in cast(list[str], finding["evidence_ids"])
    }
    verdict_changed = bool(verdict_fields)
    causal_evidence = sorted(all_changed_evidence & all_finding_evidence) if verdict_changed else []
    contextual_evidence = sorted(all_changed_evidence - set(causal_evidence))

    finding_change_count = sum(
        len(cast(list[object], finding_delta[name])) for name in ("added", "changed", "removed")
    )
    attestation_changes = _attestation_delta(old, new)
    eligibility_changes = _attestation_eligibility_changes(old, new)
    causal_attestations = (
        sorted(eligibility_changes) if finding_change_count or verdict_changed else []
    )
    contextual_attestations = sorted(
        cast(str, item["evidence_id"])
        for item in attestation_changes
        if item["evidence_id"] not in set(causal_attestations)
    )
    changed_graph = _changed_graph(old, new)
    registration_delta = _registration_delta(old, new)
    changed_registration_ids = {
        *cast(list[str], registration_delta["added"]),
        *cast(list[str], registration_delta["removed"]),
        *(
            cast(str, item["registration_id"])
            for item in cast(list[dict[str, object]], registration_delta["changed"])
        ),
    }
    registration_evidence = {
        cast(str, link["evidence_id"])
        for record in (old, new)
        for link in cast(list[dict[str, object]], record["artefact_links"])
        if link.get("registration_id") in changed_registration_ids
    }
    causal_registrations = (
        sorted(changed_registration_ids)
        if verdict_changed and registration_evidence & all_finding_evidence
        else []
    )
    contextual_registrations = sorted(changed_registration_ids - set(causal_registrations))
    graph_entries = _graph_changed_entry_keys(changed_graph)
    graph_findings = cast(dict[str, list[str]], changed_graph["supported_finding_rule_ids"])
    changed_graph_finding_ids = sorted(
        set(graph_findings["added"]) | set(graph_findings["removed"])
    )
    causes: JsonObject = {
        "attestation_evidence_ids": cast(list[JsonValue], causal_attestations),
        "evidence_ids": cast(list[JsonValue], causal_evidence),
        "finding_changes": finding_change_count if verdict_changed else 0,
        "graph_entries": cast(list[JsonValue], graph_entries if verdict_changed else []),
        "graph_supported_finding_rule_ids": cast(
            list[JsonValue], changed_graph_finding_ids if verdict_changed else []
        ),
        "registration_ids": cast(list[JsonValue], causal_registrations),
    }
    snapshot_fields: list[str] = []
    for field in ("artefact_links", "configuration_content_identity", "tool_version"):
        if old[field] != new[field]:
            snapshot_fields.append(field)
    if cast(dict[str, object], evidence_delta["dossier_content_identity"])["changed"]:
        snapshot_fields.append("dossier_content_identity")
    if ruleset_delta["changed"]:
        snapshot_fields.append("ruleset_version")
    context: JsonObject = {
        "attestation_evidence_ids": cast(list[JsonValue], contextual_attestations),
        "evidence_ids": cast(list[JsonValue], contextual_evidence),
        "finding_changes": 0 if verdict_changed else finding_change_count,
        "graph_entries": cast(list[JsonValue], [] if verdict_changed else graph_entries),
        "graph_identity_fields": cast(
            list[JsonValue],
            sorted(
                name
                for name, delta in cast(
                    dict[str, dict[str, object]], changed_graph["identities"]
                ).items()
                if delta["changed"]
            ),
        ),
        "graph_presence_changed": cast(
            bool, cast(dict[str, object], changed_graph["presence"])["changed"]
        ),
        "graph_supported_finding_rule_ids": cast(
            list[JsonValue], [] if verdict_changed else changed_graph_finding_ids
        ),
        "registration_ids": cast(list[JsonValue], contextual_registrations),
        "snapshot_fields": cast(list[JsonValue], sorted(snapshot_fields)),
    }

    return {
        "causes": causes,
        "changed_attestations": cast(list[JsonValue], attestation_changes),
        "changed_evidence": evidence_delta,
        "changed_graph": changed_graph,
        "changed_registrations": registration_delta,
        "changed_rules": changed_rules,
        "changed_verdict_fields": verdict_fields,
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "context": context,
        "new_record_identity": cast(str, new["record_content_identity"]),
        "old_record_identity": cast(str, old["record_content_identity"]),
        "verdict_delta": {
            "changed": verdict_changed,
            "new": cast(str, new_assessment["verdict"]),
            "old": cast(str, old_assessment["verdict"]),
        },
    }


def canonical_comparison_bytes(comparison: JsonObject) -> bytes:
    """Encode one comparison using the stable canonical JSON contract."""
    return canonical_json_bytes(comparison)


def render_human_comparison(comparison: Mapping[str, object]) -> str:
    """Render a concise deterministic summary without authored record content."""
    evidence = cast(dict[str, object], comparison["changed_evidence"])
    rules = cast(dict[str, object], comparison["changed_rules"])
    findings = cast(dict[str, list[object]], rules["findings"])
    verdict = cast(dict[str, object], comparison["verdict_delta"])
    causes = cast(dict[str, object], comparison["causes"])
    context = cast(dict[str, object], comparison["context"])
    context_evidence = cast(list[str], context["evidence_ids"])
    context_fields = cast(list[str], context["snapshot_fields"])
    graph = cast(dict[str, object], comparison["changed_graph"])
    graph_presence = cast(dict[str, object], graph["presence"])
    graph_identities = cast(dict[str, dict[str, object]], graph["identities"])
    graph_findings = cast(dict[str, list[object]], graph["supported_finding_rule_ids"])
    graph_nodes = cast(dict[str, list[object]], graph["finding_relevant_nodes"])
    graph_relations = cast(dict[str, list[object]], graph["finding_relevant_relations"])
    verdict_text = (
        f"{verdict['old']} -> {verdict['new']}"
        if verdict["changed"]
        else f"{verdict['old']} (unchanged)"
    )
    lines = [
        f"Compared {comparison['old_record_identity']} -> {comparison['new_record_identity']}",
        f"Verdict: {verdict_text}",
        f"Evidence: +{len(cast(Sequence[object], evidence['added']))} "
        f"-{len(cast(Sequence[object], evidence['removed']))} "
        f"~{len(cast(Sequence[object], evidence['changed']))}",
        f"Attestations: ~{len(cast(Sequence[object], comparison['changed_attestations']))}; "
        f"{len(cast(Sequence[object], causes['attestation_evidence_ids']))} causal; "
        f"{len(cast(Sequence[object], context['attestation_evidence_ids']))} contextual",
        f"Findings: +{len(findings['added'])} -{len(findings['removed'])} "
        f"~{len(findings['changed'])}",
        "Graph use: "
        f"{'present' if graph_presence['old'] else 'absent'} -> "
        f"{'present' if graph_presence['new'] else 'absent'}; "
        f"{sum(1 for item in graph_identities.values() if item['changed'])} "
        "identity changes (context)",
        f"Graph findings: +{len(graph_findings['added'])} -{len(graph_findings['removed'])}",
        f"Graph nodes: +{len(graph_nodes['added'])} -{len(graph_nodes['removed'])} "
        f"~{len(graph_nodes['changed'])}",
        f"Graph relations: +{len(graph_relations['added'])} "
        f"-{len(graph_relations['removed'])} ~{len(graph_relations['changed'])}",
        f"Causes: {len(cast(Sequence[object], causes['evidence_ids']))} evidence; "
        f"{causes['finding_changes']} finding changes; "
        f"{len(cast(Sequence[object], causes['graph_entries']))} graph entries; "
        f"{len(cast(Sequence[object], causes['graph_supported_finding_rule_ids']))} "
        "graph findings",
        f"Context: {len(context_evidence)} evidence; {context['finding_changes']} finding changes; "
        f"{len(cast(Sequence[object], context['graph_entries']))} graph entries; "
        f"{len(cast(Sequence[object], context['graph_supported_finding_rule_ids']))} "
        "graph findings; "
        f"{','.join(context_fields) or 'none'}",
    ]
    return "\n".join(lines)
