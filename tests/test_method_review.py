from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.method import METHOD_VERSION
from archsift.method_review import (
    CORPUS_VERSION,
    FAILURE_REASONS,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_2,
    REQUIRED_DECISION_AREAS,
    REQUIRED_EXAMPLES,
    REQUIRED_PASS_COUNT_2,
    REQUIRED_SESSION_COUNT_2,
    RESULT_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION_2,
    SUPPORTED_ARCHSIFT_VERSION,
    validate_method_review_results,
)
from archsift.rules import RULESET_VERSION

_TRACE_RULES = {
    "problem-value": "binding-outcome-met",
    "agency-necessity": "agentic-runtime-adaptation-supports-agency",
    "autonomy-permission": "mandatory-human-control-retained",
    "comparative-fit": "binding-constraint-met",
}
_TRACE_EVIDENCE = {
    "problem-value": "decision-observed",
    "agency-necessity": "agency-observed",
    "autonomy-permission": "autonomy-observed",
    "comparative-fit": "decision-observed",
}


def _area(name: str, *, outcome: str = "causal") -> dict[str, Any]:
    rule_id = _TRACE_RULES[name]
    if outcome == "explicitly-non-decisive":
        rule_id = "agentic-agency-fact-non-decisive"
    return {
        "decision_area": name,
        "trace_outcome": outcome,
        "rule_ids": [rule_id],
        "evidence_ids": [_TRACE_EVIDENCE[name]],
        "candidate_ids": [] if outcome == "display-only" else ["reviewed-candidate"],
        "verdict_rule_id": None if outcome == "display-only" else "verdict-supported",
    }


def _example(index: int, example_id: str) -> dict[str, Any]:
    areas = [_area(name) for name in REQUIRED_DECISION_AREAS]
    if index == 1:
        areas[1] = _area("agency-necessity", outcome="explicitly-non-decisive")
    return {
        "example_id": example_id,
        "decision_record_identity": f"sha256:{index:064x}",
        "decision_areas": areas,
        "example_result": "pass",
    }


def _review() -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "archsift_version_or_commit": SUPPORTED_ARCHSIFT_VERSION,
        "method_version": METHOD_VERSION,
        "ruleset_version": RULESET_VERSION,
        "corpus_version": CORPUS_VERSION,
        "reviewer": {
            "reviewer_id": "reviewer-01",
            "target_reviewer_eligible": True,
            "independent": True,
            "environment": {
                "operating_system": "linux",
                "python_version": "3.11",
                "install_mode": "built-wheel",
            },
        },
        "maintainer_intervention": False,
        "examples": [
            _example(index, example_id)
            for index, example_id in enumerate(REQUIRED_EXAMPLES, start=1)
        ],
        "disagreements": [],
        "overall_result": "met",
        "failure_reasons": [],
    }


def _disagreement(classification: str, *, critical: bool) -> dict[str, Any]:
    return {
        "disagreement_id": "disagreement-01",
        "example_id": "agentic-control",
        "decision_area": "agency-necessity",
        "classification": classification,
        "decision_critical": critical,
        "evidence_ids": ["agency-observed"] if classification == "declared-evidence" else [],
        "rule_ids": (
            ["agentic-runtime-adaptation-supports-agency"]
            if classification == "public-rule"
            else []
        ),
        "product_gap_id": "gap-trace-coverage" if classification == "product-gap" else None,
    }


