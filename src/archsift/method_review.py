"""Deterministic validation for the independent architecture-method review protocols."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator

from archsift.diagnostics import Diagnostic, ExitCode
from archsift.method import METHOD_VERSION
from archsift.rules import RULESET_VERSION, RuleEffect, list_rules

PROTOCOL_VERSION = "1.0.0"
RESULT_SCHEMA_VERSION = 1
SUPPORTED_ARCHSIFT_VERSION = "0.1.0"
CORPUS_VERSION = "1.0.0"
REQUIRED_EXAMPLES = (
    "agentic-control",
    "fixed-workflow",
    "insufficient-evidence",
    "no-technology-change",
)
REQUIRED_DECISION_AREAS = (
    "problem-value",
    "agency-necessity",
    "autonomy-permission",
    "comparative-fit",
)
FAILURE_REASONS = (
    "display-only-decision-area",
    "unclassified-disagreement",
    "decision-critical-product-gap",
    "maintainer-intervention",
)

PROTOCOL_VERSION_2 = "2.0.0"
RESULT_SCHEMA_VERSION_2 = 2
REQUIRED_SESSION_COUNT_2 = 4
REQUIRED_PASS_COUNT_2 = 3

MAX_RESULT_BYTES = 128 * 1024
_REQUIREMENT = "METHOD-REVIEW-1.0.0"
_REQUIREMENT_2 = "METHOD-REVIEW-2.0.0"
# The protocol binds the exact public source commit, so only the full 40-character
# lowercase commit ID is a supported source-commit binding.
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class MethodReviewBinding:
    """One published method, ruleset, and example-corpus binding for a cohort result."""

    method_version: str
    ruleset_version: str
    corpus_version: str

    def render(self) -> str:
        """Render the binding for a human diagnostic or summary line."""
        return (
            f"method {self.method_version}, ruleset {self.ruleset_version}, "
            f"corpus {self.corpus_version}"
        )


CURRENT_BINDING = MethodReviewBinding(
    method_version=METHOD_VERSION,
    ruleset_version=RULESET_VERSION,
    corpus_version=CORPUS_VERSION,
)
# Bindings a cohort was published under before the current one. A published result is
# frozen evidence for the versions its sessions actually reviewed, so it stays loadable
# after those versions are superseded. Membership is this explicit enumeration: an
# unrecognised version is never inferred to be merely older.
SUPERSEDED_BINDINGS = (
    MethodReviewBinding(
        method_version="1.2.0",
        ruleset_version="1.8.0",
        corpus_version="1.0.0",
    ),
)
PUBLISHED_BINDINGS = (CURRENT_BINDING, *SUPERSEDED_BINDINGS)
_BINDING_FIELDS = ("method_version", "ruleset_version", "corpus_version")


@dataclass(frozen=True, slots=True)
class MethodReviewValidationResult:
    """One deterministic method-review result-gate outcome."""

    exit_code: ExitCode
    diagnostics: tuple[Diagnostic, ...]
    protocol_version: str | None
    example_count: int
    disagreement_count: int
    criterion_met: bool
    session_count: int = 0
    passed_session_count: int = 0
    binding: MethodReviewBinding | None = None
    binding_superseded: bool = False


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
        file="method-review-results",
        field=field,
        requirement=requirement,
        remediation=remediation,
    )


def _result(
    exit_code: ExitCode,
    diagnostics: Iterable[Diagnostic] = (),
    *,
    protocol_version: str | None = None,
    example_count: int = 0,
    disagreement_count: int = 0,
    session_count: int = 0,
    passed_session_count: int = 0,
) -> MethodReviewValidationResult:
    return MethodReviewValidationResult(
        exit_code=exit_code,
        diagnostics=tuple(diagnostics),
        protocol_version=protocol_version,
        example_count=example_count,
        disagreement_count=disagreement_count,
        criterion_met=exit_code is ExitCode.SUCCESS,
        session_count=session_count,
        passed_session_count=passed_session_count,
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
        raise TypeError("packaged method-review schema must be an object")
    schema = cast(dict[str, Any], raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@cache
def _rule_effects() -> dict[str, RuleEffect]:
    return {rule.id: rule.effect for rule in list_rules()}


@cache
def _verdict_rule_ids() -> frozenset[str]:
    return frozenset(rule.id for rule in list_rules() if rule.id.startswith("verdict-"))


def _path(parts: Iterable[object]) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if type(part) is int else f".{part}"
    return rendered


def _error_sort_key(error: object) -> tuple[tuple[str, str], ...]:
    path = cast(Any, error).absolute_path
    return tuple((type(part).__name__, repr(part)) for part in path)


def _malformed(message: str, remediation: str) -> MethodReviewValidationResult:
    return _result(
        ExitCode.MALFORMED_INPUT,
        (_diagnostic("method-review-results-malformed", message, "$", remediation),),
    )


def _declared_protocol(payload: object) -> str | None:
    if type(payload) is dict and type(payload.get("protocol_version")) is str:
        return cast(str, payload["protocol_version"])
    return None


def _declared_binding(payload: dict[str, object]) -> MethodReviewBinding | None:
    """Return the fully declared version binding, or None when the schema must judge it."""
    declared = tuple(payload.get(field) for field in _BINDING_FIELDS)
    if any(type(value) is not str for value in declared):
        return None
    method, ruleset, corpus = cast(tuple[str, str, str], declared)
    return MethodReviewBinding(
        method_version=method, ruleset_version=ruleset, corpus_version=corpus
    )


def _unpublished_binding_field(
    binding: MethodReviewBinding, published: tuple[MethodReviewBinding, ...]
) -> str:
    """Name the first binding field whose value no published binding uses."""
    for field in _BINDING_FIELDS:
        declared = getattr(binding, field)
        if all(getattr(candidate, field) != declared for candidate in published):
            return field
    # Every value is published, but not in this combination.
    return _BINDING_FIELDS[0]


def _unsupported_binding(
    payload: dict[str, object],
    *,
    schema_version: int,
    protocol_version: str,
    requirement: str,
) -> MethodReviewValidationResult | None:
    supported: tuple[tuple[str, object, str], ...] = (
        ("schema_version", schema_version, "result schema version"),
        ("protocol_version", protocol_version, "protocol version"),
    )
    for field, expected, label in supported:
        declared = payload.get(field)
        if declared is not None and declared != expected:
            return _result(
                ExitCode.UNSUPPORTED_SCHEMA,
                (
                    _diagnostic(
                        "method-review-binding-unsupported",
                        f"The declared {label} is unsupported.",
                        f"$.{field}",
                        f"Use {label} {expected}.",
                        requirement=requirement,
                    ),
                ),
                protocol_version=_declared_protocol(payload),
            )
    binding = _declared_binding(payload)
    if binding is not None and binding not in PUBLISHED_BINDINGS:
        return _result(
            ExitCode.UNSUPPORTED_SCHEMA,
            (
                _diagnostic(
                    "method-review-binding-unsupported",
                    (
                        "The declared method, ruleset, and corpus binding "
                        f"({binding.render()}) is not a published ArchSift binding."
                    ),
                    f"$.{_unpublished_binding_field(binding, PUBLISHED_BINDINGS)}",
                    (
                        "Declare one published binding: "
                        + "; ".join(candidate.render() for candidate in PUBLISHED_BINDINGS)
                        + "."
                    ),
                    requirement=requirement,
                ),
            ),
            protocol_version=_declared_protocol(payload),
        )
    tool_binding = payload.get("archsift_version_or_commit")
    if (
        type(tool_binding) is str
        and tool_binding != SUPPORTED_ARCHSIFT_VERSION
        and _COMMIT.fullmatch(tool_binding) is None
    ):
        return _result(
            ExitCode.UNSUPPORTED_SCHEMA,
            (
                _diagnostic(
                    "method-review-tool-binding-unsupported",
                    "The declared ArchSift version or commit binding is unsupported.",
                    "$.archsift_version_or_commit",
                    (
                        f"Use version {SUPPORTED_ARCHSIFT_VERSION} or the full "
                        "40-character lowercase commit ID."
                    ),
                    requirement=requirement,
                ),
            ),
            protocol_version=_declared_protocol(payload),
        )
    return None


def _set_diagnostic(
    diagnostics: list[Diagnostic],
    *,
    id: str,
    message: str,
    field: str,
    remediation: str,
    requirement: str = _REQUIREMENT,
) -> None:
    diagnostics.append(_diagnostic(id, message, field, remediation, requirement=requirement))


def _trace_diagnostics(
    examples: list[dict[str, object]],
    diagnostics: list[Diagnostic],
    *,
    examples_field: str = "$.examples",
    requirement: str = _REQUIREMENT,
) -> set[str]:
    failure_reasons: set[str] = set()
    rule_effects = _rule_effects()
    example_ids = [cast(str, example["example_id"]) for example in examples]
    if set(example_ids) != set(REQUIRED_EXAMPLES) or len(example_ids) != len(set(example_ids)):
        _set_diagnostic(
            diagnostics,
            id="method-review-example-set",
            message="The review must contain each fixed corpus example exactly once.",
            field=f"{examples_field}",
            remediation="Record each protocol corpus example once without substitutions.",
            requirement=requirement,
        )
    record_ids = [cast(str, example["decision_record_identity"]) for example in examples]
    if len(record_ids) != len(set(record_ids)):
        _set_diagnostic(
            diagnostics,
            id="method-review-record-duplicate",
            message="Each corpus example must bind a distinct generated decision record.",
            field=f"{examples_field}",
            remediation="Record the content identity generated by assessing each fixed example.",
            requirement=requirement,
        )

    for example_index, example in enumerate(examples):
        areas = cast(list[dict[str, object]], example["decision_areas"])
        area_names = [cast(str, area["decision_area"]) for area in areas]
        if set(area_names) != set(REQUIRED_DECISION_AREAS) or len(area_names) != len(
            set(area_names)
        ):
            _set_diagnostic(
                diagnostics,
                id="method-review-area-set",
                message="Each example must contain every required decision area exactly once.",
                field=f"{examples_field}[{example_index}].decision_areas",
                remediation=(
                    "Record problem value, agency necessity, autonomy permission, and "
                    "comparative fit once."
                ),
                requirement=requirement,
            )

        derived_example_pass = True
        for area_index, area in enumerate(areas):
            outcome = cast(str, area["trace_outcome"])
            rule_ids = cast(list[str], area["rule_ids"])
            verdict_rule_id = cast(str | None, area["verdict_rule_id"])
            referenced_rules = [*rule_ids, *([verdict_rule_id] if verdict_rule_id else [])]
            if any(rule_id not in rule_effects for rule_id in referenced_rules):
                _set_diagnostic(
                    diagnostics,
                    id="method-review-rule-reference",
                    message="A decision-area trace references an unknown packaged rule.",
                    field=(
                        f"{examples_field}[{example_index}].decision_areas[{area_index}].rule_ids"
                    ),
                    remediation="Use only rule IDs exposed by the bound ArchSift ruleset.",
                    requirement=requirement,
                )
            if verdict_rule_id is not None and verdict_rule_id not in _verdict_rule_ids():
                _set_diagnostic(
                    diagnostics,
                    id="method-review-verdict-rule-reference",
                    message=(
                        "A decision-area verdict rule reference is not a packaged verdict rule."
                    ),
                    field=(
                        f"{examples_field}[{example_index}].decision_areas"
                        f"[{area_index}].verdict_rule_id"
                    ),
                    remediation=(
                        "Reference the packaged verdict rule that resolves the example (verdict-*)."
                    ),
                    requirement=requirement,
                )
            if outcome == "explicitly-non-decisive" and any(
                rule_effects.get(rule_id) is not RuleEffect.NON_DECISIVE for rule_id in rule_ids
            ):
                _set_diagnostic(
                    diagnostics,
                    id="method-review-non-decisive-trace",
                    message=(
                        "An explicitly non-decisive trace references a decision-affecting "
                        "packaged rule."
                    ),
                    field=(
                        f"{examples_field}[{example_index}].decision_areas[{area_index}].rule_ids"
                    ),
                    remediation=(
                        "Reference only public non-decisive rules that explain the area outcome."
                    ),
                    requirement=requirement,
                )
            if outcome == "causal" and not any(
                rule_effects.get(rule_id) not in {None, RuleEffect.NON_DECISIVE}
                for rule_id in rule_ids
            ):
                _set_diagnostic(
                    diagnostics,
                    id="method-review-causal-trace",
                    message="A causal trace lacks a decision-affecting packaged rule.",
                    field=(
                        f"{examples_field}[{example_index}].decision_areas[{area_index}].rule_ids"
                    ),
                    remediation=(
                        "Reference a public rule whose effect participates in disposition or "
                        "verdict resolution."
                    ),
                    requirement=requirement,
                )
            if outcome == "display-only":
                derived_example_pass = False
                failure_reasons.add("display-only-decision-area")

        declared_example_pass = example["example_result"] == "pass"
        if declared_example_pass != derived_example_pass:
            _set_diagnostic(
                diagnostics,
                id="method-review-example-inconsistent",
                message="An example outcome conflicts with its decision-area traces.",
                field=f"{examples_field}[{example_index}].example_result",
                remediation="Pass an example only when none of its required areas is display-only.",
                requirement=requirement,
            )
    return failure_reasons


def _matching_area(
    disagreement: dict[str, object],
    examples: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the uniquely matching example/area or None when the trace is not unique."""
    example_matches = [
        candidate for candidate in examples if candidate["example_id"] == disagreement["example_id"]
    ]
    if len(example_matches) != 1:
        return None
    area_matches = [
        item
        for item in cast(list[dict[str, object]], example_matches[0]["decision_areas"])
        if item["decision_area"] == disagreement["decision_area"]
    ]
    if len(area_matches) != 1:
        return None
    return area_matches[0]