def _write_result(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_packaged_schema_and_corpus_bindings_are_valid() -> None:
    root = Path(__file__).parents[1]
    schema_path = root / "src/archsift/schemas/method-review-results-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "examples/manifest.json").read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert schema["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION
    assert schema["properties"]["archsift_version_or_commit"]["oneOf"][0]["const"] == (
        SUPPORTED_ARCHSIFT_VERSION
    )
    assert (
        schema["properties"]["archsift_version_or_commit"]["oneOf"][1]["pattern"]
        == "^[0-9a-f]{40}$"
    )
    assert schema["properties"]["method_version"]["const"] == METHOD_VERSION
    assert schema["properties"]["ruleset_version"]["const"] == RULESET_VERSION
    assert schema["properties"]["corpus_version"]["const"] == CORPUS_VERSION
    assert manifest["corpus_version"] == CORPUS_VERSION
    assert tuple(item["path"] for item in manifest["examples"]) == REQUIRED_EXAMPLES
    example_ids = schema["$defs"]["exampleId"]["enum"]
    assert tuple(example_ids) == REQUIRED_EXAMPLES
    decision_areas = schema["$defs"]["decisionArea"]["enum"]
    assert tuple(decision_areas) == REQUIRED_DECISION_AREAS
    failure_reasons = schema["properties"]["failure_reasons"]["items"]["enum"]
    assert tuple(failure_reasons) == FAILURE_REASONS


def test_complete_review_meets_criterion(tmp_path: Path) -> None:
    path = tmp_path / "method-review-results.json"
    _write_result(path, _review())

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.example_count == 4
    assert result.disagreement_count == 0
    assert result.criterion_met is True
    assert result.diagnostics == ()


def test_public_source_commit_binding_is_supported(tmp_path: Path) -> None:
    payload = _review()
    payload["archsift_version_or_commit"] = "6517a88995715f710d7e3b2ec4796e4cb51cdd5d"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS


def test_cli_reports_success_in_human_and_json_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "method-review-results.json"
    _write_result(path, _review())

    assert main(["method-review-results", str(path)]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == (
        "Architecture-method review criterion met: 4 examples reviewed (protocol 1.0.0)\n"
    )

    assert main(["method-review-results", str(path), "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "criterion_met": True,
        "diagnostics": [],
        "disagreement_count": 0,
        "example_count": 4,
        "exit_code": 0,
        "protocol_version": "1.0.0",
        "status": "criterion-met",
    }


def test_missing_corpus_example_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"].pop()
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_duplicate_corpus_example_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][3]["example_id"] = "agentic-control"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.criterion_met is False
    assert "method-review-example-set" in [item.id for item in result.diagnostics]


def test_duplicate_decision_record_identity_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][3]["decision_record_identity"] = payload["examples"][0][
        "decision_record_identity"
    ]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-record-duplicate"


def test_missing_decision_area_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"].pop()
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_invalid_decision_area_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0]["decision_area"] = "visibility"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"


def test_display_only_area_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = _area("problem-value", outcome="display-only")
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == [
        "method-review-example-inconsistent",
        "method-review-failures-inconsistent",
        "method-review-overall-inconsistent",
        "method-review-criterion-not-met",
    ]


def test_unclassified_disagreement_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["disagreements"] = [_disagreement("unclassified", critical=False)]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_decision_critical_product_gap_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["disagreements"] = [_disagreement("product-gap", critical=True)]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_maintainer_intervention_cannot_be_marked_successful(tmp_path: Path) -> None:
    payload = _review()
    payload["maintainer_intervention"] = True
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-criterion-not-met" in [item.id for item in result.diagnostics]


def test_false_overall_success_claim_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = _area("problem-value", outcome="display-only")
    payload["examples"][0]["example_result"] = "fail"
    payload["failure_reasons"] = ["display-only-decision-area"]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == [
        "method-review-overall-inconsistent",
        "method-review-criterion-not-met",
    ]


@pytest.mark.parametrize(
    ("field", "value", "diagnostic_id"),
    [
        ("schema_version", 2, "method-review-binding-unsupported"),
        ("protocol_version", "2.0.0", "method-review-binding-unsupported"),
        ("method_version", "2.0.0", "method-review-binding-unsupported"),
        ("ruleset_version", "2.0.0", "method-review-binding-unsupported"),
        ("corpus_version", "2.0.0", "method-review-binding-unsupported"),
        ("archsift_version_or_commit", "9.9.9", "method-review-tool-binding-unsupported"),
    ],
)
def test_version_binding_mismatch_is_unsupported(
    tmp_path: Path, field: str, value: object, diagnostic_id: str
) -> None:
    payload = _review()
    payload[field] = value
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == diagnostic_id


def test_invalid_tool_binding_is_unsupported(tmp_path: Path) -> None:
    payload = _review()
    payload["archsift_version_or_commit"] = "main"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "method-review-tool-binding-unsupported"


def test_inconsistent_disagreement_trace_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    disagreement = _disagreement("public-rule", critical=False)
    disagreement["evidence_ids"] = ["agency-observed"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-disagreement-inconsistent"


def test_unknown_trace_rule_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0]["rule_ids"] = ["unknown-rule"]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-rule-reference"