def _disagreement_diagnostics(
    disagreements: list[dict[str, object]],
    examples: list[dict[str, object]],
    diagnostics: list[Diagnostic],
    *,
    disagreements_field: str = "$.disagreements",
    requirement: str = _REQUIREMENT,
) -> set[str]:
    failure_reasons: set[str] = set()
    rule_effects = _rule_effects()
    disagreement_ids = [cast(str, item["disagreement_id"]) for item in disagreements]
    if len(disagreement_ids) != len(set(disagreement_ids)):
        _set_diagnostic(
            diagnostics,
            id="method-review-disagreement-duplicate",
            message="Disagreement IDs must be unique within the review result.",
            field=f"{disagreements_field}",
            remediation="Assign each disagreement one unused pseudonymous ID.",
            requirement=requirement,
        )

    for index, disagreement in enumerate(disagreements):
        classification = cast(str, disagreement["classification"])
        evidence_ids = cast(list[str], disagreement["evidence_ids"])
        rule_ids = cast(list[str], disagreement["rule_ids"])
        product_gap_id = cast(str | None, disagreement["product_gap_id"])
        trace_is_consistent = (
            (
                classification == "declared-evidence"
                and bool(evidence_ids)
                and not rule_ids
                and product_gap_id is None
            )
            or (
                classification == "public-rule"
                and bool(rule_ids)
                and not evidence_ids
                and product_gap_id is None
            )
            or (
                classification == "product-gap"
                and not evidence_ids
                and not rule_ids
                and product_gap_id is not None
            )
            or (
                classification == "unclassified"
                and not evidence_ids
                and not rule_ids
                and product_gap_id is None
            )
        )
        if not trace_is_consistent:
            _set_diagnostic(
                diagnostics,
                id="method-review-disagreement-inconsistent",
                message=(
                    "A disagreement classification conflicts with its bounded trace references."
                ),
                field=f"{disagreements_field}[{index}]",
                remediation=(
                    "Use only the reference field required by the declared disagreement class."
                ),
                requirement=requirement,
            )
        if classification == "public-rule" and any(
            rule_id not in rule_effects for rule_id in rule_ids
        ):
            _set_diagnostic(
                diagnostics,
                id="method-review-rule-reference",
                message="A disagreement references an unknown packaged rule.",
                field=f"{disagreements_field}[{index}].rule_ids",
                remediation="Use only rule IDs exposed by the bound ArchSift ruleset.",
                requirement=requirement,
            )
        matching_area = _matching_area(disagreement, examples)
        if (
            classification == "declared-evidence"
            and matching_area is not None
            and not set(evidence_ids) <= set(cast(list[str], matching_area["evidence_ids"]))
        ):
            _set_diagnostic(
                diagnostics,
                id="method-review-disagreement-evidence-unbound",
                message=(
                    "A declared-evidence disagreement cites evidence absent from the matching "
                    "area trace."
                ),
                field=f"{disagreements_field}[{index}].evidence_ids",
                remediation=(
                    "Cite only evidence IDs recorded in that example's decision-area trace."
                ),
                requirement=requirement,
            )
        if (
            classification == "public-rule"
            and matching_area is not None
            and not set(rule_ids)
            <= set(
                [
                    *cast(list[str], matching_area["rule_ids"]),
                    *(
                        [cast(str, matching_area["verdict_rule_id"])]
                        if matching_area["verdict_rule_id"]
                        else []
                    ),
                ]
            )
        ):
            _set_diagnostic(
                diagnostics,
                id="method-review-disagreement-rule-unbound",
                message=(
                    "A public-rule disagreement cites a rule absent from the matching area trace."
                ),
                field=f"{disagreements_field}[{index}].rule_ids",
                remediation=(
                    "Cite only packaged rule IDs recorded in that example's decision-area trace."
                ),
                requirement=requirement,
            )
        if classification == "unclassified":
            failure_reasons.add("unclassified-disagreement")
        if classification == "product-gap" and cast(bool, disagreement["decision_critical"]):
            failure_reasons.add("decision-critical-product-gap")
    return failure_reasons


def _validate_v1(payload: dict[str, object]) -> MethodReviewValidationResult:
    errors = sorted(
        _schema_validator("method-review-results-v1").iter_errors(payload),
        key=_error_sort_key,
    )
    if errors:
        first = errors[0]
        return _result(
            ExitCode.VALIDATION_FAILED,
            (
                _diagnostic(
                    "method-review-results-contract",
                    "The result data does not match the method-review-results-v1 contract.",
                    _path(first.absolute_path),
                    "Correct the named field using the protocol and packaged JSON schema.",
                ),
            ),
            protocol_version=_declared_protocol(payload),
        )

    examples = cast(list[dict[str, object]], payload["examples"])
    disagreements = cast(list[dict[str, object]], payload["disagreements"])
    diagnostics: list[Diagnostic] = []
    derived_failures = _trace_diagnostics(examples, diagnostics)
    derived_failures.update(_disagreement_diagnostics(disagreements, examples, diagnostics))
    if cast(bool, payload["maintainer_intervention"]):
        derived_failures.add("maintainer-intervention")

    declared_failures = cast(list[str], payload["failure_reasons"])
    expected_failures = [reason for reason in FAILURE_REASONS if reason in derived_failures]
    if declared_failures != expected_failures:
        _set_diagnostic(
            diagnostics,
            id="method-review-failures-inconsistent",
            message="The declared failure reasons conflict with the review evidence.",
            field="$.failure_reasons",
            remediation="Record each derived protocol failure reason once in protocol order.",
        )

    criterion_met = not derived_failures
    declared_met = payload["overall_result"] == "met"
    if declared_met != criterion_met:
        _set_diagnostic(
            diagnostics,
            id="method-review-overall-inconsistent",
            message="The overall result conflicts with the derived review state.",
            field="$.overall_result",
            remediation=(
                "Claim met only when every trace passes without a critical gap or intervention."
            ),
        )
    if not criterion_met:
        _set_diagnostic(
            diagnostics,
            id="method-review-criterion-not-met",
            message="The independent architecture-method review criterion was not met.",
            field="$.overall_result",
            remediation=(
                "Preserve the review result and address any recorded product gap separately."
            ),
        )

    return _result(
        ExitCode.VALIDATION_FAILED if diagnostics else ExitCode.SUCCESS,
        diagnostics,
        protocol_version=PROTOCOL_VERSION,
        example_count=len(examples),
        disagreement_count=len(disagreements),
    )