def test_causal_trace_without_decision_affecting_rule_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = {
        "decision_area": "problem-value",
        "trace_outcome": "causal",
        "rule_ids": ["agentic-agency-fact-non-decisive"],
        "evidence_ids": ["decision-observed"],
        "candidate_ids": ["reviewed-candidate"],
        "verdict_rule_id": None,
    }
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-causal-trace" in [item.id for item in result.diagnostics]


def test_non_decisive_trace_without_non_decisive_rule_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = {
        "decision_area": "problem-value",
        "trace_outcome": "explicitly-non-decisive",
        "rule_ids": ["binding-outcome-met"],
        "evidence_ids": ["decision-observed"],
        "candidate_ids": ["reviewed-candidate"],
        "verdict_rule_id": "verdict-supported",
    }
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-non-decisive-trace" in [item.id for item in result.diagnostics]


def test_duplicate_decision_area_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][3] = payload["examples"][0]["decision_areas"][0]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-area-set" in [item.id for item in result.diagnostics]


def test_duplicate_disagreement_id_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["disagreements"] = [
        _disagreement("declared-evidence", critical=False),
        _disagreement("public-rule", critical=False),
    ]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-disagreement-duplicate" in [item.id for item in result.diagnostics]


def test_failure_reasons_are_enforced_in_protocol_order(tmp_path: Path) -> None:
    payload = _review()
    payload["maintainer_intervention"] = True
    payload["overall_result"] = "not-met"
    payload["failure_reasons"] = ["maintainer-intervention"]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == ["method-review-criterion-not-met"]

    payload = _review()
    payload["examples"][0]["decision_areas"][0] = _area("problem-value", outcome="display-only")
    payload["examples"][0]["example_result"] = "fail"
    payload["overall_result"] = "not-met"
    payload["failure_reasons"] = ["maintainer-intervention", "display-only-decision-area"]
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-failures-inconsistent" in [item.id for item in result.diagnostics]