def _validate_v2(payload: dict[str, object]) -> MethodReviewValidationResult:
    errors = sorted(
        _schema_validator("method-review-results-v2").iter_errors(payload),
        key=_error_sort_key,
    )
    if errors:
        first = errors[0]
        return _result(
            ExitCode.VALIDATION_FAILED,
            (
                _diagnostic(
                    "method-review-results-contract",
                    "The result data does not match the method-review-results-v2 contract.",
                    _path(first.absolute_path),
                    "Correct the named field using the protocol and packaged JSON schema.",
                    requirement=_REQUIREMENT_2,
                ),
            ),
            protocol_version=PROTOCOL_VERSION_2,
        )

    sessions = cast(list[dict[str, object]], payload["sessions"])
    diagnostics: list[Diagnostic] = []
    products = [cast(str, session["agent_product"]) for session in sessions]
    if len(products) != len(set(products)):
        _set_diagnostic(
            diagnostics,
            id="method-review-agent-product-duplicate",
            message="Agent product names must be unique within the four-session simulated cohort.",
            field="$.sessions",
            remediation="Assign each independent simulated session one distinct agent product.",
            requirement=_REQUIREMENT_2,
        )

    passed_session_count = 0
    disagreement_count = 0
    for index, session in enumerate(sessions):
        examples = cast(list[dict[str, object]], session["examples"])
        disagreements = cast(list[dict[str, object]], session["disagreements"])
        disagreement_count += len(disagreements)
        derived_failures = _trace_diagnostics(
            examples,
            diagnostics,
            examples_field=f"$.sessions[{index}].examples",
            requirement=_REQUIREMENT_2,
        )
        derived_failures.update(
            _disagreement_diagnostics(
                disagreements,
                examples,
                diagnostics,
                disagreements_field=f"$.sessions[{index}].disagreements",
                requirement=_REQUIREMENT_2,
            )
        )
        if cast(bool, session["maintainer_intervention"]):
            derived_failures.add("maintainer-intervention")

        declared_failures = cast(list[str], session["failure_reasons"])
        expected_failures = [reason for reason in FAILURE_REASONS if reason in derived_failures]
        if declared_failures != expected_failures:
            _set_diagnostic(
                diagnostics,
                id="method-review-failures-inconsistent",
                message="The declared failure reasons conflict with the review evidence.",
                field=f"$.sessions[{index}].failure_reasons",
                remediation="Record each derived protocol failure reason once in protocol order.",
                requirement=_REQUIREMENT_2,
            )

        session_passed = not derived_failures
        if session_passed:
            passed_session_count += 1
        declared_pass = session["session_result"] == "pass"
        if declared_pass != session_passed:
            _set_diagnostic(
                diagnostics,
                id="method-review-session-inconsistent",
                message="A session outcome conflicts with its review evidence.",
                field=f"$.sessions[{index}].session_result",
                remediation=(
                    "Pass a session only when its trace, disagreements, and intervention "
                    "state meet the session criterion."
                ),
                requirement=_REQUIREMENT_2,
            )

    criterion_met = passed_session_count >= REQUIRED_PASS_COUNT_2
    declared_met = payload["overall_result"] == "met"
    if declared_met != criterion_met:
        _set_diagnostic(
            diagnostics,
            id="method-review-overall-inconsistent",
            message="The overall result conflicts with the derived cohort state.",
            field="$.overall_result",
            remediation=(
                "Claim met only when at least three of exactly four simulated sessions pass."
            ),
            requirement=_REQUIREMENT_2,
        )
    if not criterion_met:
        _set_diagnostic(
            diagnostics,
            id="method-review-criterion-not-met",
            message="The simulated architecture-method review criterion was not met.",
            field="$.overall_result",
            remediation=(
                "Preserve the cohort result and address any recorded product gap separately."
            ),
            requirement=_REQUIREMENT_2,
        )

    return _result(
        ExitCode.VALIDATION_FAILED if diagnostics else ExitCode.SUCCESS,
        diagnostics,
        protocol_version=PROTOCOL_VERSION_2,
        example_count=len(REQUIRED_EXAMPLES),
        disagreement_count=disagreement_count,
        session_count=len(sessions),
        passed_session_count=passed_session_count,
    )


def _bound(
    result: MethodReviewValidationResult,
    binding: MethodReviewBinding | None,
) -> MethodReviewValidationResult:
    """Attach the resolved binding and report superseded evidence under its own code.

    ``PUBLISHED_BINDINGS[0]`` is the current binding by construction. A superseded result that
    still satisfies its contract exits `SUPERSEDED_BINDING` so that neither a caller
    reading only the exit code nor one reading only the status can mistake it for a
    cohort run against the current binding. A result that violates its contract keeps
    the failure code that contract violation already earned.
    """
    if binding is None or binding == PUBLISHED_BINDINGS[0]:
        return replace(result, binding=binding)
    contract_met = result.exit_code is ExitCode.SUCCESS or (
        result.exit_code is ExitCode.VALIDATION_FAILED
        and {item.id for item in result.diagnostics} == {"method-review-criterion-not-met"}
    )
    return replace(
        result,
        exit_code=ExitCode.SUPERSEDED_BINDING if contract_met else result.exit_code,
        binding=binding,
        binding_superseded=True,
    )


def validate_method_review_results(path: Path) -> MethodReviewValidationResult:
    """Validate one completed protocol result file and its success criterion."""
    try:
        content = path.read_bytes()
    except OSError:
        return _result(
            ExitCode.ARTEFACT_UNAVAILABLE,
            (
                _diagnostic(
                    "method-review-results-unavailable",
                    "The requested method-review result file is unavailable.",
                    "$",
                    "Provide a readable regular JSON file.",
                ),
            ),
        )
    if len(content) > MAX_RESULT_BYTES:
        return _malformed(
            "The method-review result file exceeds the supported size limit.",
            f"Provide a result file no larger than {MAX_RESULT_BYTES} bytes.",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError:
        return _malformed(
            "The method-review result file is not valid UTF-8.",
            "Encode the completed JSON result as UTF-8.",
        )
    except (json.JSONDecodeError, _DuplicateKeyError, _InvalidConstantError, RecursionError):
        return _malformed(
            "The method-review result file is not strict JSON.",
            "Provide one JSON object without duplicate keys or non-standard numbers.",
        )

    if type(payload) is not dict:
        return _validate_v1(cast(dict[str, object], payload))

    result_payload = cast(dict[str, object], payload)
    declared_schema = result_payload.get("schema_version")
    declared_protocol = result_payload.get("protocol_version")
    if declared_schema == RESULT_SCHEMA_VERSION and declared_protocol == PROTOCOL_VERSION:
        unsupported = _unsupported_binding(
            result_payload,
            schema_version=RESULT_SCHEMA_VERSION,
            protocol_version=PROTOCOL_VERSION,
            requirement=_REQUIREMENT,
        )
        if unsupported is not None:
            return unsupported
        return _bound(_validate_v1(result_payload), _declared_binding(result_payload))
    if declared_schema == RESULT_SCHEMA_VERSION_2 and declared_protocol == PROTOCOL_VERSION_2:
        unsupported = _unsupported_binding(
            result_payload,
            schema_version=RESULT_SCHEMA_VERSION_2,
            protocol_version=PROTOCOL_VERSION_2,
            requirement=_REQUIREMENT_2,
        )
        if unsupported is not None:
            return unsupported
        return _bound(_validate_v2(result_payload), _declared_binding(result_payload))
    return _result(
        ExitCode.UNSUPPORTED_SCHEMA,
        (
            _diagnostic(
                "method-review-binding-unsupported",
                "The declared result schema or protocol version is unsupported.",
                "$.schema_version",
                f"Use schema version {RESULT_SCHEMA_VERSION} with protocol {PROTOCOL_VERSION}, "
                f"or schema version {RESULT_SCHEMA_VERSION_2} with protocol {PROTOCOL_VERSION_2}.",
            ),
        ),
        protocol_version=_declared_protocol(result_payload),
    )


__all__ = [
    "CORPUS_VERSION",
    "CURRENT_BINDING",
    "FAILURE_REASONS",
    "PROTOCOL_VERSION",
    "PROTOCOL_VERSION_2",
    "PUBLISHED_BINDINGS",
    "REQUIRED_DECISION_AREAS",
    "REQUIRED_EXAMPLES",
    "REQUIRED_PASS_COUNT_2",
    "REQUIRED_SESSION_COUNT_2",
    "RESULT_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION_2",
    "SUPERSEDED_BINDINGS",
    "SUPPORTED_ARCHSIFT_VERSION",
    "MethodReviewBinding",
    "MethodReviewValidationResult",
    "validate_method_review_results",
]