@pytest.mark.parametrize(
    ("classification", "critical"),
    [
        ("declared-evidence", True),
        ("public-rule", True),
        ("product-gap", False),
    ],
)
def test_consistent_disagreement_classifications_are_accepted(
    tmp_path: Path, classification: str, critical: bool
) -> None:
    payload = _review()
    disagreement = _disagreement(classification, critical=critical)
    if classification == "public-rule":
        # Bind the method disagreement to a decision-affecting rule actually cited in
        # agentic-control's problem-value trace.
        disagreement["decision_area"] = "problem-value"
        disagreement["rule_ids"] = ["binding-outcome-met"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.disagreement_count == 1


def test_disagreement_referencing_unknown_rule_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    disagreement = _disagreement("public-rule", critical=False)
    disagreement["rule_ids"] = ["unknown-rule"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-rule-reference" in [item.id for item in result.diagnostics]


def test_causal_area_cannot_launder_non_causal_rules_via_verdict_field(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = {
        "decision_area": "problem-value",
        "trace_outcome": "causal",
        "rule_ids": ["agentic-agency-fact-non-decisive"],
        "evidence_ids": ["decision-observed"],
        "candidate_ids": [],
        "verdict_rule_id": "binding-outcome-met",
    }
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    diagnostic_ids = [item.id for item in result.diagnostics]
    assert "method-review-causal-trace" in diagnostic_ids
    assert "method-review-verdict-rule-reference" in diagnostic_ids


def test_verdict_rule_reference_must_be_a_packaged_verdict_rule(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = {
        "decision_area": "problem-value",
        "trace_outcome": "causal",
        "rule_ids": ["binding-outcome-met"],
        "evidence_ids": ["decision-observed"],
        "candidate_ids": ["reviewed-candidate"],
        "verdict_rule_id": "binding-outcome-met",
    }
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-verdict-rule-reference" in [item.id for item in result.diagnostics]


def test_non_decisive_area_cannot_mix_decision_affecting_rules(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][0] = {
        "decision_area": "problem-value",
        "trace_outcome": "explicitly-non-decisive",
        "rule_ids": ["agentic-agency-fact-non-decisive", "binding-outcome-met"],
        "evidence_ids": ["decision-observed"],
        "candidate_ids": ["reviewed-candidate"],
        "verdict_rule_id": "verdict-supported",
    }
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-non-decisive-trace" in [item.id for item in result.diagnostics]


def test_non_decisive_area_with_only_non_decisive_rules_is_accepted(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"] = [
        _area(name, outcome="explicitly-non-decisive") for name in REQUIRED_DECISION_AREAS
    ]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.criterion_met is True


def test_declared_evidence_disagreement_must_cite_area_trace_evidence(tmp_path: Path) -> None:
    payload = _review()
    disagreement = _disagreement("declared-evidence", critical=False)
    disagreement["evidence_ids"] = ["fabricated-evidence"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-disagreement-evidence-unbound" in [item.id for item in result.diagnostics]


def test_public_rule_disagreement_must_cite_area_trace_rule(tmp_path: Path) -> None:
    payload = _review()
    disagreement = _disagreement("public-rule", critical=False)
    disagreement["rule_ids"] = ["binding-outcome-met"]
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-disagreement-rule-unbound" in [item.id for item in result.diagnostics]


def test_disagreement_for_missing_area_is_rejected_without_internal_error(tmp_path: Path) -> None:
    payload = _review()
    payload["examples"][0]["decision_areas"][3] = payload["examples"][0]["decision_areas"][0]
    disagreement = _disagreement("declared-evidence", critical=False)
    disagreement["decision_area"] = "comparative-fit"
    payload["disagreements"] = [disagreement]
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert "method-review-area-set" in [item.id for item in result.diagnostics]


def test_abbreviated_commit_binding_is_rejected(tmp_path: Path) -> None:
    payload = _review()
    payload["archsift_version_or_commit"] = "dbde5cc"
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "method-review-tool-binding-unsupported"


def test_strict_json_rejects_duplicate_object_key(tmp_path: Path) -> None:
    path = tmp_path / "method-review-results.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "method-review-results-malformed"


def test_quiet_failure_emits_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _review()
    payload["maintainer_intervention"] = True
    path = tmp_path / "method-review-results.json"
    _write_result(path, payload)

    assert main(["method-review-results", str(path), "--quiet"]) == ExitCode.VALIDATION_FAILED
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_public_docs_freeze_protocol_and_exact_offline_command() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs/method-review-v1.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    protocol_words = " ".join(protocol.split())

    assert "protocol 1.0.0" in protocol_words
    assert "method 1.2.0" in protocol_words
    assert "ruleset 1.8.0" in protocol_words
    assert "corpus 1.0.0" in protocol_words
    assert (
        "problem value, agency necessity, autonomy permission, and comparative fit"
        in protocol_words
    )
    assert "no independent review has been run" in protocol_words
    command = "archsift method-review-results method-review-results.json"
    assert command in protocol
    assert command in readme
    assert "docs/method-review-v1.md" in readme


# --- Protocol 2.0.0 simulated cohort ---

_SIMULATED_PRODUCTS = ("claude-code", "codex", "opencode", "pi")


def _simulated_session(index: int, product: str) -> dict[str, Any]:
    return {
        "session_id": f"session-{index:02d}",
        "agent_product": product,
        "agent_model": f"model-{product}",
        "harness_version": "1.0.0",
        "fresh_session": True,
        "environment": {
            "operating_system": "linux",
            "python_version": "3.11",
            "install_mode": "source-checkout",
        },
        "examples": [
            _example(example_index, example_id)
            for example_index, example_id in enumerate(REQUIRED_EXAMPLES, start=1)
        ],
        "disagreements": [],
        "maintainer_intervention": False,
        "failure_reasons": [],
        "session_result": "pass",
    }


def _simulated_cohort(pass_count: int) -> dict[str, Any]:
    sessions = [
        _simulated_session(index, product)
        for index, product in enumerate(_SIMULATED_PRODUCTS, start=1)
    ]
    for index in range(pass_count, 4):
        sessions[index]["examples"][0]["decision_areas"][0] = _area(
            "problem-value", outcome="display-only"
        )
        sessions[index]["examples"][0]["example_result"] = "fail"
        sessions[index]["session_result"] = "fail"
        sessions[index]["failure_reasons"] = ["display-only-decision-area"]
    return {
        "schema_version": RESULT_SCHEMA_VERSION_2,
        "protocol_version": PROTOCOL_VERSION_2,
        "archsift_version_or_commit": "77607067db3119bf74598a2b859e758cd003f281",
        "method_version": METHOD_VERSION,
        "ruleset_version": RULESET_VERSION,
        "corpus_version": CORPUS_VERSION,
        "overall_result": "met" if pass_count >= REQUIRED_PASS_COUNT_2 else "not-met",
        "sessions": sessions,
    }


def test_packaged_simulated_method_review_schema_is_valid() -> None:
    path = Path(__file__).parents[1] / "src/archsift/schemas/method-review-results-v2.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION_2
    assert schema["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION_2
    assert schema["properties"]["sessions"]["minItems"] == REQUIRED_SESSION_COUNT_2
    assert schema["properties"]["sessions"]["maxItems"] == REQUIRED_SESSION_COUNT_2
    session = schema["$defs"]["session"]
    assert session["properties"]["fresh_session"]["const"] is True
    assert session["properties"]["examples"]["items"]["$ref"].endswith("/exampleReview")
    assert REQUIRED_PASS_COUNT_2 == 3


def test_three_of_four_simulated_sessions_meets_criterion(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _simulated_cohort(3))

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION_2
    assert result.session_count == 4
    assert result.passed_session_count == 3
    assert result.criterion_met is True
    assert result.diagnostics == ()


def test_two_of_four_simulated_sessions_rejects_the_cohort(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _simulated_cohort(2))

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.passed_session_count == 2
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["method-review-criterion-not-met"]


def test_duplicate_agent_product_is_rejected(tmp_path: Path) -> None:
    payload = _simulated_cohort(4)
    payload["sessions"][3]["agent_product"] = payload["sessions"][0]["agent_product"]
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["method-review-agent-product-duplicate"]


def test_simulated_session_outcome_must_match_evidence(tmp_path: Path) -> None:
    payload = _simulated_cohort(4)
    payload["sessions"][3]["examples"][0]["decision_areas"][0] = _area(
        "problem-value", outcome="display-only"
    )
    payload["sessions"][3]["examples"][0]["example_result"] = "fail"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    ids = [item.id for item in result.diagnostics]
    assert "method-review-session-inconsistent" in ids
    assert "method-review-failures-inconsistent" in ids
    assert result.passed_session_count == 3  # three of four sessions still pass


def test_simulated_requires_exactly_four_sessions(tmp_path: Path) -> None:
    payload = _simulated_cohort(3)
    payload["sessions"].pop()
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"
    assert result.diagnostics[0].field == "$.sessions"


def test_simulated_session_extra_field_is_rejected(tmp_path: Path) -> None:
    payload = _simulated_cohort(3)
    payload["sessions"][0]["reviewer_name"] = "private identity"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "method-review-results-contract"
    assert result.diagnostics[0].field == "$.sessions[0]"


def test_simulated_with_v1_protocol_is_unsupported(tmp_path: Path) -> None:
    payload = _simulated_cohort(3)
    payload["protocol_version"] = PROTOCOL_VERSION
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "method-review-binding-unsupported"


def test_unknown_schema_version_is_unsupported(tmp_path: Path) -> None:
    payload = _simulated_cohort(3)
    payload["schema_version"] = 3
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "method-review-binding-unsupported"


def test_simulated_cli_reports_success_in_human_and_json_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _simulated_cohort(3))

    assert main(["method-review-results", str(path)]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == (
        "Architecture-method review criterion met: 3 of 4 sessions passed (protocol 2.0.0)\n"
    )

    assert main(["method-review-results", str(path), "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "criterion-met"
    assert output["criterion_met"] is True
    assert output["protocol_version"] == "2.0.0"
    assert output["session_count"] == 4
    assert output["passed_session_count"] == 3


def test_v1_review_still_meets_criterion(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _review())

    result = validate_method_review_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 0
    assert result.passed_session_count == 0


def test_public_docs_freeze_protocol_v2_and_offline_command() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs/method-review-v2.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    protocol_words = " ".join(protocol.split())

    assert "protocol 2.0.0" in protocol_words
    assert "exactly four independent simulated review sessions" in protocol_words
    assert "at least three of the four sessions" in protocol_words
    assert "simulated review cohort has been run" in protocol_words
    assert "criterion-not-met" in protocol_words
    assert "no claim that a human architect passed" in protocol_words
    assert "no agentic candidate is represented" in protocol_words
    assert "agentic-agency-fact-non-decisive" in protocol_words
    assert "autonomy-boundary-non-decisive" in protocol_words
    assert "explicitly-non-decisive" in protocol_words
    assert "archsift method-review-results method-review-results.json" in protocol
    assert "docs/method-review-v2.md" in readme
    assert "method-review-results.json" in readme
